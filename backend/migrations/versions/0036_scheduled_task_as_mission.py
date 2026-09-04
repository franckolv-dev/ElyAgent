"""Une tâche planifiée peut lancer une MISSION au lieu d'un tour de chat.

Revision ID: 0036_scheduled_task_as_mission
Revises: 0035_usage_logs_user_timestamp_index
Create Date: 2026-09-04

« Nettoyage quotidien Gmail par catégories » (cron 12h30) échouait à chaque
tour sur la limite de récursion du chat : le tri d'une boîte ne tient pas
dans un tour. La mission, elle, a carnet, budgets et passages, mais pas de
récurrence. Cette colonne fait le pont : à l'heure dite, la tâche crée et
démarre une mission (objectif = son prompt, source ``scheduled_task``).

Défaut ``false`` : les tâches existantes ne changent pas de régime.
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_scheduled_task_as_mission"
down_revision = "0035_usage_logs_user_timestamp_index"
branch_labels = None
depends_on = None

_TABLE = "scheduled_tasks"
_COL = "as_mission"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.add_column(
        _TABLE,
        sa.Column(_COL, sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _COL not in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.drop_column(_TABLE, _COL)
