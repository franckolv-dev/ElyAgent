"""Client MCP universel — J4 : authentification distante.

Revision ID: 0013_mcp_auth
Revises: 0012_mcp_client_v2
Create Date: 2026-06-20

Ajoute à ``mcp_servers`` le type d'auth + la référence opaque de credential
(le secret vit dans le Vault, jamais ici) + le header d'API key + l'exception
LAN. DÉFENSIVE : n'ajoute que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_mcp_auth"
down_revision = "0012_mcp_client_v2"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object | None], ...] = (
    ("auth_type", sa.String(), sa.text("'none'")),
    ("credential_ref", sa.String(), None),
    ("auth_header_name", sa.String(), None),
    ("allow_private_network", sa.Boolean(), sa.text("0")),
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
    # Colonnes inertes si le code v2 disparaît ; SQLite < 3.35 ne DROP pas
    # proprement → on les laisse.
    pass
