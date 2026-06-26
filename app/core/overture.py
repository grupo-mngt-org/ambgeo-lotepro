"""Fonte alternativa de footprints REAIS: Overture Maps (open data).

O dataset de buildings da Overture funde OSM + Google + Microsoft + Esri, com
cobertura MUITO superior ao OSM puro (ex.: ~2.100 edificações onde o OSM tem ~40
no mesmo quarteirão). É consultado por bounding box direto do parquet público
via DuckDB (sem chave, região us-west-2).

Trade-off: a varredura remota é lenta (alguns minutos no primeiro acesso). Por
isso é OPCIONAL — o OSM segue como fonte default e rápida. Os footprints baixados
são persistidos na camada do projeto, então a detecção subsequente é instantânea.
"""
from __future__ import annotations

import geopandas as gpd
from shapely import wkb

from . import geo

# Release público corrente da Overture (atualizar conforme novos releases).
OVERTURE_RELEASE = "2026-05-20.0"
S3_PATH = (
    f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    "/theme=buildings/type=building/*"
)


def fetch_buildings_bbox(xmin: float, ymin: float, xmax: float, ymax: float) -> gpd.GeoDataFrame:
    """Baixa footprints da Overture dentro do bbox (lon/lat, EPSG:4326)."""
    import duckdb  # import tardio: dependência só usada neste provider

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    query = f"""
        SELECT ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{S3_PATH}', filename=true, hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {xmin} AND {xmax}
          AND bbox.ymin BETWEEN {ymin} AND {ymax}
    """
    try:
        rows = con.execute(query).fetchall()
    except Exception as exc:
        raise ValueError(
            "Falha ao consultar a Overture Maps. Verifique a conexão e tente novamente."
        ) from exc
    finally:
        con.close()

    geoms = [wkb.loads(bytes(r[0])) for r in rows if r[0] is not None]
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)
    return gpd.GeoDataFrame(geometry=geoms, crs=geo.WGS84)
