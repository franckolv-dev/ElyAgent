"""Indicateur d'état d'exécution des tâches planifiées (13/06).

Revision ID: 0007_scheduled_task_status
Revises: 0006_vault_verifier
Create Date: 2026-06-13

Deux colonnes nullables sur scheduled_tasks : ``last_status``
("running"/"success"/"error"/NULL) et ``last_run_started_at``. Donnent à
l'UI un retour visible (en cours / réussi / échec / jamais) — avant,
l'utilisateur ne savait pas si une tâche tournait, avait fini ou planté.

DÉFENSIVE (convention d'adoption hybride, cf. 0002/0005/0006) : les installs
fraîches ont déjà les colonnes via create_all.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_scheduled_task_status"
down_revision = "0006_vault_verifier"
branch_labels = None
depends_on = None

_TABLE = "scheduled_tasks"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table(_TABLE):
        return
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "last_status" not in cols:
            batch.add_column(sa.Column("last_status", sa.String(16), nullable=True))
        if "last_run_started_at" not in cols:
            batch.add_column(sa.Column("last_run_started_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("last_run_started_at")
        batch.drop_column("last_status")
