"""Client MCP v2 — J5 : sandbox des serveurs stdio.

Revision ID: 0017_mcp_stdio_sandbox
Revises: 0016_mcp_oauth
Create Date: 2026-06-28

Ajoute à ``mcp_servers`` l'override de profil sandbox par serveur
(``sandbox_profile_json`` : {mem_bytes, nofile, fsize_bytes}, NON secret). La
colonne ``cwd`` existe déjà (modèle de données MCP v2) — J5 ne fait que la
câbler au spawn, aucune nouvelle colonne pour elle. DÉFENSIVE : n'ajoute que ce
qui manque. Rétrocompat : colonne nullable, défaut NULL ⇒ profil par défaut.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_mcp_stdio_sandbox"
down_revision = "0016_mcp_oauth"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object | None], ...] = (
    ("sandbox_profile_json", sa.Text(), None),
)


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("mcp_servers"):
        return
    existing = {c["name"] for c in insp.get_columns("mcp_servers")}
    for name, type_, default in _COLUMNS:
        if name not in existing:
            op.add_column("mcp_servers", sa.Column(name, type_, nullable=True, server_default=default))


def downgrade() -> None:
    # Colonne inerte si le code v2 disparaît ; SQLite < 3.35 ne DROP pas
    # proprement → on la laisse (cf. 0013_mcp_auth, 0016_mcp_oauth).
    pass
