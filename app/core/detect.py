"""Núcleo da detecção de vazios por subtração de footprints (CRS métrico).

Compartilhado pelo provider `footprint` (modo raio) e pelo pipeline de cidade
inteira (citywide.py). Os filtros anti-falso-positivo vivem aqui:

  1. Dilatação dos footprints (building_buffer_m): frestas entre casas
     vizinhas (recuos laterais, beirais) deixam de virar "vazios".
  2. Abertura morfológica (min_width_m): vielas, corredores e sobras
     estreitas de fundo de lote são descartadas.
  3. Frente para via (require_frontage): em quadra ocupada, vazio interno
     que não encosta na divisa da quadra é fundo de quintal — não é lote
     comprável e era a principal fonte de falso-positivo.
"""
from __future__ import annotations

import geopandas as gpd
from shapely import STRtree, union_all
from shapely.geometry import MultiPolygon, Polygon

from ..providers.base import DetectionParams

# Distância máxima (m) entre o vazio e a divisa da quadra para considerar
# que ele tem frente para via.
FRONTAGE_TOL_M = 3.0


def explode_polygons(geom) -> list[Polygon]:
    """Lista de Polygons a partir de Polygon/MultiPolygon (ignora o resto)."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    return []


def _opening(geom, min_width_m: float):
    """Abertura morfológica: erode meia-largura e re-expande, removendo
    partes mais estreitas que `min_width_m` (mantido dentro do original)."""
    if min_width_m <= 0:
        return geom
    half = min_width_m / 2.0
    eroded = geom.buffer(-half)
    if eroded.is_empty:
        return eroded
    return eroded.buffer(half * 1.02).intersection(geom)


def find_gaps(
    blocks_m: list[Polygon],
    buildings_m: gpd.GeoSeries | None,
    params: DetectionParams,
    progress=None,
) -> list[Polygon]:
    """Vazios urbanos: quadra − footprints dilatados, com filtros de largura
    mínima e frente para via. Entrada/saída em CRS métrico (metros).

    `progress(done, total)` é chamado periodicamente quando fornecido.
    """
    buffered = None
    tree = None
    if buildings_m is not None and len(buildings_m) > 0:
        buffered = buildings_m.buffer(max(0.0, params.building_buffer_m))
        tree = STRtree(buffered.values)

    out: list[Polygon] = []
    total = len(blocks_m)
    for i, block in enumerate(blocks_m):
        if block is None or block.is_empty or block.area < params.min_area_m2:
            continue

        if tree is not None:
            idx = tree.query(block, predicate="intersects")
            gap = block.difference(union_all(buffered.values[idx])) if len(idx) else block
        else:
            gap = block

        if gap.is_empty:
            continue
        gap = _opening(gap, params.min_width_m)
        if gap.is_empty:
            continue

        boundary = block.exterior
        for poly in explode_polygons(gap):
            if poly.area < params.min_area_m2:
                continue
            if params.require_frontage and poly.distance(boundary) > FRONTAGE_TOL_M:
                continue  # vazio interno: fundo de quintal, não lote
            out.append(poly)

        if progress and total and (i % 200 == 0 or i == total - 1):
            progress(i + 1, total)
    return out
