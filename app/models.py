"""Models ORM (Fase 2 — Opção A).

- `projects`/`lots`/`lot_crm`: estado de negócio (substitui meta.json/results.gpkg/lots.json).
- `users`: criado já p/ a Fase 2b (Google OAuth); na 2a fica vazio.

Geometrias de INPUT (aoi/buildings/zoning) continuam em arquivo .gpkg — só o
LOTE detectado (results) vai pro banco, como WKB em `lots.geom_wkb`.

Sem isolamento por usuário: `created_by`/`updated_by` são auditoria apenas.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    picture: Mapped[str | None] = mapped_column(Text)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    # Mantém o hex de 12 chars (compat com URLs/frontend).
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    last_detect: Mapped[dict | None] = mapped_column(JSONB)

    lots: Mapped[list["Lot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True)


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(12), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # índice original (ordenação)

    area_m2: Mapped[float | None] = mapped_column(Float)
    occupation: Mapped[float | None] = mapped_column(Float)
    potential: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    zoning: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    street_view: Mapped[str | None] = mapped_column(Text)

    # Enriquecimento/score (podem faltar)
    score: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(Text)
    slope_pct: Mapped[float | None] = mapped_column(Float)
    elev_range_m: Mapped[float | None] = mapped_column(Float)
    frontage_m: Mapped[float | None] = mapped_column(Float)
    compactness: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[str | None] = mapped_column(Text)
    score_breakdown: Mapped[str | None] = mapped_column(Text)  # JSON string (round-trip fiel)

    geom_wkb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # polígono em WKB (EPSG:4326)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="lots")
    crm: Mapped["LotCrm | None"] = relationship(
        back_populates="lot", cascade="all, delete-orphan", passive_deletes=True, uselist=False)


class LotCrm(Base):
    __tablename__ = "lot_crm"

    lot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lots.id", ondelete="CASCADE"), primary_key=True)
    matricula: Mapped[str | None] = mapped_column(Text)
    inscricao: Mapped[str | None] = mapped_column(Text)
    proprietario: Mapped[str | None] = mapped_column(Text)
    contato: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    notas: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[dict | None] = mapped_column(JSONB)   # estudo de implantação
    bolha: Mapped[dict | None] = mapped_column(JSONB)    # estudo do Motor de Bolhas (IA)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    lot: Mapped["Lot"] = relationship(back_populates="crm")
