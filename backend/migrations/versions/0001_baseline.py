"""Baseline — schéma géré historiquement par create_all + _safe_columns.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-10

Cette révision est VOLONTAIREMENT vide : au 10 juin 2026, le schéma
complet est produit par ``Base.metadata.create_all`` + la liste
``_safe_columns`` de ``database.py`` (installs existantes comprises).
Le boot stampe les bases sur cette révision (``alembic_runner``) ; toute
évolution de schéma POSTÉRIEURE doit passer par une vraie révision
Alembic (``uv run alembic revision --autogenerate -m "..."``) au lieu
d'allonger ``_safe_columns``.
"""
from __future__ import annotations

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
