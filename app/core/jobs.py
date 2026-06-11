"""Jobs em background (thread) com progresso consultável por polling.

Análises pesadas (cidade inteira, 1º download de footprints) rodam aqui para
o frontend mostrar estágio/percentual em vez de travar numa request síncrona.

Uso:
    job_id = jobs.start("analyze_city", fn, arg1, arg2)
    # fn recebe `progress(stage, pct, detail="")` como primeiro argumento e
    # devolve um dict JSON-serializável (vira `result` do job).
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_JOBS = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim() -> None:
    """Mantém só os jobs mais recentes (evita crescer sem limite)."""
    if len(_jobs) <= _MAX_JOBS:
        return
    done = [j for j in _jobs.values() if j["status"] in ("done", "error")]
    done.sort(key=lambda j: j["updated_at"])
    for j in done[: len(_jobs) - _MAX_JOBS]:
        _jobs.pop(j["id"], None)


def start(name: str, fn, *args, **kwargs) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "name": name, "status": "running",
            "stage": "Iniciando…", "progress": 0, "detail": "",
            "result": None, "error": None,
            "created_at": _now(), "updated_at": _now(),
        }
        _trim()

    def progress(stage: str, pct: float, detail: str = "") -> None:
        with _lock:
            j = _jobs.get(job_id)
            if j and j["status"] == "running":
                j.update(stage=stage, progress=round(min(99.0, max(0.0, pct)), 1),
                         detail=detail, updated_at=_now())

    def runner() -> None:
        try:
            result = fn(progress, *args, **kwargs)
            with _lock:
                _jobs[job_id].update(status="done", progress=100, stage="Concluído",
                                     result=result, updated_at=_now())
        except Exception as exc:
            with _lock:
                _jobs[job_id].update(status="error", error=str(exc), updated_at=_now())
            traceback.print_exc()

    threading.Thread(target=runner, name=f"job-{name}-{job_id}", daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None
