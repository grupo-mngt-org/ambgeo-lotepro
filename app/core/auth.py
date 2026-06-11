"""Autenticação simples por token assinado (HMAC, stdlib).

Sem dependências externas. Suficiente para o MVP single-tenant (RNF03);
trocar por OAuth/JWT robusto no roadmap.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .. import config


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), config.SECRET_KEY.encode(), 100_000).hex()


def verify_credentials(username: str, password: str) -> bool:
    return hmac.compare_digest(username, config.AUTH_USER) and hmac.compare_digest(
        password, config.AUTH_PASSWORD
    )


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + config.TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> str | None:
    """Retorna o username se o token for válido e não expirado; senão None."""
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("sub")
    except Exception:
        return None
