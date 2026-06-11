"""Microsoft Building Footprints (GlobalMLBuildingFootprints) — sem chave.

Cobertura de edificações MUITO superior ao OSM no Brasil (footprints extraídos
de imagem de satélite por ML). É a fonte que elimina o falso-positivo clássico
de "quadra cheia de casas aparecendo como terreno vazio" quando o OSM não tem
as edificações mapeadas.

Distribuição oficial: tiles por quadkey (zoom 9 ≈ 78 km) listados em um índice
CSV público (~7 MB). Cada tile é um .csv.gz de GeoJSON por linha, parseado via
DuckDB (rápido) e cacheado em disco como FlatGeobuf — leituras seguintes filtram
por bbox via índice espacial (pyogrio), sem nova rede.

Ref: https://github.com/microsoft/GlobalMLBuildingFootprints
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely

from .. import config
from . import geo

LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
HTTP_HEADERS = {"User-Agent": "LotePro/0.2 (+devs@grupomngt.com.br)"}
ZOOM = 9


def _cache_dir() -> Path:
    d = config.DATA_DIR / "cache" / "msbuildings"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------- Quadkeys ------------------------------------
def _tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    """(x, y) do tile Web Mercator que contém o ponto."""
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _quadkey(x: int, y: int, z: int) -> str:
    qk = []
    for i in range(z, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        qk.append(str(digit))
    return "".join(qk)


def bbox_quadkeys(xmin: float, ymin: float, xmax: float, ymax: float, z: int = ZOOM) -> set[str]:
    """Quadkeys (zoom z) que cobrem o bbox lon/lat."""
    x0, y0 = _tile_xy(ymax, xmin, z)   # canto NW
    x1, y1 = _tile_xy(ymin, xmax, z)   # canto SE
    return {_quadkey(x, y, z) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


# --------------------------- Índice de tiles --------------------------------
def _load_links() -> pd.DataFrame:
    """Índice quadkey → URLs. Baixado uma vez e cacheado em disco."""
    path = _cache_dir() / "dataset-links.csv"
    if not path.is_file():
        resp = requests.get(LINKS_URL, headers=HTTP_HEADERS, timeout=(10, 120))
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return pd.read_csv(path, dtype=str)


def _urls_for_quadkey(links: pd.DataFrame, qk: str) -> list[str]:
    """URLs cujo quadkey cobre (prefixo) ou está contido no quadkey pedido."""
    col = links["QuadKey"].fillna("")
    mask = col.map(lambda q: q.startswith(qk) or qk.startswith(q)) if len(col) else col
    return list(links.loc[mask, "Url"].unique())


# ------------------------- Download + parse de tile -------------------------
def _parse_geojsonl_gz(path: Path) -> gpd.GeoDataFrame:
    """Parseia um .csv.gz de GeoJSON-por-linha via DuckDB (C++, rápido)."""
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        q = f"""
            SELECT ST_AsWKB(ST_GeomFromGeoJSON(CAST(geometry AS VARCHAR))) AS wkb
            FROM read_json('{path.as_posix()}', format='newline_delimited',
                           compression='gzip', columns={{'geometry': 'JSON'}})
        """
        rows = con.execute(q).fetchall()
    finally:
        con.close()
    geoms = shapely.from_wkb([bytes(r[0]) for r in rows if r[0] is not None])
    return gpd.GeoDataFrame(geometry=[g for g in geoms if g is not None], crs=geo.WGS84)


def _tile_path(qk: str) -> Path:
    return _cache_dir() / f"{qk}.fgb"


def _ensure_tile(qk: str, links: pd.DataFrame, progress=None) -> Path | None:
    """Garante o tile em cache (.fgb). None se o dataset não cobre o quadkey."""
    path = _tile_path(qk)
    if path.is_file():
        return path
    urls = _urls_for_quadkey(links, qk)
    if not urls:
        return None

    parts = []
    for n, url in enumerate(urls, 1):
        if progress:
            progress(f"Baixando footprints Microsoft — tile {qk} ({n}/{len(urls)})…")
        with tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with requests.get(url, headers=HTTP_HEADERS, stream=True,
                              timeout=(10, 600)) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    tmp.write(chunk)
        try:
            if progress:
                progress(f"Processando footprints do tile {qk} ({n}/{len(urls)})…")
            parts.append(_parse_geojsonl_gz(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)

    gdf = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), geometry="geometry", crs=geo.WGS84
    ) if parts else gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)
    if gdf.empty:
        return None
    gdf.to_file(path, driver="FlatGeobuf")
    return path


def fetch_buildings_bbox(xmin: float, ymin: float, xmax: float, ymax: float,
                         progress=None) -> gpd.GeoDataFrame:
    """Footprints Microsoft no bbox (EPSG:4326). Cache local por tile; somente
    o primeiro acesso a uma região baixa dados (dezenas de MB por tile)."""
    links = _load_links()
    frames = []
    for qk in sorted(bbox_quadkeys(xmin, ymin, xmax, ymax)):
        path = _ensure_tile(qk, links, progress)
        if path is None:
            continue
        part = gpd.read_file(path, bbox=(xmin, ymin, xmax, ymax))
        if not part.empty:
            frames.append(part[["geometry"]])
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)
    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True),
                           geometry="geometry", crs=geo.WGS84)
    out = out[out.geometry.type.isin(["Polygon", "MultiPolygon"])]
    return out.reset_index(drop=True)
