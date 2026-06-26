"""Consultas públicas para a ficha do lote: endereço, proprietário e processos.

O que cada fonte entrega (todas gratuitas, sem chave privada):

  - Nominatim (OSM) reverso → endereço oficial do lote (rua, bairro, CEP),
    que é o dado de entrada para localizar a matrícula no cartório (ONR)
    e a inscrição imobiliária no IPTU da prefeitura.
  - BrasilAPI /cnpj → dados do proprietário pessoa jurídica: razão social,
    situação cadastral, capital, endereço e QUADRO DE SÓCIOS (QSA).
  - DataJud (CNJ, chave pública oficial) → metadados de processos judiciais
    por NÚMERO de processo: classe, assuntos, órgão julgador, movimentos.

Limites legais (LGPD/cartórios) — explicitados na interface:
  - O inteiro teor da matrícula e o nome de proprietário pessoa física NÃO
    existem em API pública; a certidão é pedida online no portal do ONR
    (registrodeimoveis.org.br). O dataset público do DataJud não inclui o
    nome das partes, então busca de processo POR NOME é feita pelos links
    (TJ do estado / JusBrasil / Escavador), não por API.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from .. import config

USER_AGENT = "LotePro/0.2 (devs@grupomngt.com.br)"
# SICAR rejeita UA não-navegador (302); usamos um UA de browser só p/ essa fonte.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
DATAJUD_URL = "https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search"
# Chave PÚBLICA da API do DataJud (CNJ), agora em config/.env (DATAJUD_API_KEY).
# Documentada em https://datajud-wiki.cnj.jus.br/api-publica/acesso (igual p/ todos).
DATAJUD_PUBLIC_KEY = config.DATAJUD_API_KEY

# Tribunal de Justiça estadual por UF (alias do índice público do DataJud).
UF_TJ_ALIAS = {
    "AC": "tjac", "AL": "tjal", "AM": "tjam", "AP": "tjap", "BA": "tjba",
    "CE": "tjce", "DF": "tjdft", "ES": "tjes", "GO": "tjgo", "MA": "tjma",
    "MG": "tjmg", "MS": "tjms", "MT": "tjmt", "PA": "tjpa", "PB": "tjpb",
    "PE": "tjpe", "PI": "tjpi", "PR": "tjpr", "RJ": "tjrj", "RN": "tjrn",
    "RO": "tjro", "RR": "tjrr", "RS": "tjrs", "SC": "tjsc", "SE": "tjse",
    "SP": "tjsp", "TO": "tjto",
}

_nominatim_lock = threading.Lock()
_nominatim_last = 0.0
_point_cache: dict[tuple[float, float], dict] = {}


def _get_json(url: str, *, body: dict | None = None,
              headers: dict | None = None, timeout: float = 30) -> dict:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ----------------------------------------------------------------------------
# Endereço oficial do ponto (Nominatim reverso) + links que funcionam
# ----------------------------------------------------------------------------
def lookup_point(lat: float, lon: float) -> dict:
    """Endereço oficial do lote + links de consulta de matrícula/cadastro."""
    key = (round(lat, 5), round(lon, 5))
    if key in _point_cache:
        return _point_cache[key]

    addr: dict = {}
    display = None
    try:
        # Política do Nominatim: máx. 1 req/s — throttle global do processo.
        global _nominatim_last
        with _nominatim_lock:
            wait = 1.1 - (time.monotonic() - _nominatim_last)
            if wait > 0:
                time.sleep(wait)
            _nominatim_last = time.monotonic()
        q = urllib.parse.urlencode({
            "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2",
            "addressdetails": 1, "zoom": 18, "accept-language": "pt-BR",
        })
        data = _get_json(f"{NOMINATIM_URL}?{q}", timeout=25)
        addr = data.get("address") or {}
        display = data.get("display_name")
    except Exception:
        pass  # sem rede/limite: ficha continua com links genéricos

    iso = addr.get("ISO3166-2-lvl4") or ""        # ex.: "BR-GO"
    uf = iso.split("-")[-1] if iso.startswith("BR-") else None
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("municipality"))

    out = {
        "endereco": {
            "logradouro": addr.get("road"),
            "bairro": addr.get("suburb") or addr.get("neighbourhood"),
            "cidade": city,
            "uf": uf,
            "cep": addr.get("postcode"),
            "display": display,
        },
        "links": _consult_links(lat, lon, uf),
        # transparência: o que dá e o que não dá para automatizar
        "aviso": ("Inteiro teor da matrícula e proprietário pessoa física não têm "
                  "API pública (cartórios/LGPD). Peça a certidão digital no portal "
                  "oficial do ONR usando o endereço acima — sai em PDF no mesmo dia."),
    }
    _point_cache[key] = out
    return out


def _consult_links(lat: float, lon: float, uf: str | None) -> list[dict]:
    links = [
        {"label": "🏛️ ONR — Registro de Imóveis do Brasil (pedir matrícula/certidão)",
         "url": "https://www.registrodeimoveis.org.br/"},
        {"label": "🌾 SIGEF/INCRA — parcelas rurais certificadas (mapa)",
         "url": "https://sigef.incra.gov.br/geo/mapa/"},
        {"label": "🌳 CAR — Cadastro Ambiental Rural (consulta pública)",
         "url": "https://consultapublica.car.gov.br/publico/imoveis/index"},
    ]
    if uf == "GO":
        links.append({"label": "⚖️ TJGO — consulta processual pública (Projudi)",
                      "url": "https://projudi.tjgo.jus.br/BuscaProcessoPublica"})
    return links


# ----------------------------------------------------------------------------
# Proprietário pessoa jurídica (BrasilAPI /cnpj — Receita Federal)
# ----------------------------------------------------------------------------
@lru_cache(maxsize=256)
def cnpj_info(cnpj: str) -> dict:
    """Dados cadastrais + quadro de sócios de um CNPJ (BrasilAPI)."""
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) != 14:
        raise ValueError("CNPJ deve ter 14 dígitos.")
    try:
        data = _get_json(BRASILAPI_CNPJ_URL.format(cnpj=digits), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError("CNPJ não encontrado na base da Receita Federal.")
        raise ValueError(f"BrasilAPI indisponível (HTTP {e.code}). Tente de novo.")
    except Exception:
        raise ValueError("BrasilAPI indisponível no momento. Tente de novo.")

    fmt = f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    socios = [{
        "nome": s.get("nome_socio"),
        "qualificacao": s.get("qualificacao_socio"),
        "entrada": s.get("data_entrada_sociedade"),
    } for s in (data.get("qsa") or [])]
    ende = " ".join(str(p) for p in (
        data.get("descricao_tipo_de_logradouro"), data.get("logradouro"),
        data.get("numero"), data.get("bairro"), data.get("municipio"),
        data.get("uf"), data.get("cep")) if p)
    return {
        "cnpj": fmt,
        "razao_social": data.get("razao_social"),
        "nome_fantasia": data.get("nome_fantasia"),
        "situacao": data.get("descricao_situacao_cadastral"),
        "data_situacao": data.get("data_situacao_cadastral"),
        "natureza": data.get("natureza_juridica"),
        "porte": data.get("porte"),
        "capital_social": data.get("capital_social"),
        "atividade": data.get("cnae_fiscal_descricao"),
        "endereco": ende or None,
        "telefone": data.get("ddd_telefone_1"),
        "email": data.get("email"),
        "socios": socios,
    }


# ----------------------------------------------------------------------------
# Processos judiciais por número (DataJud / CNJ — chave pública oficial)
# ----------------------------------------------------------------------------
def _fmt_numero_cnj(d: str) -> str:
    # NNNNNNN-DD.AAAA.J.TR.OOOO
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


def _fmt_data_ajuiz(s: str | None) -> str | None:
    if not s or len(s) < 8:
        return s
    return f"{s[6:8]}/{s[4:6]}/{s[:4]}"


def processo_by_numero(numero: str, uf: str) -> dict:
    """Metadados públicos de um processo no TJ do estado (DataJud/CNJ)."""
    digits = re.sub(r"\D", "", numero or "")
    if len(digits) != 20:
        raise ValueError("Número de processo CNJ deve ter 20 dígitos "
                         "(formato NNNNNNN-DD.AAAA.J.TR.OOOO).")
    alias = UF_TJ_ALIAS.get((uf or "").upper())
    if not alias:
        raise ValueError(f"UF desconhecida: {uf!r}")
    try:
        data = _get_json(
            DATAJUD_URL.format(alias=alias),
            body={"size": 5, "query": {"match": {"numeroProcesso": digits}}},
            headers={"Authorization": f"APIKey {DATAJUD_PUBLIC_KEY}"},
            timeout=90,  # o cluster público do CNJ costuma demorar ~20 s
        )
    except Exception:
        raise ValueError("DataJud (CNJ) indisponível no momento. Tente de novo.")

    hits = (data.get("hits") or {}).get("hits") or []
    if not hits:
        raise LookupError(
            f"Processo não encontrado no {alias.upper()}. Confira o número "
            "ou consulte o site do tribunal.")

    found = []
    for h in hits:
        src = h.get("_source") or {}
        movs = src.get("movimentos") or []
        last = max(movs, key=lambda m: m.get("dataHora") or "") if movs else None
        found.append({
            "numero": _fmt_numero_cnj(digits),
            "tribunal": src.get("tribunal"),
            "grau": src.get("grau"),
            "classe": (src.get("classe") or {}).get("nome"),
            "assuntos": [a.get("nome") for a in (src.get("assuntos") or [])
                         if isinstance(a, dict) and a.get("nome")],
            "orgao": (src.get("orgaoJulgador") or {}).get("nome"),
            "ajuizamento": _fmt_data_ajuiz(src.get("dataAjuizamento")),
            "ultimo_movimento": ({
                "nome": last.get("nome"),
                "data": (last.get("dataHora") or "")[:10],
            } if last else None),
            "movimentos": len(movs),
        })
    return {"processos": found,
            "aviso": ("Dataset público do CNJ não inclui nome das partes (LGPD); "
                      "para buscar POR NOME use o site do tribunal.")}


# ----------------------------------------------------------------------------
# Imóvel rural no CAR (SICAR — consulta pública) por ponto lat/lon
# ----------------------------------------------------------------------------
# A API só responde com cookie de sessão (PLAY_SESSION). Fazemos o bootstrap
# uma vez (GET no índice), reusamos a sessão e cacheamos por ponto.
SICAR_INDEX = "https://consultapublica.car.gov.br/publico/imoveis/index"
SICAR_GET = "https://consultapublica.car.gov.br/publico/imoveis/getImovel"

_CAR_STATUS = {"AT": "Ativo", "PE": "Pendente", "SU": "Suspenso",
               "CA": "Cancelado", "EM": "Em análise"}
_CAR_TIPO = {"IRU": "Imóvel Rural", "AST": "Assentamento",
             "PCT": "Território de Povos e Comunidades Tradicionais"}

_car_lock = threading.Lock()
_car_opener = None
_car_session_ts = 0.0
_car_cache: dict[tuple[float, float], dict] = {}


def _sicar_ssl_context():
    """Contexto TLS aceito pelo WAF do SICAR.

    O urllib padrão leva SSLV3_ALERT_HANDSHAKE_FAILURE (o servidor recusa o
    fingerprint TLS do Python); baixar o SECLEVEL para 1 amplia a lista de
    cifras/curvas oferecidas e o handshake passa.
    """
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def _car_session():
    """Opener com cookie de sessão do SICAR (renovado a cada ~10 min)."""
    global _car_opener, _car_session_ts
    with _car_lock:
        if _car_opener is None or (time.monotonic() - _car_session_ts) > 600:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=_sicar_ssl_context()),
                urllib.request.HTTPCookieProcessor(jar))
            try:  # o GET no índice 302/500 mas seta o PLAY_SESSION no jar
                opener.open(urllib.request.Request(
                    SICAR_INDEX, headers={"User-Agent": BROWSER_UA}), timeout=20).read()
            except Exception:
                pass
            _car_opener = opener
            _car_session_ts = time.monotonic()
        return _car_opener


def car_imovel(lat: float, lon: float) -> dict:
    """Imóvel rural do CAR que contém o ponto (SICAR consulta pública).

    Retorna {found, codigo, area_ha, status_label, tipo_label, municipio,
    data_*, url, geometry} — ou {found: False} se o ponto não cai num imóvel
    cadastrado (típico em área urbana) ou o serviço estiver fora.
    """
    key = (round(lat, 5), round(lon, 5))
    if key in _car_cache:
        return _car_cache[key]

    result: dict = {"found": False}
    try:
        opener = _car_session()
        q = urllib.parse.urlencode({"lat": f"{lat:.10f}", "lng": f"{lon:.10f}"})
        req = urllib.request.Request(
            f"{SICAR_GET}?{q}",
            headers={"Accept": "application/json", "User-Agent": BROWSER_UA,
                     "X-Requested-With": "XMLHttpRequest", "Referer": SICAR_INDEX})
        data = json.loads(opener.open(req, timeout=25).read())
        feats = data.get("features") or []
        if feats:
            p = feats[0].get("properties") or {}
            codigo = p.get("codigo")
            result = {
                "found": True,
                "codigo": codigo,
                "area_ha": p.get("area"),
                "status": p.get("status"),
                "status_label": _CAR_STATUS.get(p.get("status"), p.get("status")),
                "tipo": p.get("tipo"),
                "tipo_label": _CAR_TIPO.get(p.get("tipo"), p.get("tipo")),
                "municipio": p.get("municipio"),
                "categoria": p.get("categoria"),
                "data_disponibilizacao": p.get("dataDisponibilizacao"),
                "data_criacao": (p.get("dataCriacao") or "")[:10] or None,
                "url": f"https://car.gov.br/#/consultar/{codigo}" if codigo else None,
                "geometry": feats[0].get("geometry"),
            }
    except Exception:
        pass

    _car_cache[key] = result
    return result
