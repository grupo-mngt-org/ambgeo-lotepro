"""Relatório de análise com múltiplos cenários de prospecção.

A detecção roda uma única vez (permissiva) e este módulo deriva, sobre o MESMO
conjunto de candidatos, três "lentes" de prospecção — do restrito ao amplo —
além de um resumo geral. Assim o usuário recebe a análise completa de uma vez,
sem precisar reconfigurar e rodar de novo.
"""
from __future__ import annotations

import geopandas as gpd

# Cenários = estratégias de prospecção (filtros sobre ocupação e área).
SCENARIOS = [
    {"key": "conservador", "label": "Conservador",
     "desc": "Praticamente vazios", "max_occ": 0.05, "min_area": 1000.0, "color": "#2ecc71"},
    {"key": "moderado", "label": "Moderado",
     "desc": "Subutilizados", "max_occ": 0.15, "min_area": 500.0, "color": "#f1c40f"},
    {"key": "amplo", "label": "Amplo",
     "desc": "Qualquer subutilização", "max_occ": 0.30, "min_area": 300.0, "color": "#e67e22"},
]

# Parâmetros permissivos da detecção única (cobrem o cenário mais amplo).
PERMISSIVE = {"min_area_m2": 300.0, "max_occupation_ratio": 0.30}


def _ha(area_m2: float) -> float:
    return round(area_m2 / 10_000.0, 2)


def build_report(results: gpd.GeoDataFrame) -> dict:
    """Monta o relatório de cenários + resumo a partir dos candidatos detectados."""
    total = len(results)
    if total == 0:
        return {"total": 0, "scenarios": [], "by_zoning": [], "largest": [],
                "area_total_m2": 0.0, "area_total_ha": 0.0}

    occ = results["occupation"]
    area = results["area_m2"]

    scenarios = []
    for s in SCENARIOS:
        mask = (occ <= s["max_occ"]) & (area >= s["min_area"])
        sub = results[mask]
        scenarios.append({
            "key": s["key"], "label": s["label"], "desc": s["desc"], "color": s["color"],
            "max_occ": s["max_occ"], "min_area": s["min_area"],
            "count": int(len(sub)),
            "area_m2": round(float(sub["area_m2"].sum()), 1),
            "area_ha": _ha(float(sub["area_m2"].sum())),
        })

    # Distribuição por zoneamento (quando houver dado real).
    by_zoning = []
    if "zoning" in results.columns:
        grp = results.groupby("zoning")["area_m2"].agg(["count", "sum"]).reset_index()
        grp = grp[grp["zoning"] != "N/D"].sort_values("sum", ascending=False)
        by_zoning = [
            {"zoning": r["zoning"], "count": int(r["count"]), "area_ha": _ha(float(r["sum"]))}
            for _, r in grp.head(8).iterrows()
        ]

    largest = [
        {"id": int(r["id"]), "area_m2": float(r["area_m2"]),
         "occupation": float(r["occupation"]), "zoning": r.get("zoning", "N/D"),
         "lat": float(r["lat"]), "lon": float(r["lon"])}
        for _, r in results.nlargest(5, "area_m2").iterrows()
    ]

    return {
        "total": total,
        "area_total_m2": round(float(area.sum()), 1),
        "area_total_ha": _ha(float(area.sum())),
        "scenarios": scenarios,
        "by_zoning": by_zoning,
        "largest": largest,
    }
