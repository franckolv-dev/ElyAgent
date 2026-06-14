"""Boucle d'auto-diagnostic J1 — table execution_outcomes.

Revision ID: 0008_execution_outcomes
Revises: 0007_scheduled_task_status
Create Date: 2026-06-14

Le « chaînon manquant » de la design note self-diagnostic-improvement-loop :
un verdict d'aboutissement réel (succeeded/dubious/failed) par exécution
automatique terminée, à côté du statut déclaré. Voir
``app/models/execution_outcome.py``.

DÉFENSIVE (convention d'adoption hybride, cf. 0002/0005/0006/0007) : les
installs fraîches ont déjà la table via ``Base.metadata.create_all`` au boot ;
on ne la (re)crée que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_execution_outcomes"
down_revision = "0007_scheduled_task_status"
branch_labels = None
depends_on = None

_TABLE = "execution_outcomes"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.String(100), nullable=True),
        sa.Column("mission_id", sa.String(), nullable=True),
        sa.Column("channel", sa.String(50), nullable=True),
        sa.Column("tier_llm", sa.String(8), nullable=True),
        sa.Column("model_used", sa.String(120), nullable=True),
        sa.Column("declared_status", sa.String(20), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("signals", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_execution_outcomes_user_id", _TABLE, ["user_id"])
    op.create_index("ix_execution_outcomes_source", _TABLE, ["source"])
    op.create_index("ix_execution_outcomes_source_id", _TABLE, ["source_id"])
    op.create_index("ix_execution_outcomes_channel", _TABLE, ["channel"])
    op.create_index("ix_execution_outcomes_tier_llm", _TABLE, ["tier_llm"])
    op.create_index("ix_execution_outcomes_outcome", _TABLE, ["outcome"])
    op.create_index("ix_execution_outcomes_created_at", _TABLE, ["created_at"])
    op.create_index(
        "ix_execution_outcomes_user_created", _TABLE, ["user_id", "created_at"]
    )
    op.create_index(
        "ix_execution_outcomes_source_outcome", _TABLE, ["source", "outcome"]
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
