# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/_user_cleanup.py
# @brief      Supprimer un utilisateur de test SANS énumérer ses tables filles.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Nettoyage d'un utilisateur de test, dérivé du SCHÉMA et non d'une liste.

⚠️ POURQUOI CE MODULE EXISTE (02/09/2026). Trois fois de suite, une fixture a
laissé une ligne fille derrière elle et fait échouer la CI sur
``FOREIGN KEY constraint failed`` en supprimant l'utilisateur :

  #354            le routeur oubliait des tables filles d'une mission
  ``1c632a2``     la fixture du 429 en nettoyait deux sur cinq
  celle-ci        elle en nettoyait cinq, et oubliait la CONVERSATION de
                  notification que ``_notify_terminal`` crée à la fin d'une
                  mission — son commentaire annonçait pourtant « les CINQ
                  tables filles »

Vingt-sept tables référencent ``users``. Toute liste écrite à la main périme au
prochain modèle ajouté, et le défaut ne se voit qu'en CI. On lit donc le
métamodèle : les clés étrangères SONT la liste, et elles sont toujours à jour.

⚠️ ``:memory:`` = UNE SEULE CONNEXION PARTAGÉE (16/09/2026, #404). Avec
``:memory:``, SQLAlchemy monte l'engine aiosqlite sur un ``StaticPool`` :
toutes les sessions se relaient sur la même connexion sqlite. Une tâche de
fond (``spawn``) qui ferme sa session émet un ROLLBACK qui efface l'écriture
encore non commitée d'une autre session — c'est ce qui rendait le test de
relance de mission instable. D'où le ``drain()`` en tête de ``purge_user`` :
on attend les tâches de fond avant de supprimer quoi que ce soit. Sur une base
FICHIER (``AsyncAdaptedQueuePool``), chaque session a sa connexion et le
problème n'existe pas — mais une tâche de fond peut alors ré-insérer une ligne
fille APRÈS le DELETE des enfants, d'où la contrainte de clé étrangère en CI.
"""
from __future__ import annotations

from sqlalchemy import delete, select

_TABLE_UTILISATEURS = "users"


def _colonnes_vers(table, cible: str) -> list[str]:
    """Colonnes de ``table`` qui pointent vers la table ``cible``."""
    return [fk.parent.name for fk in table.foreign_keys
            if fk.column.table.name == cible]


async def purge_user(uid: str) -> None:
    """Supprime tout ce qui appartient à ``uid``, puis l'utilisateur.

    Deux niveaux, ce qui suffit au schéma d'Ely : les tables qui référencent
    ``users`` directement, et leurs propres filles (``messages`` pointe vers
    ``conversations``, pas vers ``users``). Les tables sont parcourues à
    l'envers de l'ordre de dépendance, donc les enfants d'abord.

    Best-effort table par table, dans sa propre session : une table absente de
    ce build ne doit pas laisser la session en échec et abandonner le reste.
    """
    from app import models  # noqa: F401 — enregistre toutes les tables
    from app.database import Base, async_session
    from app.services.background_tasks import drain

    await drain()
    tables = list(reversed(Base.metadata.sorted_tables))
    directes = {
        t.name: _colonnes_vers(t, _TABLE_UTILISATEURS)[0]
        for t in tables
        if t.name != _TABLE_UTILISATEURS and _colonnes_vers(t, _TABLE_UTILISATEURS)
    }

    for table in tables:
        if table.name == _TABLE_UTILISATEURS:
            continue
        if table.name in directes:
            critere = table.c[directes[table.name]] == uid
        else:
            # Fille d'une table possédée : on cible par sous-requête sur le
            # parent, sans avoir à connaître le nom du lien.
            critere = None
            for fk in table.foreign_keys:
                parent = fk.column.table
                if parent.name in directes:
                    critere = table.c[fk.parent.name].in_(
                        select(fk.column).where(
                            parent.c[directes[parent.name]] == uid
                        )
                    )
                    break
            if critere is None:
                continue
        try:
            async with async_session() as db:
                await db.execute(delete(table).where(critere))
                await db.commit()
        except Exception:  # noqa: BLE001 — au mieux : une table ne bloque pas les autres
            continue

    from app.models.user import User
    async with async_session() as db:
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
            await db.commit()
