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


# ---------------------------------------------------------------------------
# Login Google (Fase 2b). Verifica o id_token emitido pelo Google Identity
# Services no frontend, faz upsert do usuário e emite o token HMAC acima.
# Sem isolamento por usuário — todos veem todos os projetos; o User serve para
# identidade/auditoria.
# ---------------------------------------------------------------------------
def _allowed_google_domains() -> set[str]:
    return {d.strip().lower() for d in config.GOOGLE_ALLOWED_DOMAINS.split(",") if d.strip()}


def verify_google_token(id_token_str: str) -> dict:
    """Valida o id_token contra o GOOGLE_CLIENT_ID. Levanta ValueError se inválido."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    if not config.GOOGLE_CLIENT_ID:
        raise ValueError("Login Google não configurado (defina GOOGLE_CLIENT_ID).")
    idinfo = google_id_token.verify_oauth2_token(
        id_token_str, google_requests.Request(), config.GOOGLE_CLIENT_ID
    )
    if not idinfo.get("email_verified"):
        raise ValueError("E-mail Google não verificado.")
    return idinfo


def upsert_google_user(idinfo: dict) -> dict:
    """Cria/atualiza o usuário a partir do idinfo do Google. Retorna {email, name}."""
    from sqlalchemy import select

    from ..database import SessionLocal
    from ..models import User

    email = (idinfo.get("email") or "").lower()
    if not email:
        raise ValueError("Token Google sem e-mail.")
    domain = email.split("@")[-1]
    allowed = _allowed_google_domains()
    if allowed and domain not in allowed:
        raise ValueError(f"Domínio @{domain} não autorizado.")

    sub = idinfo.get("sub")
    name = idinfo.get("name") or email.split("@")[0]
    picture = idinfo.get("picture")

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(email=email, name=name, picture=picture, google_sub=sub)
            db.add(user)
        else:
            user.name, user.picture = name, picture
            if not user.google_sub:
                user.google_sub = sub
        db.commit()
    return {"email": email, "name": name}
