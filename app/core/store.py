"""Persistência por projeto (isolamento de dados — RNF03).

Cada projeto vive em data/projects/<id>/ com:
  - meta.json          metadados (nome, criado_em, último detect)
  - <kind>.gpkg        camadas vetoriais: aoi | buildings | zoning | results

GeoPackage é o formato de persistência (lido/escrito via pyogrio).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

from .. import config

LAYER_KINDS = {"aoi", "buildings", "zoning", "results", "exclusions"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proj_dir(project_id: str) -> Path:
    return config.PROJECTS_DIR / project_id


def create_project(name: str) -> dict:
    pid = uuid.uuid4().hex[:12]
    d = _proj_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": pid, "name": name or pid, "created_at": _now(), "last_detect": None}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_projects() -> list[dict]:
    out = []
    for d in sorted(config.PROJECTS_DIR.glob("*")):
        meta = d / "meta.json"
        if meta.is_file():
            out.append(json.loads(meta.read_text(encoding="utf-8")))
    return out


def get_meta(project_id: str) -> dict:
    meta = _proj_dir(project_id) / "meta.json"
    if not meta.is_file():
        raise KeyError(f"Projeto não encontrado: {project_id}")
    return json.loads(meta.read_text(encoding="utf-8"))


def update_meta(project_id: str, **fields) -> dict:
    meta = get_meta(project_id)
    meta.update(fields)
    (_proj_dir(project_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def save_layer(project_id: str, kind: str, gdf: gpd.GeoDataFrame) -> int:
    if kind not in LAYER_KINDS:
        raise ValueError(f"Camada inválida: {kind}. Use {sorted(LAYER_KINDS)}.")
    get_meta(project_id)  # valida existência
    path = _proj_dir(project_id) / f"{kind}.gpkg"
    gdf.to_file(path, driver="GPKG")
    return len(gdf)


def load_layer(project_id: str, kind: str) -> gpd.GeoDataFrame | None:
    path = _proj_dir(project_id) / f"{kind}.gpkg"
    if not path.is_file():
        return None
    return gpd.read_file(path)


# ---------------------------------------------------------------------------
# Ficha do lote (CRM de prospecção) — lots.json por projeto.
# Matrícula e dono NÃO têm API pública no Brasil (cartórios/LGPD); o usuário
# consulta o cartório/prefeitura e registra aqui o resultado e o andamento.
# ---------------------------------------------------------------------------
LOT_STATUSES = ["novo", "analisando", "contato_feito", "negociando", "descartado", "comprado"]
LOT_FIELDS = {"matricula", "inscricao", "proprietario", "contato", "status", "notas", "layout"}


def _lots_file(project_id: str) -> Path:
    return _proj_dir(project_id) / "lots.json"


def get_lots_info(project_id: str) -> dict:
    """Todas as fichas do projeto: {lot_id: {matricula, proprietario, ...}}."""
    get_meta(project_id)  # valida existência
    f = _lots_file(project_id)
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_lot_info(project_id: str, lot_id: str, fields: dict) -> dict:
    """Atualiza a ficha de um lote (merge). Campos fora de LOT_FIELDS são ignorados."""
    data = get_lots_info(project_id)
    entry = data.get(str(lot_id), {})
    for k, v in fields.items():
        if k not in LOT_FIELDS:
            continue
        if k == "status" and v and v not in LOT_STATUSES:
            raise ValueError(f"Status inválido: {v!r}. Use {LOT_STATUSES}.")
        if k == "layout":  # estudo de implantação salvo: dict {params, stats}
            entry[k] = v if isinstance(v, dict) else None
            continue
        entry[k] = (str(v).strip() if v is not None else "")
    entry["updated_at"] = _now()
    data[str(lot_id)] = entry
    _lots_file(project_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry
