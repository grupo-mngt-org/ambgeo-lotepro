"""Testes do motor de score de viabilidade (puro, sem rede)."""
from __future__ import annotations

from app.core import score


def _metrics(**overrides) -> dict:
    base = {
        "area_m2": 10_000.0,
        "slope_pct": 3.0,
        "elev_range_m": 2.0,
        "road_class": "residential",
        "surface": "asphalt",
        "frontage_m": 40.0,
        "compactness": 0.785,   # quadrado
        "amenity_counts": {"school": 1, "market": 2, "health": 1, "bus": 3, "pharmacy": 1},
        "highway_dist_m": 300.0,
    }
    base.update(overrides)
    return base


def test_perfect_lot_scores_high():
    prof = score.get_profile("condominio_casas")
    res = score.compute(_metrics(), prof, 2_000, 50_000)
    assert res["score"] >= 90, f"lote ideal deveria pontuar alto, veio {res['score']}"
    assert res["grade"] == "A"
    assert res["flags"] == []


def test_steep_lot_penalized_and_flagged():
    prof = score.get_profile("condominio_casas")
    res = score.compute(_metrics(slope_pct=20.0), prof, 2_000, 50_000)  # > max 15%
    assert "ingreme" in res["flags"]
    assert res["breakdown"]["slope"]["score"] == 0.0


def test_landlocked_lot_flagged():
    prof = score.get_profile("condominio_casas")
    res = score.compute(_metrics(frontage_m=0.0), prof, 2_000, 50_000)
    assert "encravado" in res["flags"]
    assert res["breakdown"]["frontage"]["score"] == 0.0


def test_missing_dem_renormalizes_not_zero():
    """Sem dado de relevo, o score não despenca — pesos renormalizados."""
    prof = score.get_profile("condominio_casas")
    res = score.compute(_metrics(slope_pct=None), prof, 2_000, 50_000)
    assert res["score"] >= 85, "falta de dado não deveria punir o lote"
    assert "sem_dado_relevo" in res["flags"]
    assert res["breakdown"]["slope"]["score"] is None


def test_area_fit_inside_and_outside_target():
    assert score.score_area_fit(5_000, 2_000, 50_000) == 1.0
    assert score.score_area_fit(1_000, 2_000, 50_000) == 0.5     # metade do mínimo
    assert score.score_area_fit(100_000, 2_000, 50_000) == 0.5   # dobro do máximo


def test_logistics_profile_uses_highway_distance():
    prof = score.get_profile("galpao_logistico")
    near = score.compute(_metrics(highway_dist_m=200.0), prof, 5_000, 200_000)
    far = score.compute(_metrics(highway_dist_m=8_000.0), prof, 5_000, 200_000)
    assert near["score"] > far["score"], "galpão perto de rodovia deve pontuar mais"
    assert near["breakdown"]["infra"]["score"] == 1.0


def test_weights_override_changes_score():
    prof = score.get_profile("personalizado")
    base = score.compute(_metrics(slope_pct=15.0), prof, 2_000, 50_000)
    heavy_slope = score.compute(_metrics(slope_pct=15.0), prof, 2_000, 50_000,
                                weights_override={"slope": 90})
    assert heavy_slope["score"] < base["score"], \
        "peso maior em declividade ruim deve baixar o score"


def test_unknown_profile_falls_back():
    assert score.get_profile("nao_existe")["label"] == "Condomínio de casas"


def test_list_profiles_public_shape():
    profs = score.list_profiles()
    keys = {p["key"] for p in profs}
    assert {"condominio_casas", "galpao_logistico", "loteamento", "personalizado"} <= keys
    for p in profs:
        assert {"key", "label", "desc", "target_area_m2", "max_slope_pct"} <= set(p)


def test_surface_unpaved_scores_below_asphalt():
    paved = score.score_access("residential", "asphalt")
    dirt = score.score_access("residential", "dirt")
    unknown = score.score_access("residential", None)
    assert paved > unknown > dirt
