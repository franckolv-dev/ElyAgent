"""C4-3 — learned_skills.promoted_at pour la fenêtre de grâce d'injection.

Revision ID: 0021_skill_promoted_at
Revises: 0020_incident_dedup
Create Date: 2026-07-20

Un skill fraîchement promu a use_count=0 → dernier au tri top-N du bloc
<learned_skills> → coupé du prompt en premier (cold-start vécu en prod le
19/07 avec levenshtein_distance). La fenêtre de grâce (7 j) garantit son
injection le temps qu'il accumule de l'usage — elle a besoin de la date de
promotion, que personne ne stockait.

Backfill : pour les rows déjà ACTIVE, ``updated_at`` est la meilleure borne
disponible (la promotion est le dernier write pour un skill jamais utilisé ;
pour les autres c'est plus récent que la promotion réelle → grâce au pire
un peu plus longue, jamais plus courte). Les rows non-actives restent NULL
(la prochaine promotion posera la vraie date). DÉFENSIVE : n'ajoute que ce
qui manque.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_skill_promoted_at"
down_revision = "0020_incident_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("learned_skills"):
        return
    existing = {c["name"] for c in insp.get_columns("learned_skills")}
    if "promoted_at" not in existing:
        op.add_column(
            "learned_skills",
            sa.Column("promoted_at", sa.DateTime(), nullable=True),
        )
        conn.execute(sa.text(
            "UPDATE learned_skills SET promoted_at = updated_at "
            "WHERE status = 'active' AND promoted_at IS NULL"
        ))


def downgrade() -> None:
    # Colonne inerte si la grâce disparaît ; SQLite < 3.35 ne DROP pas
    # proprement → on la laisse (cf. 0013_mcp_auth, 0016, 0017, 0020).
    pass
