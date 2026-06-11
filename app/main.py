"""Lote Pro — aplicação FastAPI (API + frontend estático)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Lote Pro", version=__version__,
              description="Prospecção inteligente de áreas (terrenos vazios/subutilizados).")

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
