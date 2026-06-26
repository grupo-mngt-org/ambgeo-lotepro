"""I/O vetorial e exportação de leads.

Leitura de SHP(.zip)/KML/GeoJSON via pyogrio (GDAL embutido) — sem fiona.
Exportação para CSV, Excel (.xlsx) e KML.
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import simplekml

from . import geo

VECTOR_EXTS = {".geojson", ".json", ".kml", ".zip", ".shp", ".gpkg"}


def read_vector(filename: str, content: bytes) -> gpd.GeoDataFrame:
    """Lê bytes de um vetor enviado e devolve GeoDataFrame em EPSG:4326."""
    suffix = Path(filename).suffix.lower()
    if suffix not in VECTOR_EXTS:
        raise ValueError(
            f"Formato não suportado: {suffix!r}. Use GeoJSON, KML ou Shapefile (.zip)."
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        if suffix == ".zip":
            gdf = gpd.read_file(f"zip://{tmp_path}")
        else:
            gdf = gpd.read_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if gdf.empty:
        raise ValueError("Arquivo sem feições válidas.")
    if gdf.crs is None:
        gdf = gdf.set_crs(geo.WGS84)
    return gdf.to_crs(geo.WGS84)


def to_geojson_dict(gdf: gpd.GeoDataFrame) -> dict:
    """GeoDataFrame -> dict GeoJSON (para resposta da API)."""
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    import json
    return json.loads(gdf.to_json())


def _attr_frame(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    cols = [c for c in gdf.columns if c != "geometry"]
    return pd.DataFrame(gdf[cols])


def export_csv(gdf: gpd.GeoDataFrame) -> bytes:
    return _attr_frame(gdf).to_csv(index=False).encode("utf-8-sig")


def export_xlsx(gdf: gpd.GeoDataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _attr_frame(gdf).to_excel(writer, index=False, sheet_name="leads")
    return buf.getvalue()


def export_kml(gdf: gpd.GeoDataFrame) -> bytes:
    """Exporta polígonos para KML com nome e descrição (uso em campo)."""
    kml = simplekml.Kml()
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        name = f"Lote {row.get('id', '')} — {row.get('area_m2', '')} m²"
        score_line = ""
        if row.get("score") is not None and "score" in gdf.columns:
            score_line = (f"Score: {row.get('score', '')} ({row.get('grade', '')})\n"
                          f"Declividade: {row.get('slope_pct', 'N/D')}%\n"
                          f"Testada: {row.get('frontage_m', 'N/D')} m\n")
        crm_line = ""
        if row.get("matricula"):
            crm_line = (f"Matrícula: {row.get('matricula', '')}\n"
                        f"Proprietário: {row.get('proprietario', '')}\n"
                        f"Status: {row.get('status', '')}\n")
        desc = (
            f"Área: {row.get('area_m2', '')} m²\n"
            f"Ocupação: {float(row.get('occupation', 0)) * 100:.1f}%\n"
            + score_line + crm_line +
            f"Zoneamento: {row.get('zoning', '')}\n"
            f"Street View: {row.get('street_view', '')}"
        )
        geoms = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for part in geoms:
            poly = kml.newpolygon(name=name, description=desc)
            poly.outerboundaryis = list(part.exterior.coords)
            for interior in part.interiors:
                poly.innerboundaryis = list(interior.coords)
    return kml.kml().encode("utf-8")
