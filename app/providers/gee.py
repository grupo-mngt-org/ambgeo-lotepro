"""Provider opcional: Google Earth Engine.

Dois modos de detecção (selecionar via params.mode):

  "dw" — Dynamic World (GOOGLE/DYNAMICWORLD/V1)
      Classifica o uso do solo com imagens quase semanais (resolução 10 m).
      Usa bandas de PROBABILIDADE (bare, grass, built) — não apenas a classe
      moda — alinhado com a abordagem de limiares espectrais da AmbGEO.
      Captura tanto solo exposto (bare > 0.25) quanto lotes com vegetação
      espontânea (grass > 0.40), excluindo pixeis com assinatura de edificação
      (built >= 0.30). Janela: últimos 6 meses (RNF04).
      Ref: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1

  "spectral" — Sentinel-2 SR + NDVI/NDBI  (default quando mode não é "dw")
      Calcula índices espectrais para separar solo exposto de vegetação e
      construções. Mesmos 6 meses de janela.

Provider alias "dynamic_world" no get_provider() → provider GEE com mode="dw".
Combinação recomendada: provider="dynamic_world" + buildings_source="google"
(Google Open Buildings via GEE) → máxima cobertura e menor falso-positivo.

Habilitar:
  1. pip install earthengine-api
  2. GEE_SERVICE_ACCOUNT + GEE_KEY_FILE, ou `earthengine authenticate`.
  3. Chamar detect(provider="gee", mode="dw"|"spectral", ...).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import geopandas as gpd
from shapely.geometry import shape

from ..core import geo
from ..core.pipeline import qualify
from .base import DetectionParams, DetectionProvider

# Dynamic World: limiares de probabilidade por banda (0–1)
# Calibrados para contexto urbano brasileiro (abordagem AmbGEO de limiares espectrais).
_DW_T_BARE = 0.25   # probabilidade mínima de solo exposto para ser candidato
_DW_T_GRASS = 0.40  # probabilidade mínima de grama/vegetação rasteira (lotes abandonados)
_DW_T_BUILT = 0.30  # probabilidade máxima de construído — acima disso é excluído

# Sentinel-2: limiares conservadores para falso-positivo < 10% (RNF02)
_T_NDVI = 0.2      # abaixo = pouca vegetação
_T_NDBI = 0.0      # abaixo = não é telhado/concreto


class GEEProvider(DetectionProvider):
    name = "gee"

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------
    def _init_ee(self):
        try:
            import ee  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Provider 'gee' indisponível: instale com `pip install earthengine-api`."
            ) from exc

        sa = os.getenv("GEE_SERVICE_ACCOUNT")
        key = os.getenv("GEE_KEY_FILE")
        try:
            if sa and key:
                ee.Initialize(ee.ServiceAccountCredentials(sa, key))
            else:
                ee.Initialize()
        except Exception as exc:
            raise RuntimeError(
                "Falha ao autenticar no Google Earth Engine. Configure "
                "GEE_SERVICE_ACCOUNT + GEE_KEY_FILE ou rode `earthengine authenticate`."
            ) from exc
        return ee

    def _aoi_to_region(self, ee, aoi_gdf: gpd.GeoDataFrame):
        """Converte AOI GeoDataFrame em ee.Geometry (MultiPolygon)."""
        aoi_4326 = aoi_gdf.to_crs(geo.WGS84) if aoi_gdf.crs else aoi_gdf.set_crs(geo.WGS84)
        geojson = json.loads(aoi_4326.to_json())
        coords = [f["geometry"]["coordinates"] for f in geojson.get("features", [])]
        if not coords:
            raise ValueError("AOI vazia: nenhuma feição encontrada.")
        return ee.Geometry.MultiPolygon(coords)

    @staticmethod
    def _date_range() -> tuple[str, str]:
        end = date.today()
        start = end - timedelta(days=180)  # RNF04: últimos 6 meses
        return str(start), str(end)

    @staticmethod
    def _fc_to_gdf(fc_info: dict) -> gpd.GeoDataFrame:
        """Converte resultado de FeatureCollection.getInfo() em GeoDataFrame."""
        features = fc_info.get("features", [])
        geoms = []
        for feat in features:
            g = feat.get("geometry")
            if g:
                try:
                    geoms.append(shape(g))
                except Exception:
                    continue
        polys = [g for g in geoms if not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")]
        return gpd.GeoDataFrame(geometry=polys, crs=geo.WGS84)

    # ------------------------------------------------------------------
    # Modo DW: Dynamic World
    # ------------------------------------------------------------------
    def _detect_dw(self, ee, region, aoi, buildings, zoning, params: DetectionParams) -> gpd.GeoDataFrame:
        """Identifica terrenos vazios via Dynamic World usando bandas de probabilidade.

        Pipeline:
          1. Filtra GOOGLE/DYNAMICWORLD/V1 por região e data (últimos 6 meses).
          2. Calcula probabilidade MÉDIA por banda (bare, grass, built) — não apenas
             a classe moda. Isso captura tanto solo exposto quanto lotes com
             vegetação espontânea, seguindo a abordagem de limiares da AmbGEO.
          3. Máscara candidatos: (bare > _DW_T_BARE OU grass > _DW_T_GRASS)
                                  E built < _DW_T_BUILT
          4. Clip à região de interesse antes de vetorizar (bordas limpas).
          5. Vetoriza e passa para qualify().
        """
        start, end = self._date_range()

        dw_col = (
            ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            .filterBounds(region)
            .filterDate(start, end)
            .select(["bare", "grass", "built"])
        )

        count = dw_col.size().getInfo()
        if count == 0:
            raise ValueError(
                "Sem imagens Dynamic World para esta área/período. "
                "Verifique as credenciais GEE ou tente uma área maior."
            )

        # Probabilidade média de cada classe ao longo do período
        bare_prob = dw_col.select("bare").mean()
        grass_prob = dw_col.select("grass").mean()
        built_prob = dw_col.select("built").mean()

        # Candidatos: (solo exposto OU vegetação espontânea) E sem assinatura de edificação
        candidate_mask = (
            bare_prob.gt(_DW_T_BARE).Or(grass_prob.gt(_DW_T_GRASS))
            .And(built_prob.lt(_DW_T_BUILT))
        )

        vectors = (
            candidate_mask.selfMask()
            .clip(region)
            .reduceToVectors(
                geometry=region,
                scale=10,
                maxPixels=1_500_000,
                geometryType="polygon",
                eightConnected=False,
                crs="EPSG:4326",
                bestEffort=True,
            )
        )

        try:
            fc_info = vectors.getInfo()
        except Exception as exc:
            raise ValueError(f"Falha ao vetorizar Dynamic World: {exc}") from exc

        candidates = self._fc_to_gdf(fc_info)
        if candidates.empty:
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=geo.WGS84)
        return qualify(candidates, buildings, zoning, params)

    # ------------------------------------------------------------------
    # Modo Spectral: Sentinel-2 NDVI/NDBI
    # ------------------------------------------------------------------
    def _detect_spectral(self, ee, region, aoi, buildings, zoning, params: DetectionParams) -> gpd.GeoDataFrame:
        """Identifica solo exposto via NDVI/NDBI sobre Sentinel-2 SR.

        Pipeline:
          1. Sentinel-2 SR dos últimos 6 meses, <20% nuvem.
          2. Mediana da coleção (composto sem nuvens).
          3. NDVI < T e NDBI < T → solo exposto.
          4. Vetoriza e passa para qualify().
        """
        start, end = self._date_range()

        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        )

        count = col.size().getInfo()
        if count == 0:
            raise ValueError(
                "Sem imagens Sentinel-2 para esta área/período. "
                "Tente uma área maior ou aumente a tolerância de nuvem."
            )

        img = col.median()
        ndvi = img.normalizedDifference(["B8", "B4"])   # vegetação
        ndbi = img.normalizedDifference(["B11", "B8"])  # construído

        # Solo exposto = sem vegetação densa E sem assinatura de telhado/concreto
        vazio = ndbi.lt(_T_NDBI).And(ndvi.lt(_T_NDVI))

        vectors = (
            vazio.selfMask()
            .clip(region)
            .reduceToVectors(
                geometry=region,
                scale=10,
                maxPixels=1_500_000,
                geometryType="polygon",
                eightConnected=False,
                crs="EPSG:4326",
                bestEffort=True,
            )
        )

        try:
            fc_info = vectors.getInfo()
        except Exception as exc:
            raise ValueError(f"Falha ao vetorizar Sentinel-2: {exc}") from exc

        candidates = self._fc_to_gdf(fc_info)
        if candidates.empty:
            return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=geo.WGS84)
        return qualify(candidates, buildings, zoning, params)

    # ------------------------------------------------------------------
    # Entrypoint
    # ------------------------------------------------------------------
    def detect(self, aoi, buildings, zoning, params: DetectionParams) -> gpd.GeoDataFrame:
        if aoi is None or aoi.empty:
            raise ValueError("AOI vazia: envie a área de interesse antes de detectar.")

        ee = self._init_ee()
        region = self._aoi_to_region(ee, aoi)

        # Provider alias "dynamic_world" ou mode explícito "dw"
        use_dw = (params.mode == "dw") or (params.provider == "dynamic_world")
        if use_dw:
            return self._detect_dw(ee, region, aoi, buildings, zoning, params)
        return self._detect_spectral(ee, region, aoi, buildings, zoning, params)
