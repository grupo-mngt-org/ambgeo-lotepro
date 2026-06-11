"""Testes do motor de detecção (provider footprint) e do pipeline de qualificação."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from app.providers import DetectionParams, get_provider
from app.core import geo

# Centro/escala iguais ao gerador de amostras.
LON0, LAT0 = -49.2550, -16.6790
M_LON, M_LAT = 106_600.0, 110_570.0


def _rect(cx, cy, w, h):
    dlon, dlat = (w / 2) / M_LON, (h / 2) / M_LAT
    clon, clat = cx / M_LON, cy / M_LAT
    return box(LON0 + clon - dlon, LAT0 + clat - dlat, LON0 + clon + dlon, LAT0 + clat + dlat)


def _aoi():
    return gpd.GeoDataFrame(geometry=[_rect(0, 0, 360, 270)], crs="EPSG:4326")


def _buildings():
    return gpd.GeoDataFrame(geometry=[_rect(-120, 60, 40, 35), _rect(110, 70, 70, 60)],
                            crs="EPSG:4326")


def _zoning():
    return gpd.GeoDataFrame(
        {"zoning": ["ZR1", "ZCS"]},
        geometry=[_rect(-90, 0, 180, 270), _rect(90, 0, 180, 270)],
        crs="EPSG:4326",
    )


def test_gaps_mode_finds_vacant_and_respects_min_area():
    provider = get_provider("footprint")
    params = DetectionParams(mode="gaps", min_area_m2=500, max_occupation_ratio=0.15)
    res = provider.detect(_aoi(), _buildings(), _zoning(), params)

    assert not res.empty, "deveria encontrar vazios"
    assert (res["area_m2"] >= 500).all(), "filtro de área mínima violado"
    # Gaps removem construções: ocupação ~0.
    assert (res["occupation"] <= 0.15).all()
    assert set(res.columns) >= {"area_m2", "occupation", "potential", "zoning", "street_view"}


def test_min_area_filter_excludes_small():
    provider = get_provider("footprint")
    res = provider.detect(_aoi(), _buildings(), _zoning(),
                          DetectionParams(mode="gaps", min_area_m2=1_000_000))
    assert res.empty, "área mínima enorme deveria zerar resultados"


def test_parcels_mode_occupation_ratio():
    # Um lote 100% coberto por edificação deve ser excluído pela ocupação.
    lot = gpd.GeoDataFrame(geometry=[_rect(0, 0, 50, 50)], crs="EPSG:4326")
    full_building = gpd.GeoDataFrame(geometry=[_rect(0, 0, 50, 50)], crs="EPSG:4326")
    provider = get_provider("footprint")
    res = provider.detect(lot, full_building, None,
                          DetectionParams(mode="parcels", min_area_m2=100, max_occupation_ratio=0.15))
    assert res.empty, "lote totalmente construído não é vazio"


def test_area_measured_in_meters():
    # AOI de 360x270 m -> ~97.200 m². Medição via UTM deve bater (tolerância 3%).
    g = _aoi()
    gm = geo.to_metric(g)
    assert abs(geo.area_m2(gm.geometry.iloc[0]) - 97_200) < 97_200 * 0.03


def test_zoning_label_assigned():
    provider = get_provider("footprint")
    res = provider.detect(_aoi(), _buildings(), _zoning(),
                          DetectionParams(mode="gaps", min_area_m2=500))
    assert res["zoning"].isin(["ZR1", "ZCS", "N/D"]).all()
    assert (res["zoning"] != "N/D").any(), "deveria rotular ao menos um vazio"
