"""Serveur MCP J1 — table api_keys (clés API personnelles).

Revision ID: 0011_api_keys
Revises: 0010_proposed_patches
Create Date: 2026-06-16

Clés API longue durée pour authentifier des clients non-navigateur (serveur
MCP d'Ely, scripts…). Voir ``app/models/api_key.py``.

DÉFENSIVE (cf. 0007-0010) : les installs fraîches ont déjà la table via
``Base.metadata.create_all`` ; on ne la crée que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_api_keys"
down_revision = "0010_proposed_patches"
branch_labels = None
depends_on = None

_TABLE = "api_keys"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("last_4", sa.String(4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", _TABLE, ["user_id"])
    op.create_index("ix_api_keys_key_hash", _TABLE, ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_table(_TABLE)
