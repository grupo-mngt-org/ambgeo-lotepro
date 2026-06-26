"""Google Open Buildings — footprints via GEE.

Dataset: GOOGLE/Research/open-buildings/v3/polygons
Ref: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons

Requer credenciais GEE (GEE_SERVICE_ACCOUNT + GEE_KEY_FILE, ou
`earthengine authenticate`). Cobertura global, gerada por modelos de
visão computacional do Google — cobertura muito maior que o OSM em
regiões menos mapeadas do Brasil.

Filtragem por confiança: apenas footprints com `confidence >= GOB_CONFIDENCE_MIN`
(padrão 0.65) são retornados, reduzindo falsos-positivos no cálculo de ocupação.
Combinação recomendada: buildings_source="google" + provider="dynamic_world".
"""
from __future__ import annotations

import json
import os

import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union

from . import geo

# Confiança mínima para incluir um footprint do Google Open Buildings.
# O dataset GOB v3 atribui confidence 0.5–1.0; abaixo de 0.65 o modelo
# tem alta taxa de falso-positivo em áreas menos mapeadas do Brasil.
GOB_CONFIDENCE_MIN = 0.65
GOB_MAX_FEATURES = 10_000


def _init_ee():
    try:
        import ee  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Google Open Buildings requer `pip install earthengine-api`."
        ) from exc
    sa = os.getenv("GEE_SERVICE_ACCOUNT")
    key = os.getenv("GEE_KEY_FILE")
    try:
        if sa and key:
            ee.Initialize(ee.ServiceAccountCredentials(sa, key))
        else:
            ee.Initialize()
    except Exception as exc:
        raise RuntimeError(
            "Falha ao autenticar no GEE para Google Open Buildings. "
            "Configure GEE_SERVICE_ACCOUNT + GEE_KEY_FILE ou rode "
            "`earthengine authenticate`."
        ) from exc
    return ee


def fetch_buildings_gee(aoi_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Baixa footprints do Google Open Buildings (v3) via GEE para a AOI.

    Filtra por confidence >= GOB_CONFIDENCE_MIN para reduzir falsos-positivos
    no cálculo de taxa de ocupação, especialmente em áreas menos mapeadas do Brasil.
    Limita a GOB_MAX_FEATURES features (getInfo). Para AOIs maiores que ~3 km de raio
    use Export.table no Code Editor do GEE e suba o resultado via upload de camada.
    """
    ee = _init_ee()

    aoi_4326 = aoi_gdf.to_crs(geo.WGS84) if aoi_gdf.crs else aoi_gdf.set_crs(geo.WGS84)
    geojson = json.loads(aoi_4326.to_json())
    features = geojson.get("features", [])
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)

    coords = [f["geometry"]["coordinates"] for f in features]
    region = ee.Geometry.MultiPolygon(coords)

    gob = (
        ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons")
        .filterBounds(region)
        .filter(ee.Filter.gte("confidence", GOB_CONFIDENCE_MIN))
        .limit(GOB_MAX_FEATURES)
    )

    try:
        info = gob.getInfo()
    except Exception as exc:
        raise ValueError(
            f"Falha ao consultar Google Open Buildings no GEE: {exc}. "
            "Verifique as credenciais GEE e o tamanho da AOI (máx. ~3 km de raio)."
        ) from exc

    raw_feats = info.get("features", [])
    geoms = []
    for feat in raw_feats:
        g = feat.get("geometry")
        if g:
            try:
                geoms.append(shape(g))
            except Exception:
                continue

    polys = [g for g in geoms if not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")]
    if not polys:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)

    result = gpd.GeoDataFrame(geometry=polys, crs=geo.WGS84)

    # Clip ao contorno exato da AOI (remove bordas que extrapolam o círculo de análise).
    try:
        aoi_union = unary_union(aoi_4326.geometry.values)
        result = result[result.geometry.intersects(aoi_union)].copy()
    except Exception:
        pass

    return result
