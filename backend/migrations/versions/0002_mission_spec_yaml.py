"""Sprint 4c J1 — colonne missions.spec_yaml (spec structurée V2).

Revision ID: 0002_mission_spec_yaml
Revises: 0001_baseline
Create Date: 2026-06-10

Première vraie révision depuis la baseline — la règle posée en v1.14.11
s'applique : les nouvelles colonnes passent par Alembic, plus par
``_safe_columns``. NULL = mission legacy « prompt monolithe » (goal seul).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_mission_spec_yaml"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DÉFENSIVE (convention d'adoption hybride create_all + Alembic) : une
    # install fraîche a déjà la colonne (create_all lit le modèle) puis est
    # stampée baseline et upgradée — on vérifie donc l'existence avant
    # d'ajouter. batch_alter_table : no-op transparent sur Postgres,
    # indispensable pour ALTER sur SQLite.
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("missions"):
        return  # base partielle (tests) — create_all posera la table complète
    cols = {c["name"] for c in insp.get_columns("missions")}
    if "spec_yaml" not in cols:
        with op.batch_alter_table("missions") as batch:
            batch.add_column(sa.Column("spec_yaml", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("missions") as batch:
        batch.drop_column("spec_yaml")
