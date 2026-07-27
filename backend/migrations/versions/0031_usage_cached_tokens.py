"""Compteurs de cache de préfixe sur usage_logs.

Revision ID: 0031_usage_cached_tokens
Revises: 0030_restore_opus_cost
Create Date: 2026-07-27

Ely découpe son prompt système exprès pour maximiser le cache de préfixe, mais
`usage_metadata` remontait déjà `input_token_details.cache_read` et personne ne
le lisait. Stratégie soignée, aucun moyen de savoir si elle mord.

DEUX compteurs, pas un : la lecture est un succès, l'écriture un coût. Les
additionner masquerait un cache qui écrit sans jamais relire.
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_usage_cached_tokens"
down_revision = "0030_restore_opus_cost"
branch_labels = None
depends_on = None

_COLUMNS = ("cached_input_tokens", "cache_creation_tokens")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("usage_logs"):
        return
    existing = {c["name"] for c in insp.get_columns("usage_logs")}
    for name in _COLUMNS:
        if name not in existing:
            op.add_column("usage_logs",
                          sa.Column(name, sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("usage_logs"):
        return
    existing = {c["name"] for c in insp.get_columns("usage_logs")}
    for name in _COLUMNS:
        if name in existing:
            op.drop_column("usage_logs", name)
