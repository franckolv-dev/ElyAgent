"""Boucle d'auto-diagnostic J5 — table proposed_patches (voie C).

Revision ID: 0010_proposed_patches
Revises: 0009_execution_diagnoses
Create Date: 2026-06-14

Correctif config/prompt PROPOSÉ par Ely, validable + applicable + réversible.
Voir ``app/models/proposed_patch.py``.

DÉFENSIVE (cf. 0007/0008/0009) : installs fraîches ont déjà la table via
``Base.metadata.create_all`` ; on ne la crée que si elle manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_proposed_patches"
down_revision = "0009_execution_diagnoses"
branch_labels = None
depends_on = None

_TABLE = "proposed_patches"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "execution_diagnosis_id", sa.Integer(),
            sa.ForeignKey("execution_diagnoses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("target_type", sa.String(24), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("field", sa.String(32), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("critic_model", sa.String(120), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_proposed_patches_execution_diagnosis_id", _TABLE,
        ["execution_diagnosis_id"],
    )
    op.create_index("ix_proposed_patches_user_id", _TABLE, ["user_id"])
    op.create_index("ix_proposed_patches_status", _TABLE, ["status"])
    op.create_index("ix_proposed_patches_created_at", _TABLE, ["created_at"])


def downgrade() -> None:
    op.drop_table(_TABLE)
