"""Fenêtre et tarifs portés par l'instance LLM.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-26

Ces valeurs vivaient dans des tables du CODE que l'utilisateur ne peut pas
éditer. Il ajoutait un modèle depuis l'interface, aucune table ne le savait, et
Ely tronquait son contexte à 8 192 tokens en facturant un tarif générique
inventé — sans une erreur, pendant des mois.

Colonnes NULLABLE : « non déclaré » doit rester distinct de « déclaré à zéro ».
Un modèle local à 0,0 est gratuit ; un modèle sans tarif est inconnu, et le
contrôle de réalité continue de le signaler.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_instance_pricing_and_window"
down_revision = "0025_usage_context_breakdown"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("context_window", sa.Integer()),
    ("input_price_per_million", sa.Float()),
    ("output_price_per_million", sa.Float()),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("llm_instances"):
        return
    existing = {c["name"] for c in insp.get_columns("llm_instances")}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column("llm_instances", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("llm_instances"):
        return
    existing = {c["name"] for c in insp.get_columns("llm_instances")}
    for name, _ in _COLUMNS:
        if name in existing:
            op.drop_column("llm_instances", name)
