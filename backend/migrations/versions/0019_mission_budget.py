"""Missions autonomes — J3 : disjoncteurs (compteurs journaliers + snapshot pause).

Revision ID: 0019_mission_budget
Revises: 0018_mission_mandate
Create Date: 2026-07-11

Ajoute la table ``mission_daily_counters`` (compteurs persistés par
mission/jour — un restart backend ne remet pas les seuils D4 à zéro) et la
colonne ``missions.autonomy_pause_json`` (snapshot de la dernière pause
disjoncteur). Cadrage : docs_internes/cadrage_missions_autonomes.md (D4).
DÉFENSIVE : ne crée que ce qui manque. Rétrocompat : colonne nullable,
table vide ⇒ comportement inchangé.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_mission_budget"
down_revision = "0018_mission_mandate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if insp.has_table("missions"):
        existing = {c["name"] for c in insp.get_columns("missions")}
        if "autonomy_pause_json" not in existing:
            op.add_column("missions", sa.Column("autonomy_pause_json", sa.Text(), nullable=True))

    if not insp.has_table("mission_daily_counters"):
        op.create_table(
            "mission_daily_counters",
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("tool_actions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tool_ack", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("llm_ack", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("mission_id", "day"),
        )


def downgrade() -> None:
    # Table/colonne inertes si J3+ n'arrive jamais ; SQLite < 3.35 ne DROP pas
    # proprement → on les laisse (même politique que 0016/0017/0018).
    pass
