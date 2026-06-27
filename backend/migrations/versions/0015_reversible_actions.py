"""Substrat de confiance — Reversible Action Journal : table reversible_actions.

Revision ID: 0015_reversible_actions
Revises: 0014_idempotency_records
Create Date: 2026-06-27

Journal des actions annulables : une action mutante dont le manifeste déclare
une `compensation` est enregistrée après succès, puis peut être compensée
(« annuler »).

DÉFENSIVE (cf. 0007-0014) : install fraîche via Base.metadata.create_all ; on
ne crée la table que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_reversible_actions"
down_revision = "0014_idempotency_records"
branch_labels = None
depends_on = None

_TABLE = "reversible_actions"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("capability_id", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column("compensation", sa.String(), nullable=False),
        sa.Column("compensation_args", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="recorded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reversible_actions_user_id", _TABLE, ["user_id"])
    op.create_index("ix_reversible_actions_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    op.drop_table(_TABLE)
