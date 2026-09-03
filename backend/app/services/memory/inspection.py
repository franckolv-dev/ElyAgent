# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/inspection.py
# @brief      Surface d'audit humain de la mémoire — parcourir et oublier.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# =============================================================================
"""Inspection de la mémoire typée — Sprint 2.5 §2.5.6.

Distincte de `MemoryRecallService`, et il faut que ça le reste :

- **recall** répond « qu'est-ce qui est PERTINENT pour cette requête » — c'est
  la voie du modèle, classée, seuillée, décayée.
- **inspection** répond « qu'est-ce qu'Ely retient de moi, EXACTEMENT » —
  c'est la voie de l'humain, exhaustive, paginée, non classée.

Faire servir l'audit par la recherche par pertinence donnerait une page qui
ment par omission : un souvenir sous le seuil de score n'apparaîtrait pas, et
l'utilisateur conclurait qu'il n'existe pas. C'est la faute que l'invariant
n°4 du dépôt nomme — un repli qui se présente comme nominal.

Les identifiants Qdrant remontent ici, alors que `MemoryHit` ne les porte pas :
sans eux, aucun bouton « oublier » n'est possible.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.memory._constants import (
    COLLECTION_CONSTRAINTS,
    COLLECTION_INTERACTIONS,
    COLLECTION_MEMORIES,
    COLLECTION_PREFERENCES,
)
from app.services.memory._infra import get_memory_infra
from app.services.memory.types import MemoryType

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryEntry:
    """Une entrée telle qu'on la MONTRE à l'utilisateur, avec son identifiant."""

    id: str
    type: MemoryType
    content: str
    created_at: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# Chaque famille inspectable → (collection Qdrant, champs texte par ordre de
# préférence). Une seule table, pour que « ajouter une famille » soit une
# ligne et non une cascade de `if`.
#
# `semantic_user` occupe DEUX collections (facts + preferences) — c'est
# l'héritage documenté dans semantic_user_store, pas un oubli.
_INSPECTABLE: dict[str, tuple[str, tuple[str, ...], MemoryType]] = {
    "fact": (COLLECTION_MEMORIES, ("content",), MemoryType.SEMANTIC_USER),
    "preference": (COLLECTION_PREFERENCES, ("content",), MemoryType.SEMANTIC_USER),
    "constraint": (COLLECTION_CONSTRAINTS, ("rule", "content"), MemoryType.CONSTRAINT),
    "episodic": (
        COLLECTION_INTERACTIONS,
        ("content", "user_message"),
        MemoryType.EPISODIC,
    ),
}

# Familles NON inspectables, et pourquoi — le routeur les rend telles quelles
# pour que la page dise ce qu'elle ne peut pas montrer, au lieu de l'omettre.
UNINSPECTABLE: dict[str, str] = {
    "procedural": (
        "Pas de magasin : la mémoire procédurale est le catalogue d'outils, "
        "lu à la volée depuis le registre. Il n'y a rien à parcourir ni à "
        "oublier — retirer un outil se fait dans le code."
    ),
    "error": (
        "Écriture seule : les erreurs partent dans les cas d'échec de la "
        "boucle d'apprentissage, et rien ne les relit ici."
    ),
}


def inspectable_families() -> list[str]:
    """Les familles que la page peut afficher."""
    return list(_INSPECTABLE)


def _first_text(payload: dict, fields: tuple[str, ...]) -> str:
    for f in fields:
        value = payload.get(f)
        if value:
            return str(value)
    return ""


async def list_entries(
    family: str, user_id: str, limit: int = 50, offset: str | None = None
) -> tuple[list[MemoryEntry], str | None]:
    """Parcourir une famille — (entrées, curseur suivant).

    Best-effort comme le reste du sous-paquet : une collection absente (rien
    n'a encore été écrit dedans) rend une page vide, pas une erreur 500.
    """
    if family not in _INSPECTABLE:
        raise KeyError(family)
    collection, text_fields, mem_type = _INSPECTABLE[family]
    try:
        points, next_offset = await get_memory_infra().scroll_entries(
            collection, user_id, limit, offset
        )
    except Exception as exc:
        logger.warning(
            "inspection: scroll %s impossible (%s) — page vide", collection, exc
        )
        return [], None

    entries: list[MemoryEntry] = []
    for p in points:
        payload = p.payload or {}
        created = payload.get("created_at")
        entries.append(MemoryEntry(
            id=str(p.id),
            type=mem_type,
            content=_first_text(payload, text_fields),
            created_at=str(created) if created is not None else None,
            metadata={
                "family": family,
                "conversation_id": payload.get("conversation_id"),
            },
        ))
    return entries, next_offset


async def forget_entry(family: str, entry_id: str, user_id: str) -> bool:
    """Oublier UNE entrée. Rend False si elle n'existe pas, ou n'est pas à toi.

    Retire le vecteur Qdrant ET la ligne FTS. Oublier à moitié laisserait le
    souvenir peser sur le classement par le boost plein-texte, sans jamais
    s'afficher — un oubli qui n'oublie pas.

    ⚠️ Asymétrie VOULUE avec `list_entries` : le parcours dégrade en page vide
    quand Qdrant est muet, la suppression laisse remonter. Un `False` sur une
    panne deviendrait « Entrée introuvable » côté routeur — un mensonge : elle
    existe, on n'a pas su l'atteindre. Mieux vaut une erreur franche que la
    confirmation d'un oubli qui n'a pas eu lieu.
    """
    if family not in _INSPECTABLE:
        raise KeyError(family)
    collection, _, _ = _INSPECTABLE[family]
    deleted = await get_memory_infra().delete_point(collection, entry_id, user_id)
    if not deleted:
        return False
    try:
        from app.services.fts_store import get_fts_store
        await get_fts_store().delete_point(entry_id, user_id)
    except Exception as exc:
        # Le vecteur est parti : l'entrée ne s'affichera plus et ne sera plus
        # rappelée. On signale fort, mais on ne ment pas à l'utilisateur en
        # rendant False — la suppression a bien eu lieu.
        logger.warning(
            "inspection: vecteur %s supprimé mais ligne FTS conservée (%s) — "
            "elle continuera de peser sur le classement plein-texte",
            entry_id, exc,
        )
    return True
