"""Gera dados de exemplo (GeoJSON) para demonstrar o Lote Pro ponta a ponta.

Cria, em torno de um ponto urbano em Goiânia/GO:
  - aoi.geojson       um quarteirão (~ 360 x 270 m)
  - buildings.geojson algumas edificações dentro do quarteirão
  - zoning.geojson    duas zonas (ZR1 / ZCS) cobrindo a AOI

Uso:  python scripts/make_sample.py
Saída: data/samples/
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, box

OUT = Path(__file__).resolve().parent.parent / "data" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

# Centro aproximado (Goiânia/GO) e conversões grau<->metro nessa latitude.
LON0, LAT0 = -49.2550, -16.6790
M_PER_DEG_LON = 106_600.0
M_PER_DEG_LAT = 110_570.0


def m_to_deg(dx_m: float, dy_m: float) -> tuple[float, float]:
    return dx_m / M_PER_DEG_LON, dy_m / M_PER_DEG_LAT


def rect(cx_m: float, cy_m: float, w_m: float, h_m: float) -> Polygon:
    """Retângulo (em metros relativos ao centro) convertido para lon/lat."""
    dlon_w, dlat_h = m_to_deg(w_m / 2, h_m / 2)
    clon, clat = m_to_deg(cx_m, cy_m)
    return box(LON0 + clon - dlon_w, LAT0 + clat - dlat_h,
               LON0 + clon + dlon_w, LAT0 + clat + dlat_h)


def main() -> None:
    # AOI: quarteirão de 360 x 270 m centrado na origem.
    aoi = gpd.GeoDataFrame({"name": ["Quarteirão demo"]},
                           geometry=[rect(0, 0, 360, 270)], crs="EPSG:4326")
    aoi.to_file(OUT / "aoi.geojson", driver="GeoJSON")

    # Edificações: alguns lotes ocupados, um galpão pequeno (deve ser tolerado).
    buildings = gpd.GeoDataFrame(
        {"name": ["Casa A", "Prédio B", "Galpão pequeno", "Casa C"]},
        geometry=[
            rect(-120, 60, 40, 35),    # ocupa bem seu lote
            rect(110, 70, 70, 60),     # prédio grande
            rect(20, -80, 12, 10),     # construção pequena (~120 m²)
            rect(-110, -70, 30, 28),
        ],
        crs="EPSG:4326",
    )
    buildings.to_file(OUT / "buildings.geojson", driver="GeoJSON")

    # Zoneamento: metade oeste ZR1, metade leste ZCS.
    zoning = gpd.GeoDataFrame(
        {"zoning": ["ZR1 - Residencial", "ZCS - Comércio e Serviços"]},
        geometry=[rect(-90, 0, 180, 270), rect(90, 0, 180, 270)],
        crs="EPSG:4326",
    )
    zoning.to_file(OUT / "zoning.geojson", driver="GeoJSON")

    print(f"Amostras geradas em: {OUT}")
    for f in ("aoi", "buildings", "zoning"):
        print(f"  - {f}.geojson")


if __name__ == "__main__":
    main()
