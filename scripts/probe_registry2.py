"""Probe round 2: SIGEF com SSL relaxado, DataJud com timeout maior, CEP real."""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request

UA = {"User-Agent": "LotePro/0.2 (devs@grupomngt.com.br)"}
LAT, LON = -16.7080, -49.0910
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(url, headers=None, body=None, timeout=60):
    h = dict(UA)
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    if body is not None:
        h["Content-Type"] = "application/json"
    method = "POST" if body is not None else "GET"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout, context=CTX) as resp:
        return resp.status, resp.read()


def show(name, fn):
    print(f"\n=== {name} ===")
    try:
        status, raw = fn()
        print(f"HTTP {status} | {len(raw)} bytes")
        print(raw.decode("utf-8", errors="replace")[:1200])
    except Exception as e:
        print(f"FALHOU: {type(e).__name__}: {e}")


# CEP que o Nominatim devolveu para o ponto de teste
show("BrasilAPI CEP v2 75262-295", lambda: get(
    "https://brasilapi.com.br/api/cep/v2/75262295", timeout=25))

# SIGEF i3geo OGC com SSL relaxado
show("INCRA i3geo GetCapabilities (SSL off)", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?service=WFS&version=1.0.0&request=GetCapabilities&tema=certificada_sigef",
    timeout=60))

bbox = f"{LON-0.05},{LAT-0.05},{LON+0.05},{LAT+0.05}"
show("INCRA i3geo WFS GetFeature GeoJSON (SSL off)", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?service=WFS&version=1.0.0&request=GetFeature&tema=certificada_sigef"
    f"&typename=certificada_sigef&bbox={bbox}&outputformat=GeoJSON",
    timeout=90))

# DataJud com timeout maior (chave publica; override via DATAJUD_API_KEY)
DATAJUD_KEY = os.getenv("DATAJUD_API_KEY", "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==")
show("DataJud TJGO match_all (90s)", lambda: get(
    "https://api-publica.datajud.cnj.jus.br/api_publica_tjgo/_search",
    headers={"Authorization": f"APIKey {DATAJUD_KEY}"},
    body={"size": 1, "query": {"match_all": {}}},
    timeout=90))

print("\nPROBE2: fim")
sys.exit(0)
