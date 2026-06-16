"""Testes do Motor de Bolhas — parte determinística (puro, sem rede)."""
from __future__ import annotations

import json

from app.core import ai, bolhas


def _props(**overrides) -> dict:
    base = {
        "id": 1, "area_m2": 12_000.0, "slope_pct": 6.0, "frontage_m": 40.0,
        "compactness": 0.7, "zoning": "ZR-2", "score": 78.0, "flags": "",
        "score_breakdown": json.dumps({"infra": {"score": 0.6}, "access": {"score": 0.85}}),
    }
    base.update(overrides)
    return base


def test_metrics_extrai_infra_e_acesso_do_breakdown():
    m = bolhas.metrics_from_props(_props())
    assert m["infra"] == 0.6 and m["access"] == 0.85
    assert m["area_m2"] == 12_000.0


def test_entorno_pobre_infere_faixa_baixa():
    pobre = bolhas.metrics_from_props(_props(
        score_breakdown=json.dumps({"infra": {"score": 0.1}, "access": {"score": 0.3}})))
    rico = bolhas.metrics_from_props(_props(
        score_breakdown=json.dumps({"infra": {"score": 0.9}, "access": {"score": 0.9}})))
    assert bolhas.infer_faixa(pobre) < bolhas.infer_faixa(rico)
    assert bolhas.infer_faixa(rico) == 4


def test_rank_devolve_todas_as_bolhas_ordenadas():
    rk = bolhas.rank_bolhas(bolhas.metrics_from_props(_props()))
    assert len(rk) == len(bolhas.BOLHAS)
    assert rk == sorted(rk, key=lambda x: x["score"], reverse=True)
    assert all(0 <= r["score"] <= 100 for r in rk)


def test_mais_vida_perde_pontos_em_terreno_ingreme():
    """+Vida exige terreno plano (max_slope 8%): declividade alta derruba o fit."""
    plano = bolhas.metrics_from_props(_props(slope_pct=3.0))
    ingreme = bolhas.metrics_from_props(_props(slope_pct=25.0))
    b = bolhas.BOLHAS["mais_vida_bem_estar"]
    assert bolhas.score_fit(b, plano) > bolhas.score_fit(b, ingreme)


def test_viabilidade_respeita_teto_da_faixa():
    v3 = bolhas.viabilidade_economica(3, units=40, area_m2=12_000.0)
    v4 = bolhas.viabilidade_economica(4, units=40, area_m2=12_000.0)
    assert v3["preco_unidade_ref"] == 400_000 and v3["preco_teto_oficial"]
    assert v4["preco_unidade_ref"] == 600_000
    assert v3["vgv_estimado"] == 40 * 400_000
    assert v3["custo_alvo_max"] < v3["vgv_estimado"]  # margem reservada
    assert not v3["unidades_estimadas"]  # units informado → não estimado


def test_viabilidade_estima_unidades_quando_ausente():
    v = bolhas.viabilidade_economica(2, units=None, area_m2=10_000.0)
    assert v["unidades_estimadas"] and v["unidades"] == 40  # 10000 / 250


def test_analisar_cai_para_heuristico_sem_ia(monkeypatch):
    """Sem IA configurada, o estudo sai do ranking determinístico (nunca quebra)."""
    monkeypatch.setattr(ai, "is_configured", lambda: False)
    est = bolhas.analisar(_props(), endereco={"cidade": "Goiânia", "uf": "GO"})
    assert est["modo"] == "heuristico"
    assert est["bolha_key"] in bolhas.BOLHAS
    assert 0 <= est["score_aplicabilidade"] <= 100
    assert est["viabilidade"]["vgv_estimado"] > 0
    assert est["fit_deterministico"] and est["aviso"]


def test_analisar_usa_ia_mockada(monkeypatch):
    """Com IA mockada devolvendo JSON, o estudo entra em modo 'ia'."""
    fake = {
        "bolha_key": "estilo_compacto_autoral", "score_aplicabilidade": 88,
        "faixa_mcmv": 3, "publico_alvo": "jovens urbanos",
        "promessa_central": "viver com estilo", "modulos_sugeridos": ["coworking"],
        "programas": {"arte_incrivel": {"incluir": True, "motivo": "x"}},
        "riscos": ["custo"], "justificativa": "contexto urbano",
        "alternativas": [{"bolha_nome": "Detalhe Santorini", "score": 80, "porque": "y"}],
    }
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(ai, "chat",
                        lambda *a, **k: {"content": json.dumps(fake), "model": "fake/model"})
    est = bolhas.analisar(_props(), endereco={"cidade": "Goiânia", "uf": "GO"})
    assert est["modo"] == "ia" and est["modelo"] == "fake/model"
    assert est["bolha_key"] == "estilo_compacto_autoral"
    assert est["score_aplicabilidade"] == 88
    assert est["viabilidade"]["faixa"] == 3


def test_extract_json_pega_ultimo_objeto_apos_raciocinio():
    """extract_json deve ignorar o 'pensamento' e pegar o JSON final."""
    txt = ('Vou pensar... talvez {"rascunho": 1} mas na verdade...\n'
           'Resposta final:\n```json\n{"bolha_key": "x", "score_aplicabilidade": 90}\n```')
    out = ai.extract_json(txt)
    assert out == {"bolha_key": "x", "score_aplicabilidade": 90}
