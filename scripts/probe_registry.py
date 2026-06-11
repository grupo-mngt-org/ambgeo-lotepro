"""Sonda as APIs publicas candidatas para a ficha de matricula/proprietario.

Roda cada endpoint de verdade e imprime o que respondeu, para decidir o que
integrar em app/core/registry.py. Ponto de teste: lote em Senador Canedo-GO.
"""
from __future__ import annotations

import json
import sys
import urllib.request

UA = {"User-Agent": "LotePro/0.2 (devs@grupomngt.com.br)"}
LAT, LON = -16.7080, -49.0910  # Senador Canedo - GO


def get(url, headers=None, body=None, timeout=25):
    h = dict(UA)
    if headers:
        h.update(headers)
    method = "POST" if body is not None else "GET"
    data = json.dumps(body).encode() if body is not None else None
    if body is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()


def show(name, fn):
    print(f"\n=== {name} ===")
    try:
        status, raw = fn()
        txt = raw.decode("utf-8", errors="replace")
        print(f"HTTP {status} | {len(raw)} bytes")
        print(txt[:900])
    except Exception as e:
        print(f"FALHOU: {type(e).__name__}: {e}")


# 1. Nominatim reverse -> endereco + CEP
show("Nominatim reverse", lambda: get(
    f"https://nominatim.openstreetmap.org/reverse?lat={LAT}&lon={LON}"
    "&format=jsonv2&addressdetails=1&zoom=18&accept-language=pt-BR"))

# 2. BrasilAPI CEP v2
show("BrasilAPI CEP v2 (75250-000 Senador Canedo)", lambda: get(
    "https://brasilapi.com.br/api/cep/v2/75250000"))

# 3. BrasilAPI CNPJ (ex.: CNPJ da Prefeitura de Senador Canedo ou um conhecido)
show("BrasilAPI CNPJ v1 (00.000.000/0001-91 Banco do Brasil)", lambda: get(
    "https://brasilapi.com.br/api/cnpj/v1/00000000000191"))

# 4. SIGEF/INCRA - tentativas de WFS/JSON publico
show("INCRA acervofundiario i3geo OGC GetCapabilities", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?service=WFS&version=1.0.0&request=GetCapabilities&tema=certificada_sigef"))

show("SIGEF busca JSON (texto)", lambda: get(
    "https://sigef.incra.gov.br/geo/parcela/buscar/?texto=senador%20canedo"))

bbox = f"{LON-0.02},{LAT-0.02},{LON+0.02},{LAT+0.02}"
show("INCRA i3geo WFS GetFeature bbox", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?service=WFS&version=1.0.0&request=GetFeature&tema=certificada_sigef"
    f"&typename=certificada_sigef&bbox={bbox}&outputformat=GeoJSON"))

# 5. DataJud CNJ - API publica (chave publica documentada pelo CNJ)
DATAJUD_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
show("DataJud TJGO match_all size=1", lambda: get(
    "https://api-publica.datajud.cnj.jus.br/api_publica_tjgo/_search",
    headers={"Authorization": f"APIKey {DATAJUD_KEY}"},
    body={"size": 1, "query": {"match_all": {}}}))

# 6. ONR / Registro de Imoveis - so checa se o dominio novo responde
show("registrodeimoveis.org.br (HEAD-ish GET)", lambda: get(
    "https://www.registrodeimoveis.org.br/", timeout=20))

show("registradores.onr.org.br (link atual quebrado?)", lambda: get(
    "https://www.registradores.onr.org.br/", timeout=20))

print("\nPROBE: fim")
sys.exit(0)
