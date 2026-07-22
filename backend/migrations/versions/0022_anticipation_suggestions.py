"""C5 — table anticipation_suggestions (mode suggestion, cadrage 22/07).

Revision ID: 0022_anticipation_suggestions
Revises: 0021_skill_promoted_at
Create Date: 2026-07-22

Le détecteur hebdo de récurrences (services/anticipation.py) propose des
tâches planifiées — une row par (user, pattern_hash), l'existence de la
row EST l'anti-spam : un pattern proposé/accepté/refusé n'est jamais
re-proposé. DÉFENSIVE : ne crée que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_anticipation_suggestions"
down_revision = "0021_skill_promoted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("anticipation_suggestions"):
        return
    op.create_table(
        "anticipation_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("pattern_hash", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="proposed"),
        sa.Column("suggested_prompt", sa.Text(), nullable=False),
        sa.Column("suggested_cadence", sa.String(40), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False,
                  server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_anticipation_suggestions_status",
                    "anticipation_suggestions", ["status"])
    op.create_index("ix_anticipation_user_pattern",
                    "anticipation_suggestions", ["user_id", "pattern_hash"],
                    unique=True)


def downgrade() -> None:
    # Table inerte si la fonctionnalité disparaît — on la laisse
    # (cf. politique 0013/0016/0017/0020/0021).
    pass
