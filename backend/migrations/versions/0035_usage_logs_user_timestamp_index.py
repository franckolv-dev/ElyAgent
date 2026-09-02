"""Index composite (user_id, timestamp) sur usage_logs.

Revision ID: 0035_usage_logs_user_timestamp_index
Revises: 0034_mission_provider_retries
Create Date: 2026-09-02

L'audit du 02/09. Le modele indexait `user_id` et `timestamp`, chacun de son
cote. Les six lecteurs de la table, eux, filtrent toujours sur les DEUX :

    where user_id = ? and timestamp >= ?

cinq agregations de services/analytics_service.py (resume, usage quotidien,
usage par skill, stats HITL, ventilation par fournisseur) et le garde-budget
de services/budget_guard.py, qui passe a chaque tour.

Deux index a une colonne ne valent pas un index a deux colonnes : le planeur
n'en retient qu'un, prend celui de `user_id`, puis balaye toutes les lignes de
l'utilisateur pour n'en garder qu'une fenetre de dates. 11 280 lignes en prod
au moment de l'audit, et la table ne fait que grossir.

L'ordre des colonnes n'est pas decoratif : la colonne d'EGALITE (`user_id`)
vient avant celle d'INTERVALLE (`timestamp`). L'inverse ne servirait qu'aux
requetes globales, qui n'existent pas ici.

Les deux index simples sont CONSERVES : `timestamp` seul sert la retention
(services/retention.py, purge par date, tous utilisateurs confondus).
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_usage_logs_user_timestamp_index"
down_revision = "0034_mission_provider_retries"
branch_labels = None
depends_on = None

_TABLE = "usage_logs"
_INDEX = "ix_usage_logs_user_timestamp"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    # Defensive : une base creee par `create_all` porte deja l'index du
    # modele quand cette revision passe (le boot stampe la baseline puis
    # migre). Le reposer leverait « index already exists ».
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        return
    op.create_index(_INDEX, _TABLE, ["user_id", "timestamp"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if _INDEX not in {i["name"] for i in insp.get_indexes(_TABLE)}:
        return
    op.drop_index(_INDEX, table_name=_TABLE)
