"""Configuração via variáveis de ambiente (com defaults para desenvolvimento)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("LOTEPRO_DATA_DIR", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"

# Autenticação (RNF03). Em produção, defina via ambiente.
AUTH_USER = os.getenv("LOTEPRO_USER", "admin")
AUTH_PASSWORD = os.getenv("LOTEPRO_PASSWORD", "lotepro")
SECRET_KEY = os.getenv("LOTEPRO_SECRET", "dev-secret-troque-em-producao")
TOKEN_TTL_SECONDS = int(os.getenv("LOTEPRO_TOKEN_TTL", "28800"))  # 8h

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
