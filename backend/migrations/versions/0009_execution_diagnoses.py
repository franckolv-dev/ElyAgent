"""Boucle d'auto-diagnostic J3 — table execution_diagnoses.

Revision ID: 0009_execution_diagnoses
Revises: 0008_execution_outcomes
Create Date: 2026-06-14

Hypothèse de cause + catégorie pour une exécution douteuse/échouée (maillon 2).
Voir ``app/models/execution_diagnosis.py``.

DÉFENSIVE (cf. 0007/0008) : installs fraîches ont déjà la table via
``Base.metadata.create_all`` ; on ne la crée que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_execution_diagnoses"
down_revision = "0008_execution_outcomes"
branch_labels = None
depends_on = None

_TABLE = "execution_diagnoses"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "execution_outcome_id", sa.Integer(),
            sa.ForeignKey("execution_outcomes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=True),
        sa.Column("supporting_signals", sa.Text(), nullable=True),
        sa.Column("critic_model", sa.String(120), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_execution_diagnoses_execution_outcome_id", _TABLE,
        ["execution_outcome_id"], unique=True,
    )
    op.create_index("ix_execution_diagnoses_user_id", _TABLE, ["user_id"])
    op.create_index("ix_execution_diagnoses_status", _TABLE, ["status"])
    op.create_index("ix_execution_diagnoses_category", _TABLE, ["category"])
    op.create_index("ix_execution_diagnoses_created_at", _TABLE, ["created_at"])
    op.create_index(
        "ix_execution_diagnoses_user_status", _TABLE, ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
