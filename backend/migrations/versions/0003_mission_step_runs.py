"""Sprint 4c J2 — table mission_step_runs (statuts par step/item).

Revision ID: 0003_mission_step_runs
Revises: 0002_mission_spec_yaml
Create Date: 2026-06-10

DÉFENSIVE (convention d'adoption hybride create_all + Alembic, cf. 0002) :
les installs fraîches ont déjà la table via create_all → vérif d'existence.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_mission_step_runs"
down_revision = "0002_mission_spec_yaml"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if sa.inspect(conn).has_table("mission_step_runs"):
        return
    op.create_table(
        "mission_step_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "mission_id", sa.String(),
            sa.ForeignKey("missions.id", ondelete="CASCADE"), index=True,
        ),
        sa.Column("step_id", sa.String(64), index=True),
        sa.Column("item_index", sa.Integer(), default=0),
        sa.Column("item_value", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), index=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index(
        "ix_mission_step_runs_lookup", "mission_step_runs",
        ["mission_id", "step_id", "item_index"], unique=True,
    )


def downgrade() -> None:
    op.drop_table("mission_step_runs")
