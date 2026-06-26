"""Motor de score de viabilidade por finalidade de compra.

Cada PERFIL (finalidade) define pesos para os critérios mensuráveis:

  slope      — declividade do terreno (SRTM 30 m). Terreno plano = nota alta.
  access     — qualidade do acesso: classe da via mais próxima + pavimentação
               (tag `surface` do OSM). Asfalto = nota alta.
  frontage   — testada: metros de divisa do lote tocando via pública.
               Lote encravado (sem testada) = nota zero + flag.
  shape      — compacidade do polígono (Polsby-Popper 4πA/P²).
               Lotes regulares aproveitam melhor a área construível.
  infra      — infraestrutura do entorno:
                 modo "amenities": escolas, mercados, saúde, ônibus ≤ 800 m
                 modo "logistics": proximidade de rodovia/via arterial
  area_fit   — aderência à metragem-alvo informada pelo usuário.

Score final = média ponderada × 100, com nota A/B/C/D. Critérios sem dado
(ex.: falha de rede no DEM) são excluídos e os pesos renormalizados — o
score nunca é punido por falta de dado, mas o breakdown mostra "s/ dado".

IMPORTANTE (honestidade do método): este score automatiza a TRIAGEM técnica
de viabilidade. Não substitui a due diligence legal (certidão de matrícula,
ônus, débitos) nem levantamento topográfico para projeto executivo.
"""
from __future__ import annotations

import math

# ----------------------------------------------------------------------------
# Perfis de finalidade
# ----------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "condominio_casas": {
        "label": "Condomínio de casas",
        "desc": "Terreno plano, acesso pavimentado, comércio/escola por perto.",
        "target_area_m2": [2_000.0, 50_000.0],
        "max_slope_pct": 15.0,        # acima disso a nota de declividade zera
        "infra_mode": "amenities",
        "weights": {"slope": 25, "access": 15, "frontage": 10,
                    "shape": 10, "infra": 20, "area_fit": 20},
    },
    "galpao_logistico": {
        "label": "Galpão logístico (aluguel)",
        "desc": "Terreno plano e grande, próximo de rodovia/via arterial.",
        "target_area_m2": [5_000.0, 200_000.0],
        "max_slope_pct": 8.0,          # galpão exige platô quase plano
        "infra_mode": "logistics",
        "weights": {"slope": 30, "access": 10, "frontage": 10,
                    "shape": 15, "infra": 25, "area_fit": 10},
    },
    "loteamento": {
        "label": "Loteamento residencial",
        "desc": "Gleba grande para parcelar; declividade moderada aceitável.",
        "target_area_m2": [20_000.0, 1_000_000.0],
        "max_slope_pct": 25.0,
        "infra_mode": "amenities",
        "weights": {"slope": 20, "access": 15, "frontage": 10,
                    "shape": 10, "infra": 15, "area_fit": 30},
    },
    "personalizado": {
        "label": "Personalizado",
        "desc": "Pesos iguais; ajuste a metragem e (via API) os pesos.",
        "target_area_m2": [500.0, 100_000.0],
        "max_slope_pct": 20.0,
        "infra_mode": "amenities",
        "weights": {"slope": 17, "access": 17, "frontage": 16,
                    "shape": 16, "infra": 17, "area_fit": 17},
    },
}

CRITERIA_LABELS = {
    "slope": "Declividade",
    "access": "Acesso/pavimentação",
    "frontage": "Testada (frente p/ via)",
    "shape": "Formato do lote",
    "infra": "Infraestrutura do entorno",
    "area_fit": "Aderência à metragem",
}


def get_profile(key: str) -> dict:
    return PROFILES.get((key or "").lower(), PROFILES["condominio_casas"])


def list_profiles() -> list[dict]:
    """Versão pública dos perfis (para o frontend montar o seletor)."""
    return [
        {"key": k, "label": p["label"], "desc": p["desc"],
         "target_area_m2": p["target_area_m2"], "max_slope_pct": p["max_slope_pct"]}
        for k, p in PROFILES.items()
    ]


# ----------------------------------------------------------------------------
# Notas por critério (todas devolvem 0..1 ou None quando sem dado)
# ----------------------------------------------------------------------------
def score_slope(slope_pct: float | None, max_slope_pct: float) -> float | None:
    if slope_pct is None:
        return None
    if slope_pct >= max_slope_pct:
        return 0.0
    return round(1.0 - slope_pct / max_slope_pct, 3)


# Classe de via → nota base de acesso (residencial pavimentada é o ideal
# para condomínio; vias expressas pontuam menos por ruído/acesso restrito).
_ROAD_CLASS_SCORE = {
    "residential": 1.0, "tertiary": 1.0, "secondary": 0.9, "unclassified": 0.7,
    "primary": 0.8, "living_street": 0.9, "trunk": 0.5, "motorway": 0.4,
    "service": 0.5, "track": 0.25, "path": 0.1, "footway": 0.1,
}
_SURFACE_SCORE = {
    "asphalt": 1.0, "paved": 1.0, "concrete": 1.0, "paving_stones": 0.9,
    "sett": 0.8, "cobblestone": 0.7, "compacted": 0.5, "gravel": 0.35,
    "fine_gravel": 0.4, "unpaved": 0.25, "ground": 0.2, "dirt": 0.15,
    "sand": 0.1, "grass": 0.1, "mud": 0.05,
}


def score_access(road_class: str | None, surface: str | None) -> float | None:
    """Nota de acesso da via mais próxima: 50% classe + 50% pavimentação.

    `surface` ausente no OSM (caso comum no Brasil) → assume o típico da
    classe: residencial/terciária urbana costuma ser pavimentada (0.7),
    track/path não (0.2).
    """
    if road_class is None:
        return None
    cls = _ROAD_CLASS_SCORE.get(road_class, 0.6)
    if surface and surface in _SURFACE_SCORE:
        surf = _SURFACE_SCORE[surface]
    else:
        surf = 0.2 if road_class in ("track", "path") else 0.7  # heurística BR
    return round(cls * 0.5 + surf * 0.5, 3)


def score_frontage(frontage_m: float | None, area_m2: float) -> float | None:
    """Testada em relação ao porte do lote. 0 m = encravado (nota 0).

    Referência: testada "boa" ≈ 20% do lado de um quadrado equivalente
    (lote 10 000 m² → lado 100 m → 20 m de testada já pontua 1.0).
    """
    if frontage_m is None:
        return None
    if frontage_m <= 0:
        return 0.0
    side = math.sqrt(max(area_m2, 1.0))
    good = max(10.0, side * 0.2)
    return round(min(1.0, frontage_m / good), 3)


def score_shape(compactness: float | None) -> float | None:
    """Polsby-Popper (0..1): círculo = 1. Normaliza para que um quadrado
    (PP ≈ 0.785) pontue 1.0; faixas estreitas pontuam perto de 0."""
    if compactness is None:
        return None
    return round(min(1.0, compactness / 0.785), 3)


def score_infra_amenities(counts: dict[str, int] | None) -> float | None:
    """Presença de serviços ≤ 800 m do lote (modo condomínio/residencial)."""
    if counts is None:
        return None
    score = 0.0
    score += 0.25 if counts.get("school", 0) > 0 else 0.0
    score += 0.25 if counts.get("market", 0) > 0 else 0.0
    score += 0.20 if counts.get("health", 0) > 0 else 0.0
    score += 0.15 if counts.get("bus", 0) > 0 else 0.0
    score += 0.15 if counts.get("pharmacy", 0) > 0 else 0.0
    return round(score, 3)


def score_infra_logistics(highway_dist_m: float | None) -> float | None:
    """Proximidade de rodovia/via arterial (modo galpão logístico).
    ≤ 500 m = 1.0; decaimento exponencial com escala de 3 km."""
    if highway_dist_m is None:
        return None
    if highway_dist_m <= 500:
        return 1.0
    return round(math.exp(-(highway_dist_m - 500) / 3_000.0), 3)


def score_area_fit(area_m2: float, target_min: float, target_max: float) -> float:
    """1.0 dentro da faixa-alvo; decai proporcionalmente fora dela."""
    if target_min <= area_m2 <= target_max:
        return 1.0
    if area_m2 < target_min:
        return round(max(0.0, area_m2 / target_min), 3)
    return round(max(0.0, target_max / area_m2), 3)


# ----------------------------------------------------------------------------
# Score final
# ----------------------------------------------------------------------------
def grade(score_0_100: float) -> str:
    if score_0_100 >= 80:
        return "A"
    if score_0_100 >= 65:
        return "B"
    if score_0_100 >= 50:
        return "C"
    return "D"


def compute(metrics: dict, profile: dict,
            target_min: float, target_max: float,
            weights_override: dict | None = None) -> dict:
    """Combina as notas por critério no score final 0–100.

    `metrics` (de enrich.py): slope_pct, road_class, surface, frontage_m,
    compactness, amenity_counts | highway_dist_m, area_m2.

    Critérios None são excluídos com renormalização de pesos.
    Retorna {score, grade, breakdown: {crit: {score, weight, label, detail}}, flags}.
    """
    weights = dict(profile["weights"])
    if weights_override:
        for k, v in weights_override.items():
            if k in weights:
                try:
                    weights[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    pass

    if profile["infra_mode"] == "logistics":
        infra = score_infra_logistics(metrics.get("highway_dist_m"))
        infra_detail = (f"rodovia a {metrics['highway_dist_m']:.0f} m"
                        if metrics.get("highway_dist_m") is not None else "s/ dado")
    else:
        infra = score_infra_amenities(metrics.get("amenity_counts"))
        c = metrics.get("amenity_counts") or {}
        infra_detail = (f"escola:{c.get('school', 0)} mercado:{c.get('market', 0)} "
                        f"saúde:{c.get('health', 0)} ônibus:{c.get('bus', 0)}"
                        if metrics.get("amenity_counts") is not None else "s/ dado")

    notes: dict[str, tuple[float | None, str]] = {
        "slope": (score_slope(metrics.get("slope_pct"), profile["max_slope_pct"]),
                  f"{metrics['slope_pct']:.1f}% (desnível {metrics.get('elev_range_m', 0) or 0:.1f} m)"
                  if metrics.get("slope_pct") is not None else "s/ dado"),
        "access": (score_access(metrics.get("road_class"), metrics.get("surface")),
                   f"{metrics.get('road_class') or '—'}"
                   + (f", {metrics['surface']}" if metrics.get("surface") else "")),
        "frontage": (score_frontage(metrics.get("frontage_m"), metrics["area_m2"]),
                     f"{metrics['frontage_m']:.0f} m de testada"
                     if metrics.get("frontage_m") is not None else "s/ dado"),
        "shape": (score_shape(metrics.get("compactness")),
                  f"compacidade {metrics['compactness']:.2f}"
                  if metrics.get("compactness") is not None else "s/ dado"),
        "infra": (infra, infra_detail),
        "area_fit": (score_area_fit(metrics["area_m2"], target_min, target_max),
                     f"{metrics['area_m2']:,.0f} m² (alvo {target_min:,.0f}–{target_max:,.0f})"),
    }

    total_w = sum(weights[k] for k, (s, _) in notes.items() if s is not None)
    if total_w <= 0:
        final = 0.0
    else:
        final = sum(weights[k] * s for k, (s, _) in notes.items() if s is not None) / total_w * 100.0
    final = round(final, 1)

    flags = []
    if notes["frontage"][0] == 0.0:
        flags.append("encravado")  # sem frente para via — acesso juridicamente complexo
    sp = metrics.get("slope_pct")
    if sp is not None and sp >= profile["max_slope_pct"]:
        flags.append("ingreme")
    if sp is None:
        flags.append("sem_dado_relevo")

    breakdown = {
        k: {"label": CRITERIA_LABELS[k], "score": s, "weight": weights[k], "detail": d}
        for k, (s, d) in notes.items()
    }
    return {"score": final, "grade": grade(final), "breakdown": breakdown, "flags": flags}
