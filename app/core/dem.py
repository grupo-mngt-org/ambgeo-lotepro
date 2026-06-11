"""Elevação e declividade via OpenTopoData (SRTM 30 m) — gratuito, sem chave.

API pública: https://api.opentopodata.org/v1/srtm30m?locations=lat,lon|...
Limites: 100 pontos/chamada, 1 chamada/s, 1000 chamadas/dia. Por isso:
  - amostramos poucos pontos por lote (grade adaptativa, máx. 12);
  - agrupamos os pontos de TODOS os lotes em chamadas de 100;
  - cache em disco por coordenada (SRTM é estático — nunca expira).

A declividade é estimada ajustando um plano (mínimos quadrados) aos pontos
amostrados em CRS métrico: slope% = sqrt(a² + b²) × 100. Resolução SRTM de
30 m é adequada para TRIAGEM de terrenos (não substitui levantamento
planialtimétrico para projeto executivo).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from shapely.geometry import Point

from .. import config

OPENTOPO_URL = "https://api.opentopodata.org/v1/srtm30m"
HTTP_HEADERS = {"User-Agent": "LotePro/0.1 (+devs@grupomngt.com.br)"}
_CACHE_FILE = config.BASE_DIR / "cache" / "dem_cache.json"
_BATCH = 100          # máximo de pontos por chamada
_MAX_PTS_PER_LOT = 12
_MIN_PTS_PER_LOT = 3


def _cache_load() -> dict:
    if _CACHE_FILE.is_file():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _cache_save(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass  # cache é otimização, nunca deve quebrar a análise


def _key(lat: float, lon: float) -> str:
    # 5 casas decimais ≈ 1 m — mais fino que o pixel SRTM (30 m)
    return f"{lat:.5f},{lon:.5f}"


def sample_points(geom_4326, geom_m, n_target: int = _MAX_PTS_PER_LOT) -> list[tuple[float, float]]:
    """Grade de pontos (lat, lon) dentro do polígono. Inclui o centroide.

    `geom_4326` em graus (para as coordenadas de saída); `geom_m` em CRS
    métrico apenas para decidir a densidade (lotes pequenos → menos pontos).
    """
    pts: list[tuple[float, float]] = []
    c = geom_4326.centroid
    if geom_4326.contains(c):
        pts.append((c.y, c.x))

    minx, miny, maxx, maxy = geom_4326.bounds
    # Lotes < 2 500 m² cabem em 1 pixel SRTM — poucos pontos bastam.
    n_side = 2 if geom_m.area < 2_500 else 4
    xs = np.linspace(minx, maxx, n_side + 2)[1:-1]
    ys = np.linspace(miny, maxy, n_side + 2)[1:-1]
    for x in xs:
        for y in ys:
            if len(pts) >= n_target:
                break
            if geom_4326.contains(Point(x, y)):
                pts.append((float(y), float(x)))

    if len(pts) < _MIN_PTS_PER_LOT:
        # fallback: representative_point + cantos do envelope interno
        rp = geom_4326.representative_point()
        pts.append((rp.y, rp.x))
    # dedup
    seen, out = set(), []
    for lat, lon in pts:
        k = _key(lat, lon)
        if k not in seen:
            seen.add(k)
            out.append((lat, lon))
    return out


def fetch_elevations(points: list[tuple[float, float]]) -> dict[str, float | None]:
    """Eleva­ções (m) para uma lista de (lat, lon). Usa cache + chamadas em lote.

    Retorna {key: elevação | None}. Falhas de rede degradam para None
    (o score simplesmente ignora o critério de declividade).
    """
    cache = _cache_load()
    result: dict[str, float | None] = {}
    missing: list[tuple[float, float]] = []

    for lat, lon in points:
        k = _key(lat, lon)
        if k in cache:
            result[k] = cache[k]
        else:
            missing.append((lat, lon))

    new_entries = False
    for i in range(0, len(missing), _BATCH):
        batch = missing[i:i + _BATCH]
        locs = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in batch)
        try:
            if i > 0:
                time.sleep(1.1)  # rate limit público: 1 chamada/s
            resp = requests.get(
                OPENTOPO_URL, params={"locations": locs},
                headers=HTTP_HEADERS, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("results", [])
        except Exception:
            for lat, lon in batch:
                result[_key(lat, lon)] = None
            continue

        for (lat, lon), r in zip(batch, data):
            elev = r.get("elevation")
            k = _key(lat, lon)
            result[k] = float(elev) if elev is not None else None
            cache[k] = result[k]
            new_entries = True

    if new_entries:
        _cache_save(cache)
    return result


def slope_metrics(geom_4326, geom_m, mcrs, elevations: dict[str, float | None],
                  pts: list[tuple[float, float]]) -> dict:
    """Declividade média (%) e desnível (m) de um lote a partir das elevações.

    Ajusta um plano z = a·x + b·y + c (mínimos quadrados) em coordenadas
    métricas; slope% = sqrt(a²+b²) × 100. Com < 3 pontos válidos retorna None.
    """
    valid = [(lat, lon, elevations.get(_key(lat, lon)))
             for lat, lon in pts]
    valid = [(lat, lon, z) for lat, lon, z in valid if z is not None]
    if len(valid) < 3:
        return {"slope_pct": None, "elev_range_m": None}

    g = gpd.GeoSeries([Point(lon, lat) for lat, lon, _ in valid], crs="EPSG:4326").to_crs(mcrs)
    xs = np.array([p.x for p in g])
    ys = np.array([p.y for p in g])
    zs = np.array([z for _, _, z in valid], dtype=float)

    elev_range = float(zs.max() - zs.min())
    try:
        A = np.column_stack([xs - xs.mean(), ys - ys.mean(), np.ones(len(xs))])
        coef, *_ = np.linalg.lstsq(A, zs, rcond=None)
        slope_pct = float(np.hypot(coef[0], coef[1]) * 100.0)
    except Exception:
        # fallback grosseiro: desnível / diâmetro do lote
        diameter = max(geom_m.bounds[2] - geom_m.bounds[0],
                       geom_m.bounds[3] - geom_m.bounds[1]) or 1.0
        slope_pct = elev_range / diameter * 100.0

    return {"slope_pct": round(slope_pct, 1), "elev_range_m": round(elev_range, 1)}


def lots_slopes(lots_4326: gpd.GeoDataFrame, mcrs) -> list[dict]:
    """Calcula declividade para todos os lotes em UMA leva de chamadas batched."""
    lots_m = lots_4326.to_crs(mcrs)
    per_lot_pts: list[list[tuple[float, float]]] = []
    all_pts: list[tuple[float, float]] = []
    for geom4326, geom_m in zip(lots_4326.geometry.values, lots_m.geometry.values):
        pts = sample_points(geom4326, geom_m)
        per_lot_pts.append(pts)
        all_pts.extend(pts)

    elevations = fetch_elevations(all_pts)
    out = []
    for geom4326, geom_m, pts in zip(lots_4326.geometry.values, lots_m.geometry.values, per_lot_pts):
        out.append(slope_metrics(geom4326, geom_m, mcrs, elevations, pts))
    return out
