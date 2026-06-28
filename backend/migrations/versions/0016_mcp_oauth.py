"""Client MCP v2 — J1 : socle OAuth 2.1 / PKCE.

Revision ID: 0016_mcp_oauth
Revises: 0015_reversible_actions
Create Date: 2026-06-28

Ajoute à ``mcp_servers`` les métadonnées NON secrètes du flow OAuth (cache de
découverte RFC 9728/8414, client_id, scopes) + une référence opaque de secret
client (DCR confidentiel / serveur d'instance). Les tokens (access/refresh)
NE SONT PAS ici : ils vivent en bundle JSON dans le Vault du propriétaire
(label ``mcp::<slug>::oauth``). DÉFENSIVE : n'ajoute que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_mcp_oauth"
down_revision = "0015_reversible_actions"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object | None], ...] = (
    ("oauth_metadata_json", sa.Text(), None),
    ("oauth_client_id", sa.String(), None),
    ("oauth_client_secret_ref", sa.String(), None),
    ("oauth_scopes", sa.String(), None),
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
    # proprement → on les laisse (cf. 0013_mcp_auth).
    pass
