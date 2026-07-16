"""Dédup des incidents auto-diagnostic — occurrences + last_seen_at.

Revision ID: 0020_incident_dedup
Revises: 0019_mission_budget
Create Date: 2026-07-16

Une tâche récurrente qui échoue de la même façon ouvrait un incident par
run (62+ doublons observés en prod). La garde anti-doublon cumule désormais
sur l'incident open canonique : ``occurrences`` (nombre de runs repliés —
backfill 1 pour les lignes existantes) + ``last_seen_at`` (dernier run vu,
NULL tant que jamais dédupliqué). Les doublons repliés passent
``status="merged"`` (valeur nouvelle, aucune colonne nécessaire).
DÉFENSIVE : n'ajoute que ce qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_incident_dedup"
down_revision = "0019_mission_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("execution_diagnoses"):
        return
    existing = {c["name"] for c in insp.get_columns("execution_diagnoses")}
    if "occurrences" not in existing:
        op.add_column(
            "execution_diagnoses",
            sa.Column("occurrences", sa.Integer(), nullable=False,
                      server_default=sa.text("1")),
        )
    if "last_seen_at" not in existing:
        op.add_column(
            "execution_diagnoses",
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    # Colonnes inertes si la dédup disparaît ; SQLite < 3.35 ne DROP pas
    # proprement → on les laisse (cf. 0013_mcp_auth, 0016, 0017).
    pass
