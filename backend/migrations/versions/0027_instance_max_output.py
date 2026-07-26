"""Plafond de tokens en sortie porté par l'instance LLM.

Revision ID: 0027_instance_max_output
Revises: 0026_instance_pricing_and_window
Create Date: 2026-07-26

`max_output_tokens` valait 4 096 en dur à douze endroits de llm_provider,
quand certains modèles en autorisent 65 536. Une réponse longue était coupée
net, sans erreur et sans avertissement.

NULLABLE : « non déclaré » laisse l'appelant choisir son défaut, plutôt que le
registre inventer un chiffre.
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_instance_max_output"
down_revision = "0026_instance_pricing_and_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("llm_instances"):
        return
    if "max_output_tokens" not in {c["name"] for c in insp.get_columns("llm_instances")}:
        op.add_column("llm_instances", sa.Column("max_output_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("llm_instances"):
        return
    if "max_output_tokens" in {c["name"] for c in insp.get_columns("llm_instances")}:
        op.drop_column("llm_instances", "max_output_tokens")
