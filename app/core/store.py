"""Persistência (Fase 2 — Opção A).

- **projects / lots (results) / CRM** → Postgres (via SQLAlchemy).
- **camadas de INPUT** (aoi | buildings | zoning | exclusions) → arquivo `.gpkg`
  em data/projects/<id>/ (lidas só durante a detecção; grandes; não precisam ir
  ao banco).

A superfície pública (create_project/list_projects/get_meta/update_meta/
save_layer/load_layer/get_lots_info/set_lot_info) é preservada — `routes.py`,
`analysis.py` e `citywide.py` não mudam.

O `id` do lote exposto na API passa a ser o **PK estável** de `lots` (não mais o
índice do GeoPackage). `save_layer("results", gdf)` reescreve `gdf["id"]` in-place
com esses ids, então os payloads montados logo após já saem com ids estáveis.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely import wkb
from sqlalchemy import delete, select

from .. import config
from ..database import SessionLocal
from ..models import Lot, LotCrm, Project

LAYER_KINDS = {"aoi", "buildings", "zoning", "results", "exclusions"}
FILE_LAYERS = {"aoi", "buildings", "zoning", "exclusions"}  # results vai pro banco

# Colunas do lote (results) ↔ campos do model Lot.
_FLOAT_COLS = ("area_m2", "occupation", "lat", "lon", "score",
               "slope_pct", "elev_range_m", "frontage_m", "compactness")
_TEXT_COLS = ("potential", "color", "zoning", "street_view", "grade",
              "flags", "score_breakdown")
_LOT_COLS = _FLOAT_COLS + _TEXT_COLS
# Colunas de enriquecimento: omitidas do gdf reconstruído se TODAS forem nulas
# (mantém o payload fiel ao detect não-enriquecido, que nem cria essas colunas).
_ENRICH_COLS = ("score", "grade", "slope_pct", "elev_range_m", "frontage_m",
                "compactness", "flags", "score_breakdown")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proj_dir(project_id: str) -> Path:
    return config.PROJECTS_DIR / project_id


def _meta(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_detect": p.last_detect,
    }


# --------------------------------------------------------------------------
# Projetos
# --------------------------------------------------------------------------
def create_project(name: str) -> dict:
    pid = uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        p = Project(id=pid, name=name or pid)
        db.add(p)
        db.commit()
        db.refresh(p)
        return _meta(p)


def list_projects() -> list[dict]:
    with SessionLocal() as db:
        rows = db.execute(select(Project).order_by(Project.created_at)).scalars().all()
        return [_meta(p) for p in rows]


def get_meta(project_id: str) -> dict:
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise KeyError(f"Projeto não encontrado: {project_id}")
        return _meta(p)


def update_meta(project_id: str, **fields) -> dict:
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if p is None:
            raise KeyError(f"Projeto não encontrado: {project_id}")
        for k, v in fields.items():
            if k == "id":
                continue
            if hasattr(p, k):
                setattr(p, k, v)
        db.commit()
        db.refresh(p)
        return _meta(p)


# --------------------------------------------------------------------------
# Camadas: inputs em arquivo; results no banco
# --------------------------------------------------------------------------
def save_layer(project_id: str, kind: str, gdf: gpd.GeoDataFrame) -> int:
    if kind not in LAYER_KINDS:
        raise ValueError(f"Camada inválida: {kind}. Use {sorted(LAYER_KINDS)}.")
    get_meta(project_id)  # valida existência (KeyError -> 404)
    if kind == "results":
        return _save_results(project_id, gdf)
    d = _proj_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    gdf.to_file(d / f"{kind}.gpkg", driver="GPKG")
    return len(gdf)


def load_layer(project_id: str, kind: str) -> gpd.GeoDataFrame | None:
    if kind == "results":
        return _load_results(project_id)
    path = _proj_dir(project_id) / f"{kind}.gpkg"
    if not path.is_file():
        return None
    return gpd.read_file(path)


def _clean_float(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _clean_text(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


def _save_results(project_id: str, gdf: gpd.GeoDataFrame) -> int:
    with SessionLocal() as db:
        db.execute(delete(Lot).where(Lot.project_id == project_id))
        new_ids: list[int] = []
        if gdf is not None and not gdf.empty:
            g = gdf.to_crs("EPSG:4326") if gdf.crs is not None else gdf
            objs: list[Lot] = []
            for i, (_, row) in enumerate(g.iterrows()):
                geom = row.get("geometry")
                if geom is None:
                    continue
                seq = i
                if "id" in g.columns:
                    try:
                        seq = int(row["id"])
                    except (TypeError, ValueError):
                        seq = i
                attrs = {c: _clean_float(row.get(c)) for c in _FLOAT_COLS}
                attrs.update({c: _clean_text(row.get(c)) for c in _TEXT_COLS})
                lot = Lot(project_id=project_id, seq=seq,
                          geom_wkb=wkb.dumps(geom), **attrs)
                objs.append(lot)
                db.add(lot)
            db.flush()  # atribui os PKs em ordem de inserção
            new_ids = [o.id for o in objs]
        db.commit()
    # ids estáveis de volta no gdf (payloads montados depois usam isto)
    if gdf is not None and not gdf.empty and new_ids:
        gdf["id"] = new_ids
    return len(new_ids)


def _load_results(project_id: str) -> gpd.GeoDataFrame | None:
    with SessionLocal() as db:
        rows = db.execute(
            select(Lot).where(Lot.project_id == project_id)
            .order_by(Lot.seq, Lot.id)
        ).scalars().all()
    if not rows:
        return None
    records, geoms = [], []
    for r in rows:
        rec = {"id": r.id}
        for c in _LOT_COLS:
            rec[c] = getattr(r, c)
        records.append(rec)
        geoms.append(wkb.loads(r.geom_wkb) if r.geom_wkb else None)
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    # remove colunas de enrich totalmente nulas (fiel ao detect não-enriquecido)
    drop = [c for c in _ENRICH_COLS if c in gdf.columns and gdf[c].isna().all()]
    return gdf.drop(columns=drop) if drop else gdf


# --------------------------------------------------------------------------
# Ficha do lote (CRM de prospecção) — tabela lot_crm.
# Matrícula e dono NÃO têm API pública no Brasil (cartórios/LGPD); o usuário
# consulta o cartório/prefeitura e registra aqui o resultado e o andamento.
# --------------------------------------------------------------------------
LOT_STATUSES = ["novo", "analisando", "contato_feito", "negociando", "descartado", "comprado"]
LOT_FIELDS = {"matricula", "inscricao", "proprietario", "contato", "status", "notas",
              "layout", "bolha"}
_CRM_TEXT = ("matricula", "inscricao", "proprietario", "contato", "status", "notas")


def _crm_entry(c: LotCrm) -> dict:
    return {
        "matricula": c.matricula or "",
        "inscricao": c.inscricao or "",
        "proprietario": c.proprietario or "",
        "contato": c.contato or "",
        "status": c.status or "",
        "notas": c.notas or "",
        "layout": c.layout,
        "bolha": c.bolha,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def get_lots_info(project_id: str) -> dict:
    """Todas as fichas do projeto: {lot_id: {matricula, proprietario, ...}}."""
    with SessionLocal() as db:
        if db.get(Project, project_id) is None:
            raise KeyError(f"Projeto não encontrado: {project_id}")
        rows = db.execute(
            select(LotCrm, Lot.id).join(Lot, LotCrm.lot_id == Lot.id)
            .where(Lot.project_id == project_id)
        ).all()
        return {str(lot_id): _crm_entry(c) for c, lot_id in rows}


def set_lot_info(project_id: str, lot_id: str, fields: dict) -> dict:
    """Atualiza a ficha de um lote (merge). Campos fora de LOT_FIELDS são ignorados."""
    with SessionLocal() as db:
        if db.get(Project, project_id) is None:
            raise KeyError(f"Projeto não encontrado: {project_id}")
        try:
            lid = int(lot_id)
        except (TypeError, ValueError):
            raise KeyError(f"Lote inválido: {lot_id!r}")
        lot = db.execute(
            select(Lot).where(Lot.project_id == project_id, Lot.id == lid)
        ).scalar_one_or_none()
        if lot is None:
            raise KeyError(f"Lote não encontrado: {lot_id}")

        crm = db.get(LotCrm, lid) or LotCrm(lot_id=lid)
        for k, v in fields.items():
            if k not in LOT_FIELDS:
                continue
            if k == "status" and v and v not in LOT_STATUSES:
                raise ValueError(f"Status inválido: {v!r}. Use {LOT_STATUSES}.")
            if k in ("layout", "bolha"):
                setattr(crm, k, v if isinstance(v, dict) else None)
            else:
                setattr(crm, k, (str(v).strip() if v is not None else ""))
        db.add(crm)
        db.commit()
        db.refresh(crm)
        return _crm_entry(crm)
