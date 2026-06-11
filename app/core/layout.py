"""Estudo de implantação paramétrico (estilo TestFit) para condomínio de casas.

Dado o polígono de um terreno e parâmetros urbanísticos (lote-padrão, recuos,
via interna…), gera em tempo real a implantação: fileiras de lotes servidas
por vias internas, casa posicionada em cada lote respeitando recuos, e as
métricas de viabilidade (nº de casas, densidade, % de aproveitamento).

Geometria 100% local (Shapely, CRS métrico) — rápido o bastante para o
frontend re-gerar a cada movimento de slider.

Convenções:
  - Fileiras de lotes são dispostas perpendicularmente ao eixo escolhido
    (automático = maior lado do retângulo envolvente mínimo, ajustável).
  - Módulo viário clássico: fileira ↑frente | via | fileira ↓frente, com
    fundos de lote encostados entre módulos (double-loaded).
  - Sobras que não comportam um lote inteiro viram área verde/comum.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import geopandas as gpd
from shapely import affinity, union_all
from shapely.geometry import MultiPolygon, Polygon, box, shape

from . import geo

MAX_SITE_M2 = 3_000_000.0   # 300 ha — acima disso o estudo deixa de ser interativo
_COVERAGE_MIN = 0.98        # fração da célula dentro da área útil p/ virar lote
_EPS = 1e-6


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(v):
        return default
    return max(lo, min(hi, v))


@dataclass
class LayoutParams:
    lot_width_m: float = 8.0        # testada do lote-padrão
    lot_depth_m: float = 20.0       # profundidade do lote-padrão
    house_width_m: float = 6.0      # largura da casa
    house_depth_m: float = 10.0     # profundidade da casa
    front_setback_m: float = 3.0    # recuo frontal
    side_setback_m: float = 1.5     # recuo lateral
    back_setback_m: float = 2.0     # recuo de fundos
    road_width_m: float = 8.0       # caixa da via interna
    perimeter_margin_m: float = 2.0 # faixa no perímetro (muro/verde)
    angle_deg: float | None = None  # None = automático (maior lado do terreno)
    max_units: int = 3000

    @classmethod
    def from_dict(cls, data: dict | None) -> "LayoutParams":
        d = data or {}
        angle = d.get("angle_deg")
        try:
            angle = None if angle is None or angle == "" else float(angle)
        except (TypeError, ValueError):
            angle = None
        return cls(
            lot_width_m=_clamp(d.get("lot_width_m"), 3, 50, 8.0),
            lot_depth_m=_clamp(d.get("lot_depth_m"), 5, 100, 20.0),
            house_width_m=_clamp(d.get("house_width_m"), 2, 40, 6.0),
            house_depth_m=_clamp(d.get("house_depth_m"), 2, 60, 10.0),
            front_setback_m=_clamp(d.get("front_setback_m"), 0, 15, 3.0),
            side_setback_m=_clamp(d.get("side_setback_m"), 0, 15, 1.5),
            back_setback_m=_clamp(d.get("back_setback_m"), 0, 15, 2.0),
            road_width_m=_clamp(d.get("road_width_m"), 4, 30, 8.0),
            perimeter_margin_m=_clamp(d.get("perimeter_margin_m"), 0, 30, 2.0),
            angle_deg=angle,
        )


def _auto_angle(site_m: Polygon) -> float:
    """Ângulo (graus) do maior lado do retângulo envolvente mínimo."""
    rect = site_m.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return 0.0
    coords = list(rect.exterior.coords)
    best_len, best_angle = -1.0, 0.0
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    # normaliza para (-90, 90]
    while best_angle <= -90:
        best_angle += 180
    while best_angle > 90:
        best_angle -= 180
    return round(best_angle, 1)


def _bands(ymin: float, ymax: float, depth: float, road: float):
    """Faixas horizontais do módulo viário: [(y0, y1, frente), ...] e vias.

    Padrão double-loaded: fileira (frente p/ cima) | via | fileira (frente
    p/ baixo); módulos consecutivos encostam fundos com fundos.
    """
    rows, roads = [], []
    y = ymin
    while y + depth <= ymax + _EPS:
        rows.append((y, y + depth, "top"))
        yr = y + depth
        if yr + road + depth <= ymax + _EPS:
            roads.append((yr, yr + road))
            rows.append((yr + road, yr + road + depth, "bottom"))
            y = yr + road + depth
        else:
            y = yr
            break
    # centraliza o conjunto na altura disponível
    used = (rows[-1][1] - ymin) if rows else 0.0
    off = (ymax - ymin - used) / 2.0
    rows = [(y0 + off, y1 + off, f) for y0, y1, f in rows]
    roads = [(y0 + off, y1 + off) for y0, y1 in roads]
    return rows, roads


def _house_rect(cell, front: str, p: LayoutParams) -> Polygon | None:
    """Retângulo da casa dentro do lote, respeitando recuos e a frente."""
    x0, y0, x1, y1 = cell.bounds
    hw = min(p.house_width_m, (x1 - x0) - 2 * p.side_setback_m)
    hd = min(p.house_depth_m, (y1 - y0) - p.front_setback_m - p.back_setback_m)
    if hw < 2.0 or hd < 2.0:
        return None
    cx = (x0 + x1) / 2.0
    if front == "top":      # frente (via) é a borda superior do lote
        ya = y1 - p.front_setback_m - hd
        yb = y1 - p.front_setback_m
    else:                   # frente é a borda inferior
        ya = y0 + p.front_setback_m
        yb = y0 + p.front_setback_m + hd
    return box(cx - hw / 2.0, ya, cx + hw / 2.0, yb)


def generate(geometry: dict, params: LayoutParams) -> dict:
    """Gera a implantação para um polígono GeoJSON (EPSG:4326)."""
    try:
        shp = shape(geometry)
    except Exception as exc:
        raise ValueError(f"Geometria inválida: {exc}") from exc
    if isinstance(shp, MultiPolygon):
        shp = max(shp.geoms, key=lambda g: g.area)
    if shp.geom_type != "Polygon" or shp.is_empty:
        raise ValueError("Envie um polígono (o terreno escolhido).")

    g4326 = gpd.GeoDataFrame(geometry=[shp], crs=geo.WGS84)
    mcrs = g4326.estimate_utm_crs()
    site = g4326.to_crs(mcrs).geometry.iloc[0]
    site_area = float(site.area)
    if site_area > MAX_SITE_M2:
        raise ValueError(
            f"Terreno de {site_area / 1e4:,.0f} ha — o estudo interativo é "
            "limitado a 300 ha. Use o perfil 'loteamento' para glebas maiores.")

    usable = site.buffer(-params.perimeter_margin_m) if params.perimeter_margin_m > 0 else site
    empty_stats = {
        "units": 0, "site_area_m2": round(site_area, 1), "lots_area_m2": 0.0,
        "avg_lot_m2": 0.0, "house_area_m2": 0.0, "total_built_m2": 0.0,
        "roads_area_m2": 0.0, "green_area_m2": round(site_area, 1),
        "density_units_ha": 0.0, "efficiency_pct": 0.0, "coverage_pct": 0.0,
        "truncated": False,
    }
    if usable.is_empty:
        return {"stats": empty_stats, "angle_used": 0.0,
                "features": {"type": "FeatureCollection", "features": []}}

    angle = params.angle_deg if params.angle_deg is not None else _auto_angle(site)
    origin = (site.centroid.x, site.centroid.y)
    w = affinity.rotate(usable, -angle, origin=origin)

    xmin, ymin, xmax, ymax = w.bounds
    rows, road_bands = _bands(ymin, ymax, params.lot_depth_m, params.road_width_m)

    lots: list[tuple[Polygon, str]] = []
    truncated = False
    span = xmax - xmin
    n_cells = int(span // params.lot_width_m)
    off_x = (span - n_cells * params.lot_width_m) / 2.0
    for y0, y1, front in rows:
        for k in range(n_cells):
            x = xmin + off_x + k * params.lot_width_m
            cell = box(x, y0, x + params.lot_width_m, y1)
            if cell.intersection(w).area >= cell.area * _COVERAGE_MIN:
                lots.append((cell, front))
                if len(lots) >= params.max_units:
                    truncated = True
                    break
        if truncated:
            break

    roads_geom = union_all([
        box(xmin - 1.0, y0, xmax + 1.0, y1).intersection(w)
        for y0, y1 in road_bands
    ]) if road_bands else Polygon()

    records = []
    lots_area = 0.0
    house_area_each = 0.0
    for i, (cell, front) in enumerate(lots, start=1):
        lots_area += cell.area
        records.append({"kind": "lot", "unit": i,
                        "lot_area_m2": round(cell.area, 1), "geometry": cell})
        house = _house_rect(cell, front, params)
        if house is not None:
            house_area_each = house.area
            records.append({"kind": "house", "unit": i,
                            "lot_area_m2": round(cell.area, 1), "geometry": house})

    site_rot = affinity.rotate(site, -angle, origin=origin)
    green = site_rot.difference(union_all([c for c, _ in lots])).difference(roads_geom)
    if not roads_geom.is_empty:
        records.append({"kind": "road", "unit": None, "lot_area_m2": None,
                        "geometry": roads_geom})
    if not green.is_empty:
        records.append({"kind": "green", "unit": None, "lot_area_m2": None,
                        "geometry": green})

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=mcrs)
    gdf["geometry"] = gdf.geometry.apply(
        lambda g: affinity.rotate(g, angle, origin=origin))
    gdf = gdf.to_crs(geo.WGS84)

    units = len(lots)
    total_built = house_area_each * units
    stats = {
        "units": units,
        "site_area_m2": round(site_area, 1),
        "lots_area_m2": round(lots_area, 1),
        "avg_lot_m2": round(lots_area / units, 1) if units else 0.0,
        "house_area_m2": round(house_area_each, 1),
        "total_built_m2": round(total_built, 1),
        "roads_area_m2": round(float(roads_geom.area), 1),
        "green_area_m2": round(float(green.area), 1),
        "density_units_ha": round(units / (site_area / 10_000.0), 1) if site_area else 0.0,
        "efficiency_pct": round(lots_area / site_area * 100.0, 1) if site_area else 0.0,
        "coverage_pct": round(total_built / site_area * 100.0, 1) if site_area else 0.0,
        "truncated": truncated,
    }

    from . import io as _io  # import tardio: evita ciclo em testes unitários
    return {"stats": stats, "angle_used": round(float(angle), 1),
            "features": _io.to_geojson_dict(gdf)}
