"""Rétablit le coût Claude Opus, effacé à tort par 0029.

Revision ID: 0030_restore_opus_cost
Revises: 0029_only_paid_apis_cost
Create Date: 2026-07-26

La reprise 0029 neutralise les modèles dont plus aucune instance n'existe.
Franck avait pourtant nommé Anthropic parmi ses API payantes — mais il n'a plus
d'instance Opus configurée, ayant depuis basculé sur Haiku. Le critère
automatique a donc effacé 7,58 USD réellement dépensés, contre une déclaration
humaine explicite.

La leçon : un critère automatique ne sait pas qu'un modèle peut être retiré de
la configuration APRÈS avoir coûté. Quand le critère et la personne se
contredisent, c'est la personne qui a raison.

Le montant n'est pas inventé : le tarif appliqué est celui publié par Anthropic
pour Claude Opus 4.5 — 15 USD par million en entrée, 75 en sortie. Sur les
183 158 tokens d'entrée et 64 456 de sortie de la base réelle, il redonne
exactement les 7,58 USD stockés à l'origine.

`downgrade` sans objet.
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_restore_opus_cost"
down_revision = "0029_only_paid_apis_cost"
branch_labels = None
depends_on = None

# Tarif publié par Anthropic pour Claude Opus 4.5, en USD par million.
_OPUS_INPUT_PER_M = 15.0
_OPUS_OUTPUT_PER_M = 75.0


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("usage_logs"):
        return

    bind.execute(sa.text("""
        UPDATE usage_logs
           SET cost_usd = (COALESCE(input_tokens, 0) * :inp
                         + COALESCE(output_tokens, 0) * :outp) / 1000000.0
         WHERE model LIKE 'claude-opus%'
    """), {"inp": _OPUS_INPUT_PER_M, "outp": _OPUS_OUTPUT_PER_M})


def downgrade() -> None:
    """Sans objet : la valeur précédente était zéro, posée par erreur."""
