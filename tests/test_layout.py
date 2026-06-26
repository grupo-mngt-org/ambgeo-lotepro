"""Testes do estudo de implantação paramétrico (estilo TestFit)."""
from __future__ import annotations

from shapely.geometry import Polygon, mapping

from app.core import layout

# Terreno retangular ~200 x 120 m em Goiânia (graus aproximados).
LON0, LAT0 = -49.2550, -16.6790
DX, DY = 200 / 106_600.0, 120 / 110_570.0
RECT = Polygon([(LON0, LAT0), (LON0 + DX, LAT0), (LON0 + DX, LAT0 + DY), (LON0, LAT0 + DY)])


def test_rect_lot_yields_units_and_consistent_stats():
    res = layout.generate(mapping(RECT), layout.LayoutParams())
    s = res["stats"]
    assert s["units"] > 50, "terreno de 2,4 ha deveria comportar dezenas de casas"
    feats = res["features"]["features"]
    lots = [f for f in feats if f["properties"]["kind"] == "lot"]
    houses = [f for f in feats if f["properties"]["kind"] == "house"]
    assert len(lots) == s["units"]
    assert len(houses) == s["units"]
    # Aproveitamento: lotes + vias + verde ≈ área do terreno (tolerância 5%)
    total = s["lots_area_m2"] + s["roads_area_m2"] + s["green_area_m2"]
    assert abs(total - s["site_area_m2"]) < s["site_area_m2"] * 0.05
    assert 0 < s["coverage_pct"] < 100
    assert not s["truncated"]


def test_params_change_unit_count():
    small = layout.generate(mapping(RECT), layout.LayoutParams.from_dict(
        {"lot_width_m": 6, "lot_depth_m": 15}))
    big = layout.generate(mapping(RECT), layout.LayoutParams.from_dict(
        {"lot_width_m": 15, "lot_depth_m": 30}))
    assert small["stats"]["units"] > big["stats"]["units"]


def test_l_shape_does_not_crash():
    l_shape = Polygon([
        (LON0, LAT0), (LON0 + DX, LAT0), (LON0 + DX, LAT0 + DY / 2),
        (LON0 + DX / 2, LAT0 + DY / 2), (LON0 + DX / 2, LAT0 + DY), (LON0, LAT0 + DY),
    ])
    res = layout.generate(mapping(l_shape), layout.LayoutParams())
    assert res["stats"]["units"] > 0
    # nenhuma casa fora do terreno: aproveitamento < 100%
    assert res["stats"]["efficiency_pct"] < 100


def test_tiny_lot_yields_zero_units():
    tiny = Polygon([(LON0, LAT0), (LON0 + DX / 40, LAT0),
                    (LON0 + DX / 40, LAT0 + DY / 40), (LON0, LAT0 + DY / 40)])
    res = layout.generate(mapping(tiny), layout.LayoutParams())
    assert res["stats"]["units"] == 0


def test_from_dict_clamps_garbage():
    p = layout.LayoutParams.from_dict(
        {"lot_width_m": -10, "lot_depth_m": "abc", "road_width_m": 9999,
         "angle_deg": "x"})
    assert p.lot_width_m == 3      # clamp inferior
    assert p.lot_depth_m == 20.0   # default
    assert p.road_width_m == 30    # clamp superior
    assert p.angle_deg is None


def test_manual_angle_respected():
    res = layout.generate(mapping(RECT), layout.LayoutParams.from_dict({"angle_deg": 45}))
    assert res["angle_used"] == 45.0
