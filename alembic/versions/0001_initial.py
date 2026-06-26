"""initial schema — projects, lots, lot_crm, users (Fase 2a)

Revision ID: 0001
Revises:
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text()),
        sa.Column("picture", sa.Text()),
        sa.Column("google_sub", sa.Text(), unique=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=12), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_detect", postgresql.JSONB()),
    )

    op.create_table(
        "lots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(length=12),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("area_m2", sa.Float()),
        sa.Column("occupation", sa.Float()),
        sa.Column("potential", sa.Text()),
        sa.Column("color", sa.Text()),
        sa.Column("zoning", sa.Text()),
        sa.Column("lat", sa.Float()),
        sa.Column("lon", sa.Float()),
        sa.Column("street_view", sa.Text()),
        sa.Column("score", sa.Float()),
        sa.Column("grade", sa.Text()),
        sa.Column("slope_pct", sa.Float()),
        sa.Column("elev_range_m", sa.Float()),
        sa.Column("frontage_m", sa.Float()),
        sa.Column("compactness", sa.Float()),
        sa.Column("flags", sa.Text()),
        sa.Column("score_breakdown", sa.Text()),
        sa.Column("geom_wkb", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lots_project_id", "lots", ["project_id"])

    op.create_table(
        "lot_crm",
        sa.Column("lot_id", sa.BigInteger(),
                  sa.ForeignKey("lots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("matricula", sa.Text()),
        sa.Column("inscricao", sa.Text()),
        sa.Column("proprietario", sa.Text()),
        sa.Column("contato", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("notas", sa.Text()),
        sa.Column("layout", postgresql.JSONB()),
        sa.Column("bolha", postgresql.JSONB()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
    )


def downgrade() -> None:
    op.drop_table("lot_crm")
    op.drop_index("ix_lots_project_id", table_name="lots")
    op.drop_table("lots")
    op.drop_table("projects")
    op.drop_table("users")
