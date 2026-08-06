"""`[SILENT]` devient une permission portée par la tâche, plus une consigne.

Revision ID: 0033_scheduled_task_allow_silent
Revises: 0032_drop_learned_routing_keywords
Create Date: 2026-08-06

L'incident du 06/08. La tâche « Propositions LinkedIn PAO et InDesign » a
rendu `[SILENT]`, et le planificateur a supprimé la conversation avant toute
livraison : aucun post, aucune proposition, et plus aucune trace de ce qui
s'était passé.

Le garde-fou existait — dans le PROMPT :

    « Pour une tâche qui produit toujours un livrable (briefing, résumé,
      rapport quotidien), NE l'utilise JAMAIS — livre le résultat. »

C'est une phrase adressée au modèle, pas un verrou (invariant 3 du dépôt). Le
planificateur, lui, acceptait `[SILENT]` de n'importe quelle tâche.

Cette colonne le rend décidable côté code. **Défaut `false`** : on échoue
fermé, une tâche qui n'a rien demandé livre toujours son résultat. Les tâches
de veille existantes doivent être cochées explicitement — c'est voulu, car le
défaut inverse rendrait muettes des tâches à livrable au premier `[SILENT]`
mal placé, exactement la panne qu'on corrige.
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_scheduled_task_allow_silent"
down_revision = "0032_drop_learned_routing_keywords"
branch_labels = None
depends_on = None

_TABLE = "scheduled_tasks"
_COL = "allow_silent"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _COL in {c["name"] for c in insp.get_columns(_TABLE)}:
        return
    # server_default='0' et non `default` : les lignes DÉJÀ en base doivent
    # recevoir une valeur. Un `default` Python ne vaut que pour les insertions
    # futures et laisserait NULL partout, que le code lirait comme faux — vrai
    # ici par chance, mais on ne s'appuie pas sur une coïncidence.
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
