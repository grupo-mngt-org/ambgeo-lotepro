"""Smoke v2: valida os 3 requisitos novos contra o servidor em 127.0.0.1:8000.

  1. Análise por raio com fonte de alta cobertura (Microsoft+OSM) — job c/ progresso.
  2. Análise de CIDADE INTEIRA — job c/ progresso.
  3. Estudo de implantação (estilo TestFit) — preview + salvar no lote.

Usa apenas stdlib (urllib). Imprime o progresso dos jobs.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def req(method, path, *, token=None, json_body=None, timeout=600):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def wait_job(token, job_id, label):
    last = ""
    while True:
        j = req("GET", f"/api/jobs/{job_id}", token=token)
        line = f"  [{label}] {j['progress']:5.1f}% {j['stage']} {j.get('detail', '')}"
        if line != last:
            print(line, flush=True)
            last = line
        if j["status"] == "done":
            return j["result"]
        if j["status"] == "error":
            raise RuntimeError(f"job {label} falhou: {j['error']}")
        time.sleep(2)


def main() -> int:
    tok = req("POST", "/api/auth/login",
              json_body={"username": "admin", "password": "lotepro"})["token"]
    print("login OK")

    # ---- 1. Análise por raio (fonte auto = Microsoft + OSM) ----------------
    j = req("POST", "/api/analyze/start", token=tok, json_body={
        "mode": "radius", "query": "Setor Bueno, Goiânia, Goiás",
        "radius_m": 500, "buildings_source": "auto",
        "profile": "condominio_casas",
    })
    r1 = wait_job(tok, j["job_id"], "raio")
    print(f"RAIO: {r1['count']} lotes, {r1['buildings']} edificações, "
          f"fonte={r1['buildings_source']}")
    assert r1["buildings"] > 200, "fonte auto deveria trazer centenas de footprints"
    assert r1["buildings_source"].startswith("ms"), "Microsoft deveria ser a fonte"

    # ---- 2. Cidade inteira --------------------------------------------------
    j = req("POST", "/api/analyze/start", token=tok, json_body={
        "mode": "city", "query": "Senador Canedo, Goiás, Brasil",
        "buildings_source": "auto", "profile": "loteamento",
        "min_area_m2": 1000,
    })
    r2 = wait_job(tok, j["job_id"], "cidade")
    print(f"CIDADE: {r2['area_km2']} km², {r2['blocks']} quadras, "
          f"{r2['buildings']} edificações, {r2['count']} lotes candidatos")
    assert r2["mode"] == "city" and r2["count"] > 0
    assert r2["boundary"]["features"], "limite municipal ausente"

    # ---- 3. Estudo de implantação (TestFit-like) ---------------------------
    feats = r2["results"]["features"]
    # pega um lote de porte médio (1.500–80.000 m²) para o estudo
    cand = [f for f in feats
            if 1_500 <= f["properties"]["area_m2"] <= 80_000] or feats
    lot = cand[0]
    lay = req("POST", "/api/layout/preview", token=tok, json_body={
        "geometry": lot["geometry"],
        "params": {"lot_width_m": 8, "lot_depth_m": 20},
    })
    s = lay["stats"]
    print(f"LAYOUT: {s['units']} casas, {s['density_units_ha']}/ha, "
          f"aproveitamento {s['efficiency_pct']}% em {s['site_area_m2']:.0f} m²")
    assert s["units"] > 0, "estudo não gerou casas"

    lay2 = req("POST", "/api/layout/preview", token=tok, json_body={
        "geometry": lot["geometry"],
        "params": {"lot_width_m": 14, "lot_depth_m": 28},
    })
    assert lay2["stats"]["units"] < s["units"], "parâmetros não mudaram o resultado"
    print(f"LAYOUT dinamico OK: 8x20 -> {s['units']} casas | 14x28 -> {lay2['stats']['units']}")

    # salva o estudo na ficha do lote
    pid = r2["project_id"]
    saved = req("PATCH", f"/api/projects/{pid}/lots/{lot['properties']['id']}",
                token=tok, json_body={"layout": {
                    "params": {"lot_width_m": 8, "lot_depth_m": 20}, "stats": s}})
    assert saved["layout"]["stats"]["units"] == s["units"]
    print("estudo salvo na ficha OK")

    print("\nSMOKE V2: PASSOU [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
