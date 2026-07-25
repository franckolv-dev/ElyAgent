"""V0-2 — table hitl_requests (les validations survivent au redémarrage).

Revision ID: 0023_hitl_persistence
Revises: 0022_anticipation_suggestions
Create Date: 2026-07-25

Audit Opus 5 §4.6 : l'état HITL vivait dans un dict en mémoire. Un
redémarrage pendant une mission de nuit perdait toutes les demandes en
attente, et la décision prise ensuite depuis le téléphone tombait dans le
vide. DÉFENSIVE : ne crée que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_hitl_persistence"
down_revision = "0022_anticipation_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("hitl_requests"):
        return
    op.create_table(
        "hitl_requests",
        sa.Column("action_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    # La cloche de l'UI ne lit que « les demandes encore actionnables de CET
    # utilisateur » — c'est exactement cet index.
    op.create_index("ix_hitl_requests_user_status",
                    "hitl_requests", ["user_id", "status"])


def downgrade() -> None:
    # Table inerte si la fonctionnalité disparaît — on la laisse
    # (cf. politique 0013/0016/0017/0020/0021/0022).
    pass
