"""Endpoints REST do Lote Pro."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ..core import (analysis, auth, citywide, enrich, io, jobs, layout, osm,
                    registry, report, score, store)
from ..providers import DetectionParams, get_provider

router = APIRouter(prefix="/api")
_bearer = HTTPBearer(auto_error=False)

VALID_SOURCES = ("auto", "osm", "ms", "overture", "google")


# ----------------------------- Auth ---------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    user = auth.verify_token(cred.credentials) if cred else None
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return user


@router.post("/auth/login")
def login(body: LoginIn):
    if not auth.verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    return {"token": auth.create_token(body.username), "user": body.username}


# --------------------------- Projetos -------------------------------------
class ProjectIn(BaseModel):
    name: str = ""


@router.get("/projects")
def projects(user: str = Depends(current_user)):
    return store.list_projects()


@router.post("/projects")
def create_project(body: ProjectIn, user: str = Depends(current_user)):
    return store.create_project(body.name)


# --------------------------- Camadas --------------------------------------
@router.post("/projects/{pid}/layers/{kind}")
async def upload_layer(
    pid: str, kind: str, file: UploadFile = File(...), user: str = Depends(current_user)
):
    if kind not in store.LAYER_KINDS - {"results"}:
        raise HTTPException(400, "Camada inválida. Use aoi, buildings ou zoning.")
    try:
        gdf = io.read_vector(file.filename, await file.read())
        count = store.save_layer(pid, kind, gdf)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"kind": kind, "features": count}


@router.get("/projects/{pid}/layers/{kind}")
def get_layer(pid: str, kind: str, user: str = Depends(current_user)):
    gdf = store.load_layer(pid, kind)
    if gdf is None:
        raise HTTPException(404, f"Camada '{kind}' não encontrada.")
    return JSONResponse(io.to_geojson_dict(gdf))


# --------------------------- Autocomplete ---------------------------------
@router.get("/geocode/suggest")
def geocode_suggest(q: str = "", cities: int = 0, user: str = Depends(current_user)):
    """Sugestões de endereço (autocomplete) via Photon.
    `cities=1` filtra municípios (modo cidade inteira)."""
    return osm.suggest(q, cities_only=bool(cities))


# --------------------------- Perfis de finalidade --------------------------
@router.get("/profiles")
def profiles(user: str = Depends(current_user)):
    """Perfis de finalidade de compra (pesos/critérios do score de viabilidade)."""
    return score.list_profiles()


# ---------- Registro: endereço, proprietário (CNPJ) e processos ------------
@router.get("/registry/point")
def registry_point(lat: float, lon: float, user: str = Depends(current_user)):
    """Endereço oficial do ponto (Nominatim) + links de consulta de matrícula."""
    return registry.lookup_point(lat, lon)


@router.get("/registry/cnpj/{cnpj}")
def registry_cnpj(cnpj: str, user: str = Depends(current_user)):
    """Proprietário PJ: dados cadastrais + sócios (BrasilAPI/Receita)."""
    try:
        return registry.cnpj_info(cnpj)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/registry/processo")
def registry_processo(numero: str, uf: str = "GO",
                      user: str = Depends(current_user)):
    """Processo judicial por número CNJ (DataJud — metadados públicos)."""
    try:
        return registry.processo_by_numero(numero, uf)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------ Análise completa (1 clique) ---------------------------
class AnalyzeIn(BaseModel):
    mode: str = "radius"             # "radius" (endereço+raio) | "city" (cidade inteira)
    query: str = ""
    lat: float | None = None
    lon: float | None = None
    osm_type: str | None = None      # modo cidade: tipo OSM da sugestão (R/W)
    osm_id: int | None = None        # modo cidade: id OSM (limite municipal exato)
    radius_m: float = 500.0
    buildings_source: str = "auto"   # auto = Microsoft + OSM (alta cobertura)
    # Finalidade da compra + metragem-alvo (alimentam o score de viabilidade).
    profile: str = "condominio_casas"
    target_min_m2: float | None = None
    target_max_m2: float | None = None
    enrich: bool = True              # declividade/acesso/entorno + score
    weights: dict | None = None      # override de pesos (perfil personalizado)
    # Avançado (opcionais): sobrescrevem os defaults permissivos da análise.
    provider: str = "footprint"
    min_area_m2: float = report.PERMISSIVE["min_area_m2"]
    max_occupation_ratio: float = report.PERMISSIVE["max_occupation_ratio"]
    min_width_m: float = 6.0
    building_buffer_m: float = 1.5
    max_area_m2: float = 2_000_000.0  # teto de área (modo cidade)
    project_id: str | None = None


def _validate_analyze(body: AnalyzeIn) -> None:
    if not (body.query.strip() or (body.lat is not None and body.lon is not None)):
        raise HTTPException(400, "Informe um endereço/cidade ou selecione uma sugestão.")
    if body.buildings_source not in VALID_SOURCES:
        raise HTTPException(400, f"buildings_source deve ser um de {VALID_SOURCES}.")
    if body.mode not in ("radius", "city"):
        raise HTTPException(400, "mode deve ser 'radius' ou 'city'.")


def _run_analysis(progress, body: AnalyzeIn) -> dict:
    progress = progress or (lambda *a, **k: None)
    if body.mode == "city":
        return citywide.analyze_city(
            progress,
            city_query=body.query, osm_type=body.osm_type, osm_id=body.osm_id,
            buildings_source=body.buildings_source,
            profile=body.profile, target_min_m2=body.target_min_m2,
            target_max_m2=body.target_max_m2, weights=body.weights,
            min_area_m2=body.min_area_m2,
            max_occupation_ratio=body.max_occupation_ratio,
            min_width_m=body.min_width_m, building_buffer_m=body.building_buffer_m,
            max_area_m2=body.max_area_m2, project_id=body.project_id)
    return analysis.analyze_radius(
        progress,
        query=body.query, lat=body.lat, lon=body.lon, radius_m=body.radius_m,
        buildings_source=body.buildings_source,
        profile=body.profile, target_min_m2=body.target_min_m2,
        target_max_m2=body.target_max_m2, enrich_enabled=body.enrich,
        weights=body.weights, provider=body.provider,
        min_area_m2=body.min_area_m2,
        max_occupation_ratio=body.max_occupation_ratio,
        min_width_m=body.min_width_m, building_buffer_m=body.building_buffer_m,
        project_id=body.project_id)


@router.post("/analyze")
def analyze(body: AnalyzeIn, user: str = Depends(current_user)):
    """Análise síncrona (compatibilidade/scripts). O frontend usa /analyze/start."""
    _validate_analyze(body)
    try:
        return _run_analysis(None, body)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")
    except (ValueError, RuntimeError, NotImplementedError) as e:
        raise HTTPException(400, str(e))


@router.post("/analyze/start")
def analyze_start(body: AnalyzeIn, user: str = Depends(current_user)):
    """Inicia a análise em background. Acompanhe via GET /api/jobs/{id}."""
    _validate_analyze(body)
    job_id = jobs.start(f"analyze-{body.mode}", _run_analysis, body)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, user: str = Depends(current_user)):
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "Job não encontrado.")
    return j


# ---------------- Estudo de implantação (estilo TestFit) -------------------
class LayoutIn(BaseModel):
    geometry: dict                   # polígono GeoJSON do terreno (EPSG:4326)
    params: dict = {}


@router.post("/layout/preview")
def layout_preview(body: LayoutIn, user: str = Depends(current_user)):
    """Gera a implantação paramétrica (lotes, casas, vias, métricas) em tempo
    real — chamado a cada ajuste de slider no frontend."""
    try:
        return layout.generate(body.geometry, layout.LayoutParams.from_dict(body.params))
    except ValueError as e:
        raise HTTPException(400, str(e))


# --------------------- Fonte de dados real (OSM) --------------------------
class OSMSourceIn(BaseModel):
    city: str = ""
    address: str = ""
    radius_m: float = 400.0
    buildings_source: str = "auto"  # auto = Microsoft + OSM (alta cobertura)


@router.post("/projects/{pid}/source/osm")
def source_osm(pid: str, body: OSMSourceIn, user: str = Depends(current_user)):
    """Busca dados REAIS (geocodifica + baixa edificações reais) e grava as
    camadas `aoi` e `buildings`. Footprints via OSM (default) ou Overture."""
    try:
        store.get_meta(pid)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")
    if not (body.city.strip() or body.address.strip()):
        raise HTTPException(400, "Informe ao menos a cidade.")
    if body.buildings_source not in VALID_SOURCES:
        raise HTTPException(400, f"buildings_source deve ser um de {VALID_SOURCES}.")
    try:
        data = osm.fetch_area(body.city, body.address, body.radius_m, body.buildings_source)
    except ValueError as e:
        raise HTTPException(400, str(e))

    store.save_layer(pid, "aoi", data["aoi"])
    if data["buildings_count"] > 0:
        store.save_layer(pid, "buildings", data["buildings"])
    return {
        "query": data["query"],
        "center": data["center"],
        "radius_m": data["radius_m"],
        "buildings_source": data["buildings_source"],
        "buildings": data["buildings_count"],
    }


# --------------------------- Detecção -------------------------------------
@router.post("/projects/{pid}/detect")
def detect(pid: str, params: dict | None = None, user: str = Depends(current_user)):
    try:
        store.get_meta(pid)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")

    aoi = store.load_layer(pid, "aoi")
    if aoi is None:
        raise HTTPException(400, "Envie a camada 'aoi' antes de detectar.")
    buildings = store.load_layer(pid, "buildings")
    zoning = store.load_layer(pid, "zoning")

    p = DetectionParams.from_dict(params)
    try:
        provider = get_provider(p.provider)
        results = provider.detect(aoi, buildings, zoning, p)
    except (ValueError, RuntimeError, NotImplementedError) as e:
        raise HTTPException(400, str(e))

    # Reaplica o enriquecimento/score (centro e raio derivados da própria AOI).
    # Em projetos grandes (cidade inteira) o contexto é limitado e o relevo só
    # vai nos 150 maiores lotes — a cota da API pública de elevação é pequena.
    params = params or {}
    if params.get("enrich", True) and not results.empty:
        try:
            xmin, ymin, xmax, ymax = (float(v) for v in aoi.total_bounds)
            clat, clon = (ymin + ymax) / 2, (xmin + xmax) / 2
            radius = max(200.0, min((ymax - ymin) * 110_570.0 / 2, 2_500.0))
            dem_limit = 150 if len(results) > 300 else None
            results = enrich.enrich_and_score(
                results, params.get("profile", "condominio_casas"),
                params.get("target_min_m2"), params.get("target_max_m2"),
                clat, clon, radius, params.get("weights"), dem_limit=dem_limit,
            )
        except Exception:
            pass

    store.save_layer(pid, "results", results)
    store.update_meta(pid, last_detect={"provider": p.provider, "mode": p.mode, "count": len(results)})
    return {"count": len(results), "results": io.to_geojson_dict(results),
            "report": report.build_report(results),
            "lots_info": store.get_lots_info(pid)}


# ---------------- Ficha do lote (CRM de prospecção) ------------------------
class LotInfoIn(BaseModel):
    matricula: str | None = None     # nº da matrícula no Cartório de Registro de Imóveis
    inscricao: str | None = None     # inscrição imobiliária (IPTU) na prefeitura
    proprietario: str | None = None
    contato: str | None = None
    status: str | None = None        # novo|analisando|contato_feito|negociando|descartado|comprado
    notas: str | None = None
    layout: dict | None = None       # estudo de implantação salvo {params, stats}


@router.get("/projects/{pid}/lots")
def lots_info(pid: str, user: str = Depends(current_user)):
    """Fichas de todos os lotes do projeto (matrícula, proprietário, status…)."""
    try:
        return store.get_lots_info(pid)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")


@router.patch("/projects/{pid}/lots/{lot_id}")
def update_lot_info(pid: str, lot_id: str, body: LotInfoIn,
                    user: str = Depends(current_user)):
    """Atualiza a ficha de um lote. Matrícula/dono vêm da consulta manual ao
    cartório (ONR/Registradores) ou à prefeitura — não há API pública (LGPD)."""
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        return store.set_lot_info(pid, lot_id, fields)
    except KeyError:
        raise HTTPException(404, "Projeto não encontrado.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{pid}/results")
def results(pid: str, user: str = Depends(current_user)):
    gdf = store.load_layer(pid, "results")
    if gdf is None:
        raise HTTPException(404, "Nenhum resultado. Rode a detecção primeiro.")
    return JSONResponse(io.to_geojson_dict(gdf))


# --------------------------- Exportação -----------------------------------
_EXPORTS = {
    "csv": (io.export_csv, "text/csv", "leads.csv"),
    "xlsx": (io.export_xlsx,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "leads.xlsx"),
    "kml": (io.export_kml, "application/vnd.google-earth.kml+xml", "leads.kml"),
}


@router.get("/projects/{pid}/export.{fmt}")
def export(pid: str, fmt: str, user: str = Depends(current_user)):
    if fmt not in _EXPORTS:
        raise HTTPException(400, "Formato inválido. Use csv, xlsx ou kml.")
    gdf = store.load_layer(pid, "results")
    if gdf is None or gdf.empty:
        raise HTTPException(404, "Nenhum resultado para exportar.")

    # Mescla a ficha (matrícula, proprietário, status…) nos leads exportados.
    infos = store.get_lots_info(pid)
    if infos:
        for col in ("matricula", "inscricao", "proprietario", "contato", "status", "notas"):
            gdf[col] = [infos.get(str(i), {}).get(col, "") for i in gdf["id"]]
        # Estudo de implantação salvo → nº de casas do estudo no export.
        gdf["estudo_casas"] = [
            (infos.get(str(i), {}).get("layout") or {}).get("stats", {}).get("units", "")
            for i in gdf["id"]]

    fn, media, filename = _EXPORTS[fmt]
    return Response(
        content=fn(gdf),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
