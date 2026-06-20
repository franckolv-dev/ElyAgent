"""Client MCP universel — Lot 0 : modèle de données.

Revision ID: 0012_mcp_client_v2
Revises: 0011_api_keys
Create Date: 2026-06-20

Étend ``mcp_servers`` (args/cwd, portée+propriété, confiance, kill switch,
handshake+santé) et crée le catalogue ``mcp_tools`` + l'ACL
``mcp_tool_permissions``. Ces deux tables sont le substrat du bridge (J3)
et de la policy (J4) — créées maintenant pour ne pas multiplier les
migrations.

DÉFENSIVE (cf. 0007-0011) : les installs fraîches obtiennent tout via
``Base.metadata.create_all`` ; on n'ajoute ici que ce qui manque sur une
base existante. Idempotent (ré-exécutable sans erreur).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_mcp_client_v2"
down_revision = "0011_api_keys"
branch_labels = None
depends_on = None


# Nouvelles colonnes de mcp_servers : (nom, type, server_default).
# server_default backfill les lignes existantes (serveurs déjà approuvés
# par l'admin → trust_state='active', health_state='unknown', etc.).
_SERVER_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object | None], ...] = (
    ("args_json", sa.Text(), None),
    ("cwd", sa.Text(), None),
    ("scope", sa.String(), sa.text("'instance'")),
    ("owner_user_id", sa.String(), None),
    ("kill_switch", sa.Boolean(), sa.text("0")),
    ("trust_state", sa.String(), sa.text("'active'")),
    ("protocol_version", sa.String(), None),
    ("server_info_json", sa.Text(), None),
    ("capabilities_json", sa.Text(), None),
    ("health_state", sa.String(), sa.text("'unknown'")),
    ("last_connected_at", sa.DateTime(timezone=True), None),
    ("last_error_code", sa.String(), None),
    ("updated_at", sa.DateTime(timezone=True), None),
)


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # ── 1. Étendre mcp_servers (additif, idempotent) ───────────────────
    if insp.has_table("mcp_servers"):
        existing = {c["name"] for c in insp.get_columns("mcp_servers")}
        for name, type_, default in _SERVER_COLUMNS:
            if name in existing:
                continue
            col = sa.Column(name, type_, nullable=True, server_default=default)
            op.add_column("mcp_servers", col)

    # ── 2. Catalogue des outils ────────────────────────────────────────
    if not insp.has_table("mcp_tools"):
        op.create_table(
            "mcp_tools",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "server_id", sa.String(36),
                sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("remote_name", sa.String(), nullable=False),
            sa.Column("local_name", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("input_schema_json", sa.Text(), nullable=True),
            sa.Column("output_schema_json", sa.Text(), nullable=True),
            sa.Column("annotations_json", sa.Text(), nullable=True),
            sa.Column("definition_hash", sa.String(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("risk_level", sa.String(), nullable=False, server_default=sa.text("'medium'")),
            sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_mcp_tools_server_id", "mcp_tools", ["server_id"])
        op.create_index("ix_mcp_tools_local_name", "mcp_tools", ["local_name"], unique=True)

    # ── 3. ACL par (user, serveur, outil) ──────────────────────────────
    if not insp.has_table("mcp_tool_permissions"):
        op.create_table(
            "mcp_tool_permissions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id", sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "server_id", sa.String(36),
                sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tool_id", sa.String(36),
                sa.ForeignKey("mcp_tools.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("decision", sa.String(), nullable=False, server_default=sa.text("'ask'")),
            sa.Column("data_policy", sa.String(), nullable=True),
            sa.Column("granted_by", sa.String(), nullable=True),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_mcp_tool_permissions_lookup",
            "mcp_tool_permissions",
            ["user_id", "server_id", "tool_id"],
        )


def downgrade() -> None:
    # Tables ajoutées : on les retire. Les colonnes ajoutées à mcp_servers
    # restent (SQLite ne sait pas DROP COLUMN proprement avant 3.35 et
    # elles sont inertes si le code v2 n'est plus là).
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("mcp_tool_permissions"):
        op.drop_table("mcp_tool_permissions")
    if insp.has_table("mcp_tools"):
        op.drop_table("mcp_tools")
