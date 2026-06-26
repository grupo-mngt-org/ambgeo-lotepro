"""Pipeline de qualificação compartilhado por todos os providers.

Recebe polígonos candidatos (EPSG:4326) e devolve o GeoDataFrame final
padronizado, aplicando: medição de área (CRS métrico), taxa de ocupação,
filtros de negócio (RF03), cruzamento de zoneamento e classificação de
potencial.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely import STRtree, union_all

from . import geo
from ..providers.base import DetectionParams

OUTPUT_COLUMNS = [
    "id", "area_m2", "occupation", "potential", "color",
    "zoning", "lat", "lon", "street_view", "geometry",
]


def _zoning_label(candidates_4326: gpd.GeoDataFrame, zoning: gpd.GeoDataFrame | None) -> pd.Series:
    """Rotula cada candidato com a zona predominante (spatial join por interseção)."""
    if zoning is None or zoning.empty:
        return pd.Series(["N/D"] * len(candidates_4326), index=candidates_4326.index)

    label_col = next(
        (c for c in ("zoning", "zona", "zone", "nome", "name", "label", "sigla")
         if c in zoning.columns),
        None,
    )
    z = zoning[[label_col, "geometry"]].rename(columns={label_col: "zoning"}) if label_col \
        else zoning[["geometry"]].assign(zoning="N/D")

    joined = gpd.sjoin(
        candidates_4326[["geometry"]], z, how="left", predicate="intersects"
    )
    # Em sobreposição múltipla, mantém a primeira zona por candidato.
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined["zoning"].reindex(candidates_4326.index).fillna("N/D")


def qualify(
    candidates: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame | None,
    zoning: gpd.GeoDataFrame | None,
    params: DetectionParams,
) -> gpd.GeoDataFrame:
    """Mede, filtra e classifica os candidatos. Entrada e saída em EPSG:4326."""
    if candidates.crs is None:
        candidates = candidates.set_crs(geo.WGS84)
    candidates = candidates.to_crs(geo.WGS84).reset_index(drop=True)

    if candidates.empty:
        return gpd.GeoDataFrame(columns=OUTPUT_COLUMNS, geometry="geometry", crs=geo.WGS84)

    # Zoneamento (em 4326, antes de reprojetar).
    zoning_series = _zoning_label(candidates, zoning).reset_index(drop=True)

    # Reprojeta candidatos e edificações para o MESMO CRS métrico.
    mcrs = geo.metric_crs(candidates)
    cand_m = candidates.to_crs(mcrs)
    # STRtree em vez de união global: viabiliza cidades inteiras (300k+ footprints).
    btree, bgeoms = None, None
    if buildings is not None and not buildings.empty:
        b = buildings if buildings.crs else buildings.set_crs(geo.WGS84)
        bgeoms = b.to_crs(mcrs).geometry.values
        btree = STRtree(bgeoms)

    rows = []
    for i, geom_m in enumerate(cand_m.geometry.values):
        if geom_m is None or geom_m.is_empty:
            continue
        area = geo.area_m2(geom_m)
        if area < params.min_area_m2:               # RF03: área mínima
            continue
        if params.max_area_m2 and area > params.max_area_m2:  # teto (modo cidade)
            continue
        if btree is not None:
            idx = btree.query(geom_m, predicate="intersects")
            local_union = union_all(bgeoms[idx]) if len(idx) else None
        else:
            local_union = None
        occ = geo.occupation_ratio(geom_m, local_union)
        if occ > params.max_occupation_ratio:         # RF03: ocupação máxima
            continue
        potential = geo.classify_potential(occ, params.max_occupation_ratio)
        centroid = candidates.geometry.iloc[i].centroid  # centroide em 4326
        rows.append({
            "id": int(i),
            "area_m2": round(area, 1),
            "occupation": round(occ, 4),
            "potential": potential,
            "color": geo.POTENTIAL_COLORS[potential],
            "zoning": zoning_series.iloc[i],
            "lat": round(float(centroid.y), 6),
            "lon": round(float(centroid.x), 6),
            "street_view": geo.street_view_url(centroid.y, centroid.x),
            "geometry": candidates.geometry.iloc[i],
        })

    out = gpd.GeoDataFrame(rows, columns=OUTPUT_COLUMNS, geometry="geometry", crs=geo.WGS84)
    return out.sort_values("area_m2", ascending=False).reset_index(drop=True)
