"""Sprint 4d J1 — colonne tool_origin sur error_log + hitl_refusals.

Revision ID: 0005_tool_origin
Revises: 0004_step_run_answer
Create Date: 2026-06-10

"learned" | "builtin" | NULL (rows pré-J1). Sert aux gates de graduation
(stats par learned tool sans JOIN fragile sur learned_skills).

DÉFENSIVE (convention d'adoption hybride, cf. 0002) : les installs
fraîches ont déjà la colonne via create_all.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_tool_origin"
down_revision = "0004_step_run_answer"
branch_labels = None
depends_on = None

_TABLES = ("error_log", "hitl_refusals")


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    for table in _TABLES:
        if not insp.has_table(table):
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "tool_origin" not in cols:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("tool_origin", sa.String(16), nullable=True))
            op.create_index(f"ix_{table}_tool_origin", table, ["tool_origin"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_tool_origin", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("tool_origin")
