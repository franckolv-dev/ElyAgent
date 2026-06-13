"""Audit sécurité 13/06 (M3) — vérificateur de mot de passe sur vault_config.

Revision ID: 0006_vault_verifier
Revises: 0005_tool_origin
Create Date: 2026-06-13

Deux colonnes nullables : ``verifier`` (sentinelle chiffrée AES-GCM) et
``verifier_nonce``. Permet de vérifier le mot de passe maître MÊME quand le
vault est vide — avant, un vault sans entrée acceptait n'importe quel mot de
passe (rien à déchiffrer). Nullable : les vaults legacy restent lisibles et
se voient poser un vérificateur au premier unlock réussi.

DÉFENSIVE (convention d'adoption hybride, cf. 0002/0005) : les installs
fraîches ont déjà les colonnes via create_all.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_vault_verifier"
down_revision = "0005_tool_origin"
branch_labels = None
depends_on = None

_TABLE = "vault_config"
_COLS = ("verifier", "verifier_nonce")


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table(_TABLE):
        return
    cols = {c["name"] for c in insp.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "verifier" not in cols:
            batch.add_column(sa.Column("verifier", sa.LargeBinary(), nullable=True))
        if "verifier_nonce" not in cols:
            batch.add_column(sa.Column("verifier_nonce", sa.LargeBinary(12), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for col in _COLS:
            batch.drop_column(col)
