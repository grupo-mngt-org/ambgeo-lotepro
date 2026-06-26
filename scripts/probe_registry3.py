"""Probe round 3: variantes SIGEF/INCRA (tema por UF, geoserver)."""
from __future__ import annotations

import json
import ssl
import urllib.request

UA = {"User-Agent": "LotePro/0.2 (devs@grupomngt.com.br)"}
LAT, LON = -16.7080, -49.0910
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(url, timeout=60):
    r = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(r, timeout=timeout, context=CTX) as resp:
        return resp.status, resp.read()


def show(name, fn):
    print(f"\n=== {name} ===")
    try:
        status, raw = fn()
        print(f"HTTP {status} | {len(raw)} bytes")
        print(raw.decode("utf-8", errors="replace")[:1000])
    except Exception as e:
        print(f"FALHOU: {type(e).__name__}: {e}")


bbox = f"{LON-0.05},{LAT-0.05},{LON+0.05},{LAT+0.05}"

show("i3geo tema=certificada_sigef_go GetFeature", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?tema=certificada_sigef_go&service=WFS&version=1.0.0&request=GetFeature"
    f"&typename=certificada_sigef_go&bbox={bbox}&outputformat=GeoJSON"))

show("i3geo tema=certificada_sigef_go GetCapabilities", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php"
    "?tema=certificada_sigef_go&service=WFS&request=GetCapabilities"))

show("acervo geoserver ows GetCapabilities", lambda: get(
    "https://acervofundiario.incra.gov.br/geoserver/ows"
    "?service=WFS&request=GetCapabilities", timeout=40))

show("i3geo ogc.php sem params (lista temas?)", lambda: get(
    "https://acervofundiario.incra.gov.br/i3geo/ogc.php", timeout=40))

print("\nPROBE3: fim")
