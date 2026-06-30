"""Camada de banco — SQLAlchemy síncrono (Postgres).

Geoprocessamento é CPU-bound; seguimos o padrão síncrono (sem asyncpg),
igual ao mngpt-distributed-ai.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,   # recicla conexões mortas (restart do Postgres)
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Dependency do FastAPI: uma sessão por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
