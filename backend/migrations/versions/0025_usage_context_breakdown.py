"""P2 — usage_logs.context_breakdown : d'où viennent les tokens d'un tour.

Revision ID: 0025_usage_context_breakdown
Revises: 0024_usage_latency_architecture
Create Date: 2026-07-25

Mesuré en production : certains tours pèsent 230 203 tokens d'entrée
(`desktop_search_files`), 175 232 (`browser_navigate`), et rien ne disait
lequel des postes — schémas d'outils, historique, résultat d'outil — les
portait. Cette colonne stocke la ventilation compacte (JSON plat) calculée
par `services/context_breakdown.py` (port de Hermes v0.19, MIT).

NULLABLE : les lignes historiques restent honnêtement « non ventilées »
plutôt que rétro-remplies. DÉFENSIVE : n'ajoute que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_usage_context_breakdown"
down_revision = "0024_usage_latency_architecture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("usage_logs"):
        return
    existing = {c["name"] for c in insp.get_columns("usage_logs")}
    if "context_breakdown" not in existing:
        op.add_column("usage_logs", sa.Column("context_breakdown", sa.Text(), nullable=True))


def downgrade() -> None:
    # Colonne inerte si la fonctionnalité disparaît — on la laisse
    # (cf. politique 0013 → 0024).
    pass
