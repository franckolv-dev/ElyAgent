"""Missions autonomes — J1 : mandat d'autonomie par mission.

Revision ID: 0018_mission_mandate
Revises: 0017_mcp_stdio_sandbox
Create Date: 2026-07-11

Ajoute à ``missions`` le mandat d'autonomie (cadrage :
docs_internes/cadrage_missions_autonomes.md) : ``mandate_json`` (forme
canonique du bloc `mandate:` de la spec v2, NON secret) et
``autonomy_state`` (cycle de vie du mandat, J1 : 'pending_validation').
DÉFENSIVE : n'ajoute que ce qui manque. Rétrocompat : colonnes nullable,
défaut NULL ⇒ mission supervisée, comportement inchangé.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_mission_mandate"
down_revision = "0017_mcp_stdio_sandbox"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object | None], ...] = (
    ("mandate_json", sa.Text(), None),
    ("autonomy_state", sa.String(20), None),
)


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("missions"):
        return
    existing = {c["name"] for c in insp.get_columns("missions")}
    for name, type_, default in _COLUMNS:
        if name not in existing:
            op.add_column("missions", sa.Column(name, type_, nullable=True, server_default=default))


def downgrade() -> None:
    # Colonnes inertes si J2+ n'arrive jamais ; SQLite < 3.35 ne DROP pas
    # proprement → on les laisse (même politique que 0013/0016/0017).
    pass
