"""Compteur de reports de tick sur panne passagere du fournisseur LLM.

Revision ID: 0034_mission_provider_retries
Revises: 0033_scheduled_task_allow_silent
Create Date: 2026-08-31

L'incident du 31/08. La mission « Prospection STE Print » venait d'etendre son
`foreach` en 5 societes, d'ecrire son historique et de creer son tableur.
Vingt-cinq minutes de travail, effacees par :

    graph crashed: {'message': 'Provider returned error', 'code': 429}

Une limite de debit n'est pas un bug : elle se resout toute seule en
attendant. Le heartbeat traitait pourtant toute exception de la meme facon,
`fail_mission`, sans distinguer « le graphe est casse » de « le fournisseur
nous demande de ralentir ».

Le tick est desormais REPORTE dans ce cas. Cette colonne borne le report :
un fournisseur durablement en panne laisserait sinon une mission « en cours »
pour toujours, ce qui est pire qu'un echec franc parce que muet. Le compteur
se remet a zero au premier tick reussi.
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_mission_provider_retries"
down_revision = "0033_scheduled_task_allow_silent"
branch_labels = None
depends_on = None

_TABLE = "missions"
_COL = "provider_retries"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    # server_default : les missions DEJA en base doivent recevoir 0. Un
    # `default` Python ne vaut que pour les insertions futures et laisserait
    # NULL, sur quoi la comparaison au plafond ne dirait rien de bon.
    op.add_column(
        _TABLE,
        sa.Column(_COL, sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _COL not in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    op.drop_column(_TABLE, _COL)
