"""Provider default: detecção de vazios por subtração de footprints.

Roda 100% local (GeoPandas/Shapely), sem credenciais nem API key.

Modos:
  - "gaps":    vazio = quadra − footprints dilatados (núcleo em core/detect.py,
               com filtros de largura mínima e frente para via).
  - "parcels": cada feição da AOI é um lote; pontua pela taxa de ocupação.
"""
from __future__ import annotations

import geopandas as gpd

from ..core import detect, geo
from ..core.pipeline import qualify
from .base import DetectionParams, DetectionProvider


class FootprintProvider(DetectionProvider):
    name = "footprint"

    def detect(self, aoi, buildings, zoning, params: DetectionParams) -> gpd.GeoDataFrame:
        if aoi is None or aoi.empty:
            raise ValueError("AOI vazia: envie a área de interesse antes de detectar.")

        if params.mode == "parcels":
            candidates = aoi.to_crs(geo.WGS84) if aoi.crs else aoi.set_crs(geo.WGS84)
            return qualify(candidates, buildings, zoning, params)

        # modo "gaps": trabalha em CRS métrico (buffers/larguras em metros).
        aoi_4326 = aoi.to_crs(geo.WGS84) if aoi.crs else aoi.set_crs(geo.WGS84)
        mcrs = geo.metric_crs(aoi_4326)
        aoi_m = aoi_4326.to_crs(mcrs)

        blocks = []
        for geom in aoi_m.geometry.values:
            blocks.extend(detect.explode_polygons(geom))

        buildings_m = None
        if buildings is not None and not buildings.empty:
            b = buildings if buildings.crs else buildings.set_crs(geo.WGS84)
            buildings_m = b.to_crs(mcrs).geometry

        gaps = detect.find_gaps(blocks, buildings_m, params)
        candidates = gpd.GeoDataFrame(geometry=gaps, crs=mcrs).to_crs(geo.WGS84)
        # No modo gaps as edificações já foram removidas: ocupação medida ~0.
        return qualify(candidates, buildings, zoning, params)
