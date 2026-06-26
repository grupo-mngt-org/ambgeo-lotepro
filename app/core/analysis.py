"""Análise por endereço + raio — fluxo completo, com progresso opcional.

Compartilhado pela rota síncrona /api/analyze (compatibilidade) e pelo job
assíncrono /api/analyze/start (frontend, com barra de progresso).
"""
from __future__ import annotations

from . import enrich, io, osm, report, score, store
from ..providers import DetectionParams, get_provider


def _noop(stage: str, pct: float, detail: str = "") -> None:
    pass


def analyze_radius(
    progress=None,
    *,
    query: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float = 500.0,
    buildings_source: str = "auto",
    profile: str = "condominio_casas",
    target_min_m2: float | None = None,
    target_max_m2: float | None = None,
    enrich_enabled: bool = True,
    weights: dict | None = None,
    provider: str = "footprint",
    min_area_m2: float = report.PERMISSIVE["min_area_m2"],
    max_occupation_ratio: float = report.PERMISSIVE["max_occupation_ratio"],
    min_width_m: float = 6.0,
    building_buffer_m: float = 1.5,
    project_id: str | None = None,
) -> dict:
    progress = progress or _noop

    pid = project_id or store.create_project(query or "Análise")["id"]
    store.get_meta(pid)  # KeyError se o projeto não existe (rota mapeia p/ 404)

    progress("Coletando dados reais (vias, exclusões, edificações)", 5)
    data = osm.fetch_area(
        "", query, radius_m, buildings_source, lat, lon,
        progress=lambda msg: progress("Coletando dados reais", 15, msg))
    store.save_layer(pid, "aoi", data["aoi"])
    if data["buildings_count"] > 0:
        store.save_layer(pid, "buildings", data["buildings"])
    if data.get("exclusions") is not None and not data["exclusions"].empty:
        store.save_layer(pid, "exclusions", data["exclusions"])

    zoning = store.load_layer(pid, "zoning")
    params = DetectionParams(
        provider=provider, mode="gaps",
        min_area_m2=min_area_m2, max_occupation_ratio=max_occupation_ratio,
        min_width_m=min_width_m, building_buffer_m=building_buffer_m)

    progress("Detectando vazios urbanos", 45)
    results = get_provider(params.provider).detect(
        data["aoi"], data["buildings"], zoning, params)

    if enrich_enabled and not results.empty:
        progress("Qualificando lotes (relevo, acesso, entorno)", 65,
                 f"{len(results)} candidatos")
        try:
            results = enrich.enrich_and_score(
                results, profile, target_min_m2, target_max_m2,
                data["center"]["lat"], data["center"]["lon"], data["radius_m"],
                weights,
            )
        except Exception:
            pass  # análise nunca falha por causa do enriquecimento

    progress("Salvando resultados", 92)
    store.save_layer(pid, "results", results)
    store.update_meta(pid, last_detect={
        "count": len(results), "source": data["buildings_source"],
        "profile": profile, "mode": "radius"})

    prof = score.get_profile(profile)
    return {
        "mode": "radius",
        "project_id": pid,
        "query": data["query"],
        "center": data["center"],
        "radius_m": data["radius_m"],
        "buildings_source": data["buildings_source"],
        "provider": params.provider,
        "profile": profile,
        "profile_label": prof["label"],
        "target_min_m2": target_min_m2 or prof["target_area_m2"][0],
        "target_max_m2": target_max_m2 or prof["target_area_m2"][1],
        "buildings": data["buildings_count"],
        "count": len(results),
        "results": io.to_geojson_dict(results),
        "report": report.build_report(results),
        "lots_info": store.get_lots_info(pid),
    }
