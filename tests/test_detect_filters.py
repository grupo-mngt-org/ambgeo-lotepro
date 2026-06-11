"""Testes dos filtros anti-falso-positivo do núcleo de detecção (CRS métrico)."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Polygon, box

from app.core import detect
from app.providers.base import DetectionParams

PARAMS = DetectionParams(min_area_m2=100.0, building_buffer_m=1.5, min_width_m=6.0)


def test_interior_courtyard_dropped_without_frontage():
    """Quadra com casas em todo o perímetro: o miolo (fundos de quintal)
    NÃO pode virar lote — não tem frente para via."""
    block = box(0, 0, 100, 100)
    ring_buildings = gpd.GeoSeries([
        box(0, 0, 100, 15), box(0, 85, 100, 100),     # faixas norte/sul
        box(0, 15, 15, 85), box(85, 15, 100, 85),     # faixas leste/oeste
    ])
    gaps = detect.find_gaps([block], ring_buildings, PARAMS)
    assert gaps == [], "miolo de quadra ocupada virou lote (falso-positivo)"

    open_params = DetectionParams(min_area_m2=100.0, building_buffer_m=1.5,
                                  min_width_m=6.0, require_frontage=False)
    gaps2 = detect.find_gaps([block], ring_buildings, open_params)
    assert len(gaps2) == 1, "sem o filtro, o miolo deveria aparecer"


def test_narrow_alley_dropped_by_opening():
    """Viela de 4 m entre duas casas não é lote."""
    block = box(0, 0, 50, 30)
    buildings = gpd.GeoSeries([box(0, 0, 23, 30), box(27, 0, 50, 30)])
    gaps = detect.find_gaps([block], buildings, PARAMS)
    assert gaps == [], "viela estreita virou lote"


def test_real_vacant_lot_survives():
    """Lote vazio de 20 m de testada entre casas continua detectado."""
    block = box(0, 0, 60, 30)
    buildings = gpd.GeoSeries([box(0, 0, 20, 30), box(40, 0, 60, 30)])
    gaps = detect.find_gaps([block], buildings, PARAMS)
    assert len(gaps) == 1
    assert gaps[0].area > 300


def test_empty_block_is_full_candidate():
    block = box(0, 0, 80, 60)
    gaps = detect.find_gaps([block], None, PARAMS)
    assert len(gaps) == 1
    assert abs(gaps[0].area - 80 * 60) < 80 * 60 * 0.05


def test_max_area_cap_applies_in_qualify():
    from app.core.pipeline import qualify
    huge = gpd.GeoDataFrame(
        geometry=[Polygon([(-49.30, -16.70), (-49.20, -16.70),
                           (-49.20, -16.60), (-49.30, -16.60)])], crs="EPSG:4326")
    params = DetectionParams(min_area_m2=100.0, max_area_m2=2_000_000.0)
    out = qualify(huge, None, None, params)
    assert out.empty, "gleba acima do teto de área deveria ser cortada"
