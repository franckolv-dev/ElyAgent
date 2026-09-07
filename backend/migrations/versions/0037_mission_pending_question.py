"""Une mission libre peut poser une question et attendre la réponse.

Revision ID: 0037_mission_pending_question
Revises: 0036_scheduled_task_as_mission
Create Date: 2026-09-07

Mission « RDV » du 06/09/2026 : « si plusieurs créneaux sont libres,
demande-moi lequel ». Aucun outil ne permettait de demander ; le modèle a
réservé sans choix puis a tourné (217 actions, 3,7 M tokens). Ces deux
colonnes portent la question en attente (statut ``waiting_user``) et
l'heure où elle a été posée. NULL = rien en attente.
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_mission_pending_question"
down_revision = "0036_scheduled_task_as_mission"
branch_labels = None
depends_on = None

_TABLE = "missions"
_COLS = (
    ("pending_question", sa.Text()),
    ("question_asked_at", sa.DateTime()),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    existantes = {c["name"] for c in insp.get_columns(_TABLE)}
    for nom, typ in _COLS:
        if nom not in existantes:
            op.add_column(_TABLE, sa.Column(nom, typ, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    existantes = {c["name"] for c in insp.get_columns(_TABLE)}
    for nom, _typ in _COLS:
        if nom in existantes:
            op.drop_column(_TABLE, nom)
