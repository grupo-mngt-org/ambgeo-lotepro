"""Contrato do motor de detecção (Strategy pattern).

Cada provider recebe a AOI (e, quando houver, footprints de edificações e
zoneamento) e devolve um GeoDataFrame de candidatos a terreno vazio, já com
as colunas padronizadas:

    area_m2, occupation, potential, zoning, lat, lon, street_view

Todos os GeoDataFrames trafegam em EPSG:4326.
"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd


@dataclass
class DetectionParams:
    """Parâmetros de negócio da detecção (RF03), todos editáveis.

    provider: "footprint" | "gee" | "dynamic_world"
    mode:
      footprint → "gaps" (default) | "parcels"
      gee       → "dw"  (Dynamic World, default p/ dynamic_world) | "spectral" (Sentinel-2)

    Filtros anti-falso-positivo (modo gaps):
      building_buffer_m — dilata cada footprint antes de subtrair, eliminando
        frestas entre casas vizinhas (recuos/beirais) que não são lotes.
      min_width_m — abertura morfológica: descarta vazios mais estreitos que
        isso (vielas, corredores laterais, sobras de fundo de lote).
      require_frontage — exige que o vazio encoste na divisa da quadra
        (frente para via). Vazios internos = fundos de quintal, não lotes.
      max_area_m2 — teto de área (modo cidade: corta "quadras" rurais gigantes).
    """
    provider: str = "footprint"
    mode: str = "gaps"
    min_area_m2: float = 500.0       # RF03: área mínima
    max_occupation_ratio: float = 0.15  # RF03: ocupação máxima (15%)
    building_buffer_m: float = 1.5
    min_width_m: float = 6.0
    require_frontage: bool = True
    max_area_m2: float | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "DetectionParams":
        data = data or {}
        max_area = data.get("max_area_m2")
        return cls(
            provider=str(data.get("provider", "footprint")),
            mode=str(data.get("mode", "gaps")),
            min_area_m2=float(data.get("min_area_m2", 500.0)),
            max_occupation_ratio=float(data.get("max_occupation_ratio", 0.15)),
            building_buffer_m=float(data.get("building_buffer_m", 1.5)),
            min_width_m=float(data.get("min_width_m", 6.0)),
            require_frontage=bool(data.get("require_frontage", True)),
            max_area_m2=float(max_area) if max_area else None,
        )


class DetectionProvider:
    """Interface base. Implementações devolvem candidatos em EPSG:4326."""

    name: str = "base"

    def detect(
        self,
        aoi: gpd.GeoDataFrame,
        buildings: gpd.GeoDataFrame | None,
        zoning: gpd.GeoDataFrame | None,
        params: DetectionParams,
    ) -> gpd.GeoDataFrame:  # pragma: no cover - interface
        raise NotImplementedError


def get_provider(name: str) -> DetectionProvider:
    """Fábrica de providers.

    Aliases:
      "dynamic_world" → GEEProvider com mode="dw" (Dynamic World).
    """
    name = (name or "footprint").lower()
    if name == "footprint":
        from .footprint import FootprintProvider
        return FootprintProvider()
    if name in ("gee", "dynamic_world"):
        from .gee import GEEProvider
        return GEEProvider()
    raise ValueError(
        f"Provider desconhecido: {name!r}. Use 'footprint', 'gee' ou 'dynamic_world'."
    )
