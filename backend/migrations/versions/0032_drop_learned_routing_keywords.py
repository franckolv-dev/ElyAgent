"""Retrait de la table learned_routing_keywords — plus aucun lecteur.

Revision ID: 0032_drop_learned_routing_keywords
Revises: 0031_usage_cached_tokens
Create Date: 2026-07-29

La table alimentait la passe rapide du routeur, disparue avec `supervisor.py`
(V1 temps 2, #259). Mesuré le 29/07 avant suppression : **0 ligne** en
production, aucun appelant de `match_learned_keywords()`, et l'endpoint
`/api/settings/routing` sans aucun client dans le dépôt.

`create_all` ne sait pas supprimer une table : retirer le modèle suffit pour
les bases neuves, pas pour celles qui portent la table depuis mai. D'où cette
révision.

Le `downgrade` recrée la structure à l'identique — pas les données, qui
n'existaient pas.
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_drop_learned_routing_keywords"
down_revision = "0031_usage_cached_tokens"
branch_labels = None
depends_on = None

_TABLE = "learned_routing_keywords"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table(_TABLE):
        op.drop_table(_TABLE)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("rationale", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "keyword", "domain",
                            name="uq_learned_kw_user_term_domain"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_learned_kw_active_domain", _TABLE, ["active", "domain"])
    op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])
