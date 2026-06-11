"""Núcleo geoespacial: CRS métrico, área, taxa de ocupação e classificação.

Convenção: GeoDataFrames trafegam em EPSG:4326 (graus). Toda medição de área é
feita após reprojeção para o UTM local (metros), evitando o erro clássico de
calcular área em graus.
"""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

WGS84 = "EPSG:4326"

# Faixas de potencial de aproveitamento por taxa de ocupação (área construída / área total).
# Quanto menos construído, maior o potencial de prospecção.
POTENTIAL_COLORS = {
    "alto": "#2ecc71",    # praticamente vazio
    "medio": "#f1c40f",   # subutilizado
    "baixo": "#e67e22",   # ocupação relevante
}


def metric_crs(gdf: gpd.GeoDataFrame) -> str:
    """Estima o CRS UTM apropriado para a extensão dos dados (medições em metros)."""
    g = gdf if gdf.crs else gdf.set_crs(WGS84)
    if (g.crs or "").to_string() != WGS84 and g.crs is not None:
        g = g.to_crs(WGS84)
    return g.estimate_utm_crs().to_string()


def to_metric(gdf: gpd.GeoDataFrame, crs: str | None = None) -> gpd.GeoDataFrame:
    """Reprojeta para um CRS métrico (UTM local por padrão)."""
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    crs = crs or metric_crs(gdf)
    return gdf.to_crs(crs)


def area_m2(geom_metric: BaseGeometry) -> float:
    """Área em m² de uma geometria já em CRS métrico."""
    return float(geom_metric.area)


def occupation_ratio(lot_metric: BaseGeometry, buildings_union_metric: BaseGeometry | None) -> float:
    """Razão área construída / área do lote (0..1), ambos em CRS métrico."""
    total = lot_metric.area
    if total <= 0:
        return 0.0
    if buildings_union_metric is None or buildings_union_metric.is_empty:
        return 0.0
    built = lot_metric.intersection(buildings_union_metric).area
    return max(0.0, min(1.0, built / total))


def classify_potential(occupation: float, max_occupation_ratio: float) -> str:
    """Classifica potencial em alto/medio/baixo a partir da ocupação."""
    if occupation <= max_occupation_ratio * 0.34:
        return "alto"
    if occupation <= max_occupation_ratio:
        return "medio"
    return "baixo"


def street_view_url(lat: float, lon: float) -> str:
    """Link gratuito de navegação para o Google Street View (sem custo de tile/API)."""
    return f"https://www.google.com/maps?q=&layer=c&cbll={lat:.6f},{lon:.6f}"
