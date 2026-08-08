# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/memory.py
# @brief      Sprint 2.5 §2.5.6 — surface HTTP de la page « Mes mémoires » :
#             parcourir ce qu'Ely retient, et l'oublier.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Inspection de la mémoire — Sprint 2.5 §2.5.6.

Trois endpoints :

  - ``GET    /api/me/memories/families``    → ce qui est inspectable, et ce
                                              qui ne l'est pas AVEC la raison
  - ``GET    /api/me/memories/{family}``    → parcours paginé
  - ``DELETE /api/me/memories/{family}/{id}`` → oublier une entrée

Le principe #1 du projet — « le user possède son agent » — n'a de sens que
s'il peut voir et corriger. La page qui liste sans pouvoir oublier serait de
la transparence en vitrine.

Cloisonnement : l'``user_id`` vient TOUJOURS du jeton, jamais d'un paramètre.
La suppression filtre sur le propriétaire dans la requête Qdrant elle-même
(cf. ``MemoryInfra.delete_point``), et un identifiant qui n'est pas à
l'appelant rend 404 — pas 403, qui confirmerait son existence. C'est la même
règle que ``conversations._get_owned_conversation``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.memory.inspection import (
    UNINSPECTABLE,
    forget_entry,
    inspectable_families,
    list_entries,
)

router = APIRouter()

# Plafond de page. Le parcours sert à auditer, pas à exporter : au-delà,
# c'est la pagination qui répond, sinon une mémoire chargée fait une réponse
# de plusieurs mégaoctets que le navigateur encaisse mal.
_MAX_LIMIT = 200


@router.get("/api/me/memories/families")
async def list_families(current_user: User = Depends(get_current_user)) -> dict:
    """Les familles de mémoire, inspectables ou non.

    ``uninspectable`` porte une RAISON par famille, et la page l'affiche.
    Masquer ces deux entrées ferait croire à une mémoire à quatre familles ;
    les montrer sans raison ferait croire à une panne.
    """
    return {
        "inspectable": inspectable_families(),
        "uninspectable": [
            {"family": name, "reason": reason}
            for name, reason in UNINSPECTABLE.items()
        ],
    }


@router.get("/api/me/memories/{family}")
async def browse_family(
    family: str,
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: str | None = Query(
        None, description="Curseur rendu par l'appel précédent (`next_offset`)."
    ),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Parcourir une famille, page par page.

    Pas de recherche par pertinence ici, exprès : l'audit doit être exhaustif.
    Un classement par score cacherait les entrées sous le seuil, et l'absence
    se lirait « Ely ne retient pas ça » — ce qui serait faux.
    """
    try:
        entries, next_offset = await list_entries(
            family, str(current_user.id), limit=limit, offset=offset
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Famille de mémoire inconnue : {family!r}. "
                f"Inspectables : {', '.join(inspectable_families())}."
            ),
        )
    return {
        "family": family,
        "entries": [e.to_dict() for e in entries],
        "next_offset": next_offset,
    }


@router.delete("/api/me/memories/{family}/{entry_id}")
async def forget(
    family: str,
    entry_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Oublier une entrée. ``{"ok": true}`` si c'est fait, 404 sinon.

    Un corps JSON et non un 204 : le client (`fetchAPI`) appelle `res.json()`
    sur TOUTES les réponses, un 204 sans corps le ferait lever. Même forme que
    `DELETE /api/conversations/{id}`.

    404 couvre DEUX cas volontairement indistinguables — l'entrée n'existe
    pas, ou elle n'est pas à l'appelant. Les séparer donnerait un oracle
    d'existence sur la mémoire d'autrui.
    """
    try:
        deleted = await forget_entry(family, entry_id, str(current_user.id))
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Famille de mémoire inconnue : {family!r}."
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    return {"ok": True}
