"""Fonte de dados REAL via OpenStreetMap (sem chave, sem mock).

Usa OSMnx (Nominatim para geocodificação + Overpass para footprints reais de
edificações). A partir de uma cidade e um endereço inicial, define a AOI (círculo
de raio configurável em torno do ponto) e baixa as edificações reais da área.
"""
from __future__ import annotations

import geopandas as gpd
import osmnx as ox
import requests
from shapely import union_all
from shapely.geometry import Point

PHOTON_URL = "https://photon.komoot.io/api/"
# Photon/Nominatim exigem User-Agent identificável (sem ele, retornam 403).
HTTP_HEADERS = {"User-Agent": "LotePro/0.1 (+devs@grupomngt.com.br)"}


def suggest(query: str, limit: int = 6, cities_only: bool = False) -> list[dict]:
    """Autocomplete via Photon (Komoot) — gratuito, sem chave.
    Retorna [{label, lat, lon, osm_type, osm_id}]; com `cities_only`, filtra
    municípios (place=city/town/village) e o osm_id permite buscar o limite
    municipal exato no Nominatim."""
    query = (query or "").strip()
    if len(query) < 3:
        return []
    params: list[tuple[str, str]] = [("q", query), ("limit", str(limit * 2))]
    if cities_only:
        for tag in ("place:city", "place:town", "place:village", "place:municipality"):
            params.append(("osm_tag", tag))
    try:
        resp = requests.get(PHOTON_URL, params=params, headers=HTTP_HEADERS, timeout=8)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
    except Exception:
        return []

    out = []
    for f in feats:
        p = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates")
        if not coords:
            continue
        parts = [p.get("name"), p.get("street"), p.get("district"),
                 p.get("city") or p.get("county"), p.get("state"), p.get("country")]
        # remove duplicatas mantendo a ordem
        seen, clean = set(), []
        for x in parts:
            if x and x not in seen:
                seen.add(x); clean.append(str(x))
        out.append({
            "label": ", ".join(clean) or query,
            "lat": float(coords[1]), "lon": float(coords[0]),
            "osm_type": p.get("osm_type"), "osm_id": p.get("osm_id"),
        })
        if len(out) >= limit:
            break
    return out

from . import geo

# Configuração do cliente OSMnx (rede real).
ox.settings.requests_timeout = 90
ox.settings.overpass_rate_limit = True
ox.settings.use_cache = True


def geocode(query: str) -> tuple[float, float]:
    """Geocodifica um endereço/cidade para (lat, lon) via Nominatim."""
    if not query or not query.strip():
        raise ValueError("Informe a cidade e/ou o endereço para a busca.")
    try:
        lat, lon = ox.geocode(query)
    except Exception as exc:
        raise ValueError(f"Endereço não encontrado: {query!r}.") from exc
    return float(lat), float(lon)


def build_aoi(lat: float, lon: float, radius_m: float, label: str) -> gpd.GeoDataFrame:
    """AOI = círculo de raio `radius_m` em torno do ponto (buffer em CRS métrico)."""
    pt = gpd.GeoDataFrame({"name": [label]}, geometry=[Point(lon, lat)], crs=geo.WGS84)
    mcrs = pt.estimate_utm_crs()
    pt_m = pt.to_crs(mcrs)
    pt_m["geometry"] = pt_m.buffer(radius_m)
    return pt_m.to_crs(geo.WGS84)


def fetch_buildings(lat: float, lon: float, radius_m: float) -> gpd.GeoDataFrame:
    """Baixa footprints REAIS de edificações (OSM/Overpass) no raio informado."""
    try:
        gdf = ox.features_from_point((lat, lon), tags={"building": True}, dist=radius_m)
    except Exception as exc:
        raise ValueError(
            "Falha ao consultar o Overpass (OSM). Tente novamente ou reduza o raio."
        ) from exc

    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)

    polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    # Mantém só a geometria (tags OSM têm tipos mistos e quebram o schema do GPKG).
    return gpd.GeoDataFrame(geometry=polys.geometry.values, crs=geo.WGS84)


# Largura (m) do leito carroçável por classe de via — usada para recortar
# as quadras da AOI e do modo cidade-inteira.
ROAD_WIDTHS_M = {
    "motorway": 22.0, "trunk": 18.0, "primary": 14.0, "secondary": 12.0,
    "tertiary": 10.0, "residential": 8.0, "unclassified": 8.0,
    "living_street": 7.0, "service": 5.0, "motorway_link": 12.0,
    "trunk_link": 10.0, "primary_link": 10.0, "secondary_link": 9.0,
    "tertiary_link": 8.0,
}
DEFAULT_ROAD_WIDTH_M = 7.0

# Áreas que NUNCA são lote comprável: praças, escolas, cemitérios, água…
# São subtraídas da AOI para não virarem falso-positivo de "terreno vazio".
EXCLUSION_TAGS = {
    "leisure": ["park", "playground", "pitch", "sports_centre", "stadium",
                "garden", "golf_course", "nature_reserve", "dog_park"],
    "landuse": ["cemetery", "military", "railway", "landfill", "quarry",
                "recreation_ground", "religious"],
    "amenity": ["school", "university", "college", "hospital", "prison",
                "place_of_worship", "grave_yard", "fuel"],
    "natural": ["water", "wetland"],
    "boundary": ["protected_area"],
    "aeroway": ["aerodrome"],
}


def _only_polygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    polys = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
    return gpd.GeoDataFrame(geometry=polys.geometry.values, crs=geo.WGS84)


def roads_polygon_m(roads: gpd.GeoDataFrame | None, mcrs):
    """União das vias (linhas OSM) bufferizadas pela meia-largura da classe,
    em CRS métrico. Subtrair isso da AOI particiona o vazio em quadras."""
    if roads is None or roads.empty:
        return None
    lines = roads[roads.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if lines.empty:
        return None

    def half_width(hw) -> float:
        if isinstance(hw, list):
            hw = hw[0] if hw else None
        return ROAD_WIDTHS_M.get(str(hw), DEFAULT_ROAD_WIDTH_M) / 2.0

    widths = (lines["highway"].map(half_width) if "highway" in lines.columns
              else DEFAULT_ROAD_WIDTH_M / 2.0)
    buffered = lines.to_crs(mcrs).buffer(widths)
    return union_all(buffered.values)


def fetch_roads_point(lat: float, lon: float, radius_m: float) -> gpd.GeoDataFrame | None:
    try:
        roads = ox.features_from_point((lat, lon), tags={"highway": True}, dist=radius_m)
    except Exception:
        return None
    lines = roads[roads.geometry.type.isin(["LineString", "MultiLineString"])]
    if lines.empty:
        return None
    cols = ["geometry"] + [c for c in ("highway",) if c in lines.columns]
    return gpd.GeoDataFrame(lines[cols], crs=geo.WGS84).reset_index(drop=True)


def fetch_exclusions_point(lat: float, lon: float, radius_m: float) -> gpd.GeoDataFrame:
    """Polígonos de áreas não-prospectáveis (praças, escolas, água…)."""
    try:
        gdf = ox.features_from_point((lat, lon), tags=EXCLUSION_TAGS, dist=radius_m)
        return _only_polygons(gdf)
    except Exception:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)


def fetch_exclusions_polygon(polygon) -> gpd.GeoDataFrame:
    try:
        gdf = ox.features_from_polygon(polygon, tags=EXCLUSION_TAGS)
        return _only_polygons(gdf)
    except Exception:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)


def fetch_buildings_for_bbox(xmin: float, ymin: float, xmax: float, ymax: float,
                             source: str, lat: float, lon: float, radius_m: float,
                             progress=None) -> tuple[gpd.GeoDataFrame, str]:
    """Edificações pela fonte pedida. Retorna (gdf, rótulo da fonte usada).

    "auto" = Microsoft Building Footprints (alta cobertura, cache local)
    mesclado com OSM; cai para OSM puro se a Microsoft estiver indisponível.
    """
    import pandas as pd

    if source == "overture":
        from . import overture
        return overture.fetch_buildings_bbox(xmin, ymin, xmax, ymax), "overture"
    if source == "google":
        from . import gob
        aoi = build_aoi(lat, lon, radius_m, "aoi")
        return gob.fetch_buildings_gee(aoi), "google"
    if source == "osm":
        return fetch_buildings(lat, lon, radius_m), "osm"
    if source == "ms":
        from . import msbuildings
        return msbuildings.fetch_buildings_bbox(xmin, ymin, xmax, ymax, progress), "ms"

    # auto: MS + OSM (cada um pode falhar de forma independente)
    frames, labels = [], []
    try:
        from . import msbuildings
        ms = msbuildings.fetch_buildings_bbox(xmin, ymin, xmax, ymax, progress)
        if not ms.empty:
            frames.append(ms)
            labels.append("ms")
    except Exception:
        pass
    try:
        osm_b = fetch_buildings(lat, lon, radius_m)
        if not osm_b.empty:
            frames.append(osm_b)
            labels.append("osm")
    except Exception:
        pass
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84), "nenhuma"
    merged = gpd.GeoDataFrame(
        pd.concat([f[["geometry"]] for f in frames], ignore_index=True),
        geometry="geometry", crs=geo.WGS84)
    return merged, "+".join(labels)


def fetch_area(city: str, address: str, radius_m: float, buildings_source: str = "auto",
               lat: float | None = None, lon: float | None = None,
               progress=None) -> dict:
    """Pipeline completo: geocodifica, monta a AOI recortada por vias e áreas
    de exclusão, e baixa edificações reais. A AOI vira um conjunto de quadras.

    Se `lat`/`lon` forem informados (ex.: vindos do autocomplete), pula a
    geocodificação. `progress(msg)` é opcional (modo job)."""
    radius_m = max(50.0, min(float(radius_m), 5000.0))
    query = ", ".join(p for p in (address.strip(), city.strip()) if p) or "Área selecionada"
    if lat is None or lon is None:
        if progress:
            progress("Geocodificando endereço…")
        lat, lon = geocode(query)
    lat, lon = float(lat), float(lon)

    aoi = build_aoi(lat, lon, radius_m, query)
    xmin, ymin, xmax, ymax = (float(v) for v in aoi.total_bounds)  # bbox do círculo
    mcrs = aoi.estimate_utm_crs()

    if progress:
        progress("Baixando malha viária (OSM)…")
    roads = fetch_roads_point(lat, lon, radius_m)
    roads_m = roads_polygon_m(roads, mcrs)

    if progress:
        progress("Baixando áreas de exclusão (praças, escolas, água…)…")
    exclusions = fetch_exclusions_point(lat, lon, radius_m)

    aoi_m = aoi.to_crs(mcrs)
    if roads_m is not None and not roads_m.is_empty:
        aoi_m["geometry"] = aoi_m.geometry.difference(roads_m)  # remove leito das vias
    if not exclusions.empty:
        excl_m = union_all(exclusions.to_crs(mcrs).geometry.values)
        aoi_m["geometry"] = aoi_m.geometry.difference(excl_m)
    aoi = aoi_m.to_crs(geo.WGS84)

    if progress:
        progress("Baixando edificações…")
    buildings, source_used = fetch_buildings_for_bbox(
        xmin, ymin, xmax, ymax, buildings_source, lat, lon, radius_m, progress)

    return {
        "center": {"lat": lat, "lon": lon},
        "query": query,
        "radius_m": radius_m,
        "buildings_source": source_used,
        "aoi": aoi,
        "buildings": buildings,
        "buildings_count": len(buildings),
        "exclusions": exclusions,
        "roads": roads,
    }
