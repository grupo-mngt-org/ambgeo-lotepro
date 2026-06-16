"""Configuração via variáveis de ambiente (com defaults para desenvolvimento)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carrega o .env para os.environ (sem dependência externa).

    Só define chaves AINDA não presentes no ambiente — variáveis reais do SO
    (ex.: em produção/Render) têm prioridade sobre o arquivo.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("LOTEPRO_DATA_DIR", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"

# Autenticação (RNF03). Em produção, defina via ambiente.
AUTH_USER = os.getenv("LOTEPRO_USER", "admin")
AUTH_PASSWORD = os.getenv("LOTEPRO_PASSWORD", "lotepro")
SECRET_KEY = os.getenv("LOTEPRO_SECRET", "dev-secret-troque-em-producao")
TOKEN_TTL_SECONDS = int(os.getenv("LOTEPRO_TOKEN_TTL", "28800"))  # 8h

# ---------------------------------------------------------------------------
# IA — OpenRouter (Motor de Bolhas). Chave + modelos vêm do .env. Os nomes
# minúsculos (open_router_*) são os usados no .env do projeto; aceitamos também
# os equivalentes MAIÚSCULOS caso definidos no ambiente do SO.
# ---------------------------------------------------------------------------
def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


OPENROUTER_KEY = _env("OPENROUTER_KEY", "open_router_key")


def _model_list() -> list[str]:
    """Modelos na ORDEM do .env: open_router_model, _model2, _model3, _model4…

    A ordem É a prioridade de fallback: ponha os modelos free primeiro e o
    modelo pago (garantido) por último — o sistema rotaciona até um responder.
    """
    out: list[str] = []
    for suf in ("", "2", "3", "4", "5", "6", "7", "8"):
        v = _env(f"OPENROUTER_MODEL{suf}", f"open_router_model{suf}")
        if v and v not in out:
            out.append(v)
    return out


OPENROUTER_MODELS = _model_list()
OPENROUTER_URL = _env("OPENROUTER_URL",
                      default="https://openrouter.ai/api/v1/chat/completions")
# Timeout (s) do ÚLTIMO modelo da cadeia (o pago/garantido) — generoso.
OPENROUTER_TIMEOUT = float(_env("OPENROUTER_TIMEOUT", default="180"))
# Timeout (s) por modelo NÃO-final (free): se não devolver JSON válido nesse
# tempo (lentidão/erro), rotaciona para o próximo. Mantém a rotação ágil.
OPENROUTER_FREE_TIMEOUT = float(_env("OPENROUTER_FREE_TIMEOUT", default="40"))
# Prazo TOTAL da cadeia; esgotado, cai p/ o estudo determinístico (raro c/ pago no fim).
OPENROUTER_DEADLINE = float(_env("OPENROUTER_DEADLINE", default="360"))

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
