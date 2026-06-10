"""Sprint 4c J3 — colonne mission_step_runs.answer (réponse ask_user).

Revision ID: 0004_step_run_answer
Revises: 0003_mission_step_runs
Create Date: 2026-06-10

DÉFENSIVE (convention d'adoption hybride, cf. 0002) : les installs
fraîches ont déjà la colonne via create_all.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_step_run_answer"
down_revision = "0003_mission_step_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("mission_step_runs"):
        return
    cols = {c["name"] for c in insp.get_columns("mission_step_runs")}
    if "answer" not in cols:
        with op.batch_alter_table("mission_step_runs") as batch:
            batch.add_column(sa.Column("answer", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mission_step_runs") as batch:
        batch.drop_column("answer")
