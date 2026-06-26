"""Configuração via pydantic-settings (.env + variáveis de ambiente).

Substitui o loader `.env` caseiro. A superfície pública de módulo
(`config.DATA_DIR`, `config.OPENROUTER_MODELS`, `config.AUTH_USER`, …) é
preservada como aliases sobre `settings`, para não tocar nos consumidores
(`app/core/*.py` fazem `from .. import config`).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configurações da aplicação. Variáveis reais do SO têm prioridade sobre o .env."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Persistência (filesystem hoje; DB vem na Fase 2)
    data_dir: Path = Field(default=BASE_DIR / "data", validation_alias="LOTEPRO_DATA_DIR")

    # Autenticação single-user (RNF03)
    auth_user: str = Field("admin", validation_alias="LOTEPRO_USER")
    auth_password: str = Field("lotepro", validation_alias="LOTEPRO_PASSWORD")
    secret_key: str = Field("dev-secret-troque-em-producao", validation_alias="LOTEPRO_SECRET")
    token_ttl_seconds: int = Field(28800, validation_alias="LOTEPRO_TOKEN_TTL")  # 8h

    # Banco de dados — pronto para a Fase 2 (vazio = sem DB, persistência em arquivo)
    database_url: str = Field("", validation_alias="DATABASE_URL")

    # DataJud (CNJ) — chave PÚBLICA documentada pelo CNJ (igual para todos,
    # https://datajud-wiki.cnj.jus.br/api-publica/acesso). NÃO é segredo; fica
    # aqui só para configurabilidade/DRY (override via DATAJUD_API_KEY).
    datajud_api_key: str = Field(
        "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==",
        validation_alias="DATAJUD_API_KEY",
    )

    # IA — OpenRouter (Motor de Bolhas). Aceita nomes minúsculos (do .env do
    # projeto) e MAIÚSCULOS (ambiente do SO).
    openrouter_key: str = Field(
        "", validation_alias=AliasChoices("OPENROUTER_KEY", "open_router_key")
    )
    openrouter_url: str = Field(
        "https://openrouter.ai/api/v1/chat/completions",
        validation_alias=AliasChoices("OPENROUTER_URL", "open_router_url"),
    )
    # Timeout (s) do ÚLTIMO modelo da cadeia (o pago/garantido) — generoso.
    openrouter_timeout: float = Field(180, validation_alias="OPENROUTER_TIMEOUT")
    # Timeout (s) por modelo NÃO-final (free): rotaciona se estourar.
    openrouter_free_timeout: float = Field(40, validation_alias="OPENROUTER_FREE_TIMEOUT")
    # Prazo TOTAL da cadeia; esgotado, cai p/ o estudo determinístico.
    openrouter_deadline: float = Field(360, validation_alias="OPENROUTER_DEADLINE")

    # Modelos na ORDEM de fallback: open_router_model, _model2, … _model8.
    # A ordem É a prioridade: free primeiro, pago (garantido) por último.
    openrouter_model: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL", "open_router_model"))
    openrouter_model2: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL2", "open_router_model2"))
    openrouter_model3: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL3", "open_router_model3"))
    openrouter_model4: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL4", "open_router_model4"))
    openrouter_model5: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL5", "open_router_model5"))
    openrouter_model6: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL6", "open_router_model6"))
    openrouter_model7: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL7", "open_router_model7"))
    openrouter_model8: str = Field("", validation_alias=AliasChoices("OPENROUTER_MODEL8", "open_router_model8"))

    @property
    def openrouter_models(self) -> list[str]:
        out: list[str] = []
        for v in (
            self.openrouter_model, self.openrouter_model2, self.openrouter_model3,
            self.openrouter_model4, self.openrouter_model5, self.openrouter_model6,
            self.openrouter_model7, self.openrouter_model8,
        ):
            if v and v not in out:
                out.append(v)
        return out


settings = Settings()

# ---------------------------------------------------------------------------
# Aliases de módulo — compat com consumidores existentes (`config.X`).
# ---------------------------------------------------------------------------
DATA_DIR = settings.data_dir
PROJECTS_DIR = DATA_DIR / "projects"

AUTH_USER = settings.auth_user
AUTH_PASSWORD = settings.auth_password
SECRET_KEY = settings.secret_key
TOKEN_TTL_SECONDS = settings.token_ttl_seconds

DATABASE_URL = settings.database_url

DATAJUD_API_KEY = settings.datajud_api_key

OPENROUTER_KEY = settings.openrouter_key
OPENROUTER_MODELS = settings.openrouter_models
OPENROUTER_URL = settings.openrouter_url
OPENROUTER_TIMEOUT = settings.openrouter_timeout
OPENROUTER_FREE_TIMEOUT = settings.openrouter_free_timeout
OPENROUTER_DEADLINE = settings.openrouter_deadline

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
