"""Substrat de confiance — J3 : table idempotency_records.

Revision ID: 0014_idempotency_records
Revises: 0013_mcp_auth
Create Date: 2026-06-20

Store d'idempotence : une action (par l'empreinte de son plan, J2) n'est pas
ré-exécutée tant que son enregistrement n'a pas expiré.

DÉFENSIVE (cf. 0007-0013) : install fraîche via Base.metadata.create_all ; on
ne crée la table que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_idempotency_records"
down_revision = "0013_mcp_auth"
branch_labels = None
depends_on = None

_TABLE = "idempotency_records"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("capability_id", sa.String(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_idempotency_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    op.drop_table(_TABLE)
