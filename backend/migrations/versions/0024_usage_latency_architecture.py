"""V2-1 — usage_logs : latence + architecture d'agent.

Revision ID: 0024_usage_latency_architecture
Revises: 0023_hitl_persistence
Create Date: 2026-07-25

Vague 2 (`docs_internes/v2_mesure_architectures.md`) : 8 938 lignes d'usage
en production, et aucune ne dit combien de temps le tour a pris ni quelle
architecture l'a servi. Le critère n° 1 de la décision mono-agent /
sous-agents — la latence — n'était donc pas mesurable.

Les deux colonnes sont NULLABLES : les 8 938 lignes historiques restent
honnêtement « non mesurées » plutôt que rétro-remplies à 0.
DÉFENSIVE : n'ajoute que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_usage_latency_architecture"
down_revision = "0023_hitl_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("usage_logs"):
        return
    existing = {c["name"] for c in insp.get_columns("usage_logs")}
    if "latency_ms" not in existing:
        op.add_column("usage_logs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    if "architecture" not in existing:
        op.add_column("usage_logs", sa.Column("architecture", sa.String(32), nullable=True))
        # Le banc agrège par architecture — c'est le seul accès non trivial.
        op.create_index("ix_usage_logs_architecture", "usage_logs", ["architecture"])


def downgrade() -> None:
    # Colonnes inertes si la fonctionnalité disparaît — on les laisse
    # (cf. politique 0013/0016/0017/0020/0021/0022/0023).
    pass
