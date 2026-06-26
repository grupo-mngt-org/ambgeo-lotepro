"""Análise de CIDADE INTEIRA: do limite municipal aos lotes vazios ranqueados.

Pipeline (roda como job em background, com progresso):
  1. Limite municipal exato (Nominatim, por OSM ID quando vier do autocomplete).
  2. Malha viária completa do município (Overpass/OSMnx).
  3. Áreas de exclusão (praças, escolas, cemitérios, água…).
  4. Edificações de alta cobertura (Microsoft Building Footprints, cache local).
  5. Particiona o município em QUADRAS (vias + exclusões subtraídas).
  6. Detecção de vazios por quadra (core/detect.py, filtros anti-falso-positivo).
  7. Qualificação + score (relevo só para os maiores — API pública tem cota).

Município muito extenso (> MAX_CITY_KM2) é recusado com orientação — a malha
urbana de municípios gigantes deve ser analisada por endereço + raio.
"""
from __future__ import annotations

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely import union_all

from . import detect, enrich, geo, io, osm, report, score, store
from .pipeline import qualify
from ..providers.base import DetectionParams

MAX_CITY_KM2 = 4_000.0
# Quadras maiores que isso são glebas rurais fora da malha — ignoradas.
BLOCK_MAX_FACTOR = 4.0
DEM_TOP_LOTS = 150          # nº de lotes (maiores) com consulta de relevo
OSM_FALLBACK_MAX_KM2 = 300.0

# Retém a tag `surface` nas vias (alimenta o score de acesso/pavimentação).
if "surface" not in ox.settings.useful_tags_way:
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["surface"]


def _boundary_gdf(city_query: str, osm_type: str | None, osm_id) -> gpd.GeoDataFrame:
    """Limite municipal. Prioriza o OSM ID exato vindo do autocomplete."""
    g = None
    if osm_type in ("R", "W") and osm_id:
        try:
            g = ox.geocode_to_gdf(f"{osm_type}{int(osm_id)}", by_osmid=True)
        except Exception:
            g = None
    if g is None:
        try:
            g = ox.geocode_to_gdf(city_query)
        except Exception as exc:
            raise ValueError(f"Cidade não encontrada: {city_query!r}.") from exc
    g = g[g.geometry.type.isin(["Polygon", "MultiPolygon"])]
    if g.empty:
        raise ValueError(
            "Não encontrei o polígono do limite municipal — selecione a cidade "
            "na lista de sugestões do campo de busca.")
    return g.iloc[[0]].reset_index(drop=True)


def _city_roads(polygon) -> gpd.GeoDataFrame:
    """Malha viária dirigível do município (Overpass via OSMnx)."""
    try:
        graph = ox.graph_from_polygon(polygon, network_type="drive",
                                      retain_all=True, truncate_by_edge=True)
        edges = ox.graph_to_gdfs(graph, nodes=False).reset_index(drop=True)
    except Exception as exc:
        raise ValueError(
            "Falha ao baixar a malha viária do município (Overpass). "
            "Tente novamente em alguns minutos.") from exc
    cols = ["geometry"] + [c for c in ("highway", "surface") if c in edges.columns]
    return gpd.GeoDataFrame(edges[cols], crs=geo.WGS84)


def _city_buildings(polygon, bbox, area_km2: float, source: str, progress) -> tuple[gpd.GeoDataFrame, str]:
    """Edificações para o município inteiro, com cadeia de fallback."""
    xmin, ymin, xmax, ymax = bbox
    if source in ("auto", "ms"):
        try:
            from . import msbuildings
            gdf = msbuildings.fetch_buildings_bbox(
                xmin, ymin, xmax, ymax,
                progress=lambda m: progress("Edificações (Microsoft)", 30, m))
            if not gdf.empty:
                return gdf, "ms"
        except Exception:
            if source == "ms":
                raise ValueError(
                    "Falha ao baixar os footprints Microsoft. Verifique a conexão.")
    if source == "overture":
        from . import overture
        return overture.fetch_buildings_bbox(xmin, ymin, xmax, ymax), "overture"
    if source == "google":
        from . import gob
        aoi = gpd.GeoDataFrame(geometry=[polygon], crs=geo.WGS84)
        return gob.fetch_buildings_gee(aoi), "google"

    # OSM puro: só viável para municípios pequenos.
    if area_km2 > OSM_FALLBACK_MAX_KM2:
        raise ValueError(
            "Footprints Microsoft indisponíveis e o município é grande demais "
            f"para baixar edificações do OSM ({area_km2:,.0f} km²). Tente de novo.")
    try:
        gdf = ox.features_from_polygon(polygon, tags={"building": True})
        polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
        return gpd.GeoDataFrame(geometry=polys.geometry.values, crs=geo.WGS84), "osm"
    except Exception as exc:
        raise ValueError("Falha ao baixar edificações (OSM/Overpass).") from exc


def _ctx_for_city(roads: gpd.GeoDataFrame, polygon, infra_mode: str, progress) -> dict:
    """Contexto de enriquecimento pré-buscado (uma chamada por município)."""
    ctx: dict = {"roads": roads, "amenities": None, "big_roads": None}
    if infra_mode == "logistics":
        try:
            if "highway" in roads.columns:
                hw = roads["highway"].map(
                    lambda v: v[0] if isinstance(v, list) and v else v).astype(str)
                big = roads[hw.isin(enrich._BIG_ROADS)]
                if not big.empty:
                    ctx["big_roads"] = gpd.GeoDataFrame(big[["geometry"]], crs=geo.WGS84)
        except Exception:
            pass
        return ctx
    try:
        progress("Serviços do entorno (escolas, mercados…)", 78)
        am = ox.features_from_polygon(polygon, tags={
            "amenity": ["school", "kindergarten", "hospital", "clinic", "pharmacy"],
            "shop": ["supermarket", "convenience"],
            "highway": ["bus_stop"],
        })
        if not am.empty:
            am = am.copy()
            am["geometry"] = am.geometry.centroid
            keep = [c for c in ("amenity", "shop", "highway") if c in am.columns]
            ctx["amenities"] = gpd.GeoDataFrame(
                am[["geometry"] + keep], crs=geo.WGS84).reset_index(drop=True)
    except Exception:
        pass
    return ctx


def analyze_city(
    progress,
    *,
    city_query: str,
    osm_type: str | None = None,
    osm_id=None,
    buildings_source: str = "auto",
    profile: str = "condominio_casas",
    target_min_m2: float | None = None,
    target_max_m2: float | None = None,
    weights: dict | None = None,
    min_area_m2: float = report.PERMISSIVE["min_area_m2"],
    max_occupation_ratio: float = report.PERMISSIVE["max_occupation_ratio"],
    min_width_m: float = 6.0,
    building_buffer_m: float = 1.5,
    max_area_m2: float = 2_000_000.0,
    project_id: str | None = None,
) -> dict:
    progress("Limite municipal", 2)
    boundary = _boundary_gdf(city_query, osm_type, osm_id)
    polygon = boundary.geometry.iloc[0]
    mcrs = boundary.estimate_utm_crs()
    boundary_m = boundary.to_crs(mcrs)
    area_km2 = float(boundary_m.geometry.iloc[0].area) / 1e6
    if area_km2 > MAX_CITY_KM2:
        raise ValueError(
            f"O município tem {area_km2:,.0f} km² (limite: {MAX_CITY_KM2:,.0f} km²). "
            "Municípios muito extensos são majoritariamente rurais — analise a "
            "área urbana por endereço + raio.")

    pid = project_id or store.create_project(city_query)["id"]
    store.get_meta(pid)

    progress("Malha viária do município", 8, "Overpass — pode levar 1–3 min")
    roads = _city_roads(polygon)

    progress("Áreas de exclusão (praças, escolas, água…)", 20)
    exclusions = osm.fetch_exclusions_polygon(polygon)

    progress("Edificações (alta cobertura)", 28)
    bbox = tuple(float(v) for v in boundary.total_bounds)
    buildings, source_used = _city_buildings(
        polygon, bbox, area_km2, buildings_source, progress)

    progress("Montando as quadras do município", 45,
             f"{len(roads):,} vias · {len(buildings):,} edificações")
    roads_m = osm.roads_polygon_m(roads, mcrs)
    city_m = boundary_m.geometry.iloc[0]
    if roads_m is not None and not roads_m.is_empty:
        city_m = city_m.difference(roads_m)
    if not exclusions.empty:
        city_m = city_m.difference(union_all(exclusions.to_crs(mcrs).geometry.values))

    block_cap = max_area_m2 * BLOCK_MAX_FACTOR
    blocks = [b for b in detect.explode_polygons(city_m)
              if min_area_m2 <= b.area <= block_cap]
    if not blocks:
        raise ValueError("Nenhuma quadra urbana encontrada no município.")

    aoi = gpd.GeoDataFrame(geometry=blocks, crs=mcrs).to_crs(geo.WGS84)
    store.save_layer(pid, "aoi", aoi)
    if not exclusions.empty:
        store.save_layer(pid, "exclusions", exclusions)

    params = DetectionParams(
        provider="footprint", mode="gaps",
        min_area_m2=min_area_m2, max_occupation_ratio=max_occupation_ratio,
        min_width_m=min_width_m, building_buffer_m=building_buffer_m,
        max_area_m2=max_area_m2)

    progress("Detectando vazios urbanos", 52, f"{len(blocks):,} quadras")
    buildings_m = buildings.to_crs(mcrs).geometry if not buildings.empty else None
    gaps = detect.find_gaps(
        blocks, buildings_m, params,
        progress=lambda d, t: progress("Detectando vazios urbanos",
                                       52 + 18.0 * d / max(t, 1), f"{d:,}/{t:,} quadras"))
    candidates = gpd.GeoDataFrame(geometry=gaps, crs=mcrs).to_crs(geo.WGS84)

    progress("Qualificando candidatos", 72, f"{len(candidates):,} vazios")
    zoning = store.load_layer(pid, "zoning")
    results = qualify(candidates, buildings, zoning, params)

    prof = score.get_profile(profile)
    if not results.empty:
        ctx = _ctx_for_city(roads, polygon, prof["infra_mode"], progress)
        progress("Score de viabilidade", 82,
                 f"relevo nos {min(DEM_TOP_LOTS, len(results))} maiores lotes")
        centroid = polygon.centroid
        try:
            results = enrich.enrich_and_score(
                results, profile, target_min_m2, target_max_m2,
                float(centroid.y), float(centroid.x), 0.0, weights,
                ctx=ctx, dem_limit=DEM_TOP_LOTS)
        except Exception:
            pass

    progress("Salvando camadas do projeto", 93)
    store.save_layer(pid, "buildings", buildings[["geometry"]])
    store.save_layer(pid, "results", results)
    store.update_meta(pid, name=city_query, last_detect={
        "count": len(results), "source": source_used,
        "profile": profile, "mode": "city"})

    # Payload com geometrias simplificadas (transporte) — camadas mantêm precisão.
    results_payload = results.copy()
    if not results_payload.empty:
        results_payload["geometry"] = results_payload.geometry.simplify(
            0.00001, preserve_topology=True)
    boundary_payload = boundary.copy()
    boundary_payload["geometry"] = boundary_payload.geometry.simplify(
        0.0001, preserve_topology=True)
    centroid = polygon.centroid

    return {
        "mode": "city",
        "project_id": pid,
        "query": city_query,
        "center": {"lat": float(centroid.y), "lon": float(centroid.x)},
        "area_km2": round(area_km2, 1),
        "boundary": io.to_geojson_dict(boundary_payload[["geometry"]]),
        "buildings_source": source_used,
        "provider": "footprint",
        "profile": profile,
        "profile_label": prof["label"],
        "target_min_m2": target_min_m2 or prof["target_area_m2"][0],
        "target_max_m2": target_max_m2 or prof["target_area_m2"][1],
        "buildings": len(buildings),
        "blocks": len(blocks),
        "count": len(results),
        "results": io.to_geojson_dict(results_payload),
        "report": report.build_report(results),
        "lots_info": store.get_lots_info(pid),
    }
