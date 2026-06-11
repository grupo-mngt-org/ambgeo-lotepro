"""Enriquecimento de lotes: declividade, acesso, testada, formato e entorno.

Transforma os candidatos detectados em leads QUALIFICADOS para decisão de
compra, calculando os critérios que alimentam o score de viabilidade
(score.py). Todas as fontes são gratuitas e sem chave:

  - Relevo: OpenTopoData / SRTM 30 m (dem.py)
  - Vias, pavimentação e serviços do entorno: OpenStreetMap via OSMnx

Cada componente falha de forma independente (try/except) — uma queda do
serviço de elevação, por exemplo, não derruba a análise: o critério fica
"sem dado" e os pesos do score são renormalizados.
"""
from __future__ import annotations

import json
import math

import geopandas as gpd
import osmnx as ox
from shapely import union_all

from . import dem, geo, score

_AMENITY_RADIUS_M = 800.0     # raio de busca de serviços em torno do lote
_FRONTAGE_BUFFER_M = 12.0     # via buffer p/ detectar testada (meia pista + recuo)
_BIG_ROADS = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}


# ----------------------------------------------------------------------------
# Contexto (1 chamada de cada por análise, não por lote)
# ----------------------------------------------------------------------------
def fetch_context(lat: float, lon: float, radius_m: float, infra_mode: str) -> dict:
    """Baixa o contexto do entorno: vias com tags e serviços (OSM)."""
    ctx: dict = {"roads": None, "amenities": None, "big_roads": None}

    try:
        roads = ox.features_from_point((lat, lon), tags={"highway": True},
                                       dist=radius_m + 900)
        lines = roads[roads.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        if not lines.empty:
            cols = ["geometry", "highway"] + (["surface"] if "surface" in lines.columns else [])
            ctx["roads"] = gpd.GeoDataFrame(lines[cols], crs=geo.WGS84).reset_index(drop=True)
    except Exception:
        pass

    if infra_mode == "logistics":
        try:
            big = ox.features_from_point(
                (lat, lon), tags={"highway": list(_BIG_ROADS)}, dist=radius_m + 4_000)
            big = big[big.geometry.type.isin(["LineString", "MultiLineString"])]
            if not big.empty:
                ctx["big_roads"] = gpd.GeoDataFrame(
                    big[["geometry"]], crs=geo.WGS84).reset_index(drop=True)
        except Exception:
            pass
    else:
        try:
            am = ox.features_from_point(
                (lat, lon),
                tags={
                    "amenity": ["school", "kindergarten", "hospital", "clinic", "pharmacy"],
                    "shop": ["supermarket", "convenience"],
                    "highway": ["bus_stop"],
                },
                dist=radius_m + _AMENITY_RADIUS_M + 100,
            )
            if not am.empty:
                am = am.copy()
                am["geometry"] = am.geometry.centroid  # polígonos → ponto
                keep = [c for c in ("amenity", "shop", "highway") if c in am.columns]
                ctx["amenities"] = gpd.GeoDataFrame(
                    am[["geometry"] + keep], crs=geo.WGS84).reset_index(drop=True)
        except Exception:
            pass

    return ctx


def _amenity_category(row) -> str | None:
    a = row.get("amenity")
    if a in ("school", "kindergarten"):
        return "school"
    if a in ("hospital", "clinic"):
        return "health"
    if a == "pharmacy":
        return "pharmacy"
    if row.get("shop") in ("supermarket", "convenience"):
        return "market"
    if row.get("highway") == "bus_stop":
        return "bus"
    return None


# ----------------------------------------------------------------------------
# Métricas por lote
# ----------------------------------------------------------------------------
def _nearest_road(lot_geom_m, roads_m: gpd.GeoDataFrame | None) -> tuple[str | None, str | None]:
    """(classe, pavimentação) da via mais próxima do lote (≤ 150 m)."""
    if roads_m is None or roads_m.empty:
        return None, None
    try:
        idx, dist = roads_m.sindex.nearest(
            lot_geom_m, return_all=False, return_distance=True)
        i = int(idx[1][0])
        if float(dist[0]) > 150.0:
            return None, None
        row = roads_m.iloc[i]
        hw = row.get("highway")
        if isinstance(hw, list):
            hw = hw[0] if hw else None
        surface = row.get("surface") if "surface" in roads_m.columns else None
        if isinstance(surface, list):
            surface = surface[0] if surface else None
        return (str(hw) if hw else None,
                str(surface) if surface and str(surface) != "nan" else None)
    except Exception:
        return None, None


def _compactness(geom_m) -> float | None:
    """Polsby-Popper: 4πA / P² (1.0 = círculo perfeito)."""
    try:
        p = geom_m.length
        if p <= 0:
            return None
        return round(4.0 * math.pi * geom_m.area / (p * p), 3)
    except Exception:
        return None


def enrich_and_score(
    results: gpd.GeoDataFrame,
    profile_key: str,
    target_min: float | None,
    target_max: float | None,
    center_lat: float,
    center_lon: float,
    radius_m: float,
    weights_override: dict | None = None,
    ctx: dict | None = None,
    dem_limit: int | None = None,
) -> gpd.GeoDataFrame:
    """Adiciona métricas de viabilidade + score a cada lote detectado.

    Novas colunas: score, grade, slope_pct, elev_range_m, frontage_m,
    compactness, flags, score_breakdown (JSON). Resultado ordenado por score.

    `ctx`: contexto pré-buscado (modo cidade inteira) — evita novo download.
    `dem_limit`: consulta relevo só dos N primeiros lotes da ordem de entrada
    (modo cidade: limita chamadas à API pública de elevação).
    """
    if results.empty:
        return results

    profile = score.get_profile(profile_key)
    tmin = float(target_min) if target_min else profile["target_area_m2"][0]
    tmax = float(target_max) if target_max else profile["target_area_m2"][1]
    if tmin > tmax:
        tmin, tmax = tmax, tmin

    if ctx is None:
        ctx = fetch_context(center_lat, center_lon, radius_m, profile["infra_mode"])

    mcrs = geo.metric_crs(results)
    lots_m = results.to_crs(mcrs)

    roads_m = ctx["roads"].to_crs(mcrs) if ctx["roads"] is not None else None

    amenities_m = ctx["amenities"].to_crs(mcrs) if ctx["amenities"] is not None else None
    big_roads_m = ctx["big_roads"].to_crs(mcrs) if ctx["big_roads"] is not None else None
    big_union = None
    if big_roads_m is not None and not big_roads_m.empty:
        try:
            big_union = union_all(big_roads_m.geometry.values)
        except Exception:
            big_union = None

    # Relevo em chamadas batched (cache + rate limit em dem.py). Com
    # dem_limit, só os N primeiros lotes (cidade inteira: os maiores).
    no_slope = {"slope_pct": None, "elev_range_m": None}
    try:
        if dem_limit is not None and len(results) > dem_limit:
            head = results.iloc[:dem_limit]
            slopes = dem.lots_slopes(head, mcrs) + [no_slope] * (len(results) - dem_limit)
        else:
            slopes = dem.lots_slopes(results, mcrs)
    except Exception:
        slopes = [no_slope] * len(results)

    out = results.copy()
    scores, grades, slope_col, elev_col = [], [], [], []
    frontage_col, compact_col, flags_col, breakdown_col = [], [], [], []

    for i, (idx, row) in enumerate(out.iterrows()):
        geom_m = lots_m.geometry.iloc[i]
        area_m2 = float(row["area_m2"])

        # Testada: divisa do lote dentro do buffer das vias PRÓXIMAS
        # (consulta local via índice espacial — escala para cidade inteira).
        frontage = None
        if roads_m is not None and not roads_m.empty:
            try:
                near_idx = roads_m.sindex.query(
                    geom_m, predicate="dwithin", distance=_FRONTAGE_BUFFER_M)
                if len(near_idx):
                    local_buf = union_all(
                        roads_m.geometry.iloc[near_idx].buffer(_FRONTAGE_BUFFER_M).values)
                    frontage = round(float(geom_m.boundary.intersection(local_buf).length), 1)
                else:
                    frontage = 0.0
            except Exception:
                frontage = None

        road_class, surface = _nearest_road(geom_m, roads_m)

        amenity_counts = None
        if amenities_m is not None and not amenities_m.empty:
            try:
                centroid_m = geom_m.centroid
                near = amenities_m[amenities_m.distance(centroid_m) <= _AMENITY_RADIUS_M]
                counts: dict[str, int] = {}
                for _, a in near.iterrows():
                    cat = _amenity_category(a)
                    if cat:
                        counts[cat] = counts.get(cat, 0) + 1
                amenity_counts = counts
            except Exception:
                amenity_counts = None
        elif profile["infra_mode"] == "amenities" and ctx["amenities"] is not None:
            amenity_counts = {}

        highway_dist = None
        if big_union is not None:
            try:
                highway_dist = round(float(geom_m.centroid.distance(big_union)), 0)
            except Exception:
                highway_dist = None

        metrics = {
            "area_m2": area_m2,
            "slope_pct": slopes[i]["slope_pct"],
            "elev_range_m": slopes[i]["elev_range_m"],
            "road_class": road_class,
            "surface": surface,
            "frontage_m": frontage,
            "compactness": _compactness(geom_m),
            "amenity_counts": amenity_counts,
            "highway_dist_m": highway_dist,
        }
        res = score.compute(metrics, profile, tmin, tmax, weights_override)

        scores.append(res["score"])
        grades.append(res["grade"])
        slope_col.append(metrics["slope_pct"])
        elev_col.append(metrics["elev_range_m"])
        frontage_col.append(frontage)
        compact_col.append(metrics["compactness"])
        flags_col.append(";".join(res["flags"]))
        breakdown_col.append(json.dumps(res["breakdown"], ensure_ascii=False))

    out["score"] = scores
    out["grade"] = grades
    out["slope_pct"] = slope_col
    out["elev_range_m"] = elev_col
    out["frontage_m"] = frontage_col
    out["compactness"] = compact_col
    out["flags"] = flags_col
    out["score_breakdown"] = breakdown_col

    return out.sort_values("score", ascending=False).reset_index(drop=True)
