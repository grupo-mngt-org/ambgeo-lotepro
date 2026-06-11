"""Smoke test ponta a ponta contra o servidor rodando em 127.0.0.1:8000.

Login -> cria projeto -> envia AOI/buildings/zoning de exemplo -> detecta ->
busca resultados -> exporta CSV/XLSX/KML. Usa apenas a stdlib (urllib).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def req(method, path, *, token=None, data=None, json_body=None, multipart=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif multipart is not None:
        boundary = "----lotepro"
        fname, content = multipart
        parts = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        body = parts
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    r = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        return resp.status, resp.read()


def main() -> int:
    # 1. login
    _, b = req("POST", "/api/auth/login", json_body={"username": "admin", "password": "lotepro"})
    token = json.loads(b)["token"]
    print("login OK")

    # 2. projeto
    _, b = req("POST", "/api/projects", token=token, json_body={"name": "Smoke"})
    pid = json.loads(b)["id"]
    print("projeto", pid)

    # 3. camadas
    for kind in ("aoi", "buildings", "zoning"):
        content = (SAMPLES / f"{kind}.geojson").read_bytes()
        _, b = req("POST", f"/api/projects/{pid}/layers/{kind}", token=token,
                   multipart=(f"{kind}.geojson", content))
        print("upload", kind, json.loads(b))

    # 4. detecção
    _, b = req("POST", f"/api/projects/{pid}/detect", token=token,
               json_body={"provider": "footprint", "mode": "gaps",
                          "min_area_m2": 500, "max_occupation_ratio": 0.15})
    det = json.loads(b)
    print("detect count =", det["count"])
    assert det["count"] > 0, "nenhum vazio encontrado"
    props = det["results"]["features"][0]["properties"]
    assert {"area_m2", "occupation", "zoning", "street_view", "potential"} <= props.keys()
    print("amostra:", {k: props[k] for k in ("area_m2", "occupation", "potential", "zoning")})

    # 5. exports
    for fmt in ("csv", "xlsx", "kml"):
        st, b = req("GET", f"/api/projects/{pid}/export.{fmt}", token=token)
        assert st == 200 and len(b) > 0, f"export {fmt} vazio"
        print(f"export {fmt}: {len(b)} bytes OK")

    # 6. auth negativa
    try:
        req("GET", "/api/projects")
        print("ERRO: deveria exigir auth"); return 1
    except urllib.error.HTTPError as e:
        assert e.code == 401
        print("auth obrigatória OK (401)")

    print("\nSMOKE E2E: PASSOU [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
