# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/memory.py
# @brief      Sprint 2.5 §2.5.6 — surface HTTP de la page « Mes mémoires » :
#             parcourir ce qu'Ely retient, et l'oublier.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
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
        "uninspectable": [{"family": name, "reason": reason} for name, reason in UNINSPECTABLE.items()],
    }


@router.get("/api/me/memories/scopes")
async def scopes(current_user: User = Depends(get_current_user)):
    from sqlalchemy import select
    from app.database import async_session
    from app.models.mission import Mission
    from app.models.google_account import GoogleAccount

    uid = str(current_user.id)
    async with async_session() as db:
        missions = (await db.execute(select(Mission.id, Mission.title).where(Mission.user_id == uid))).all()
        accounts = (
            await db.execute(select(GoogleAccount.id, GoogleAccount.alias).where(GoogleAccount.user_id == uid))
        ).all()
    return [{"id": f"mission:{m.id}", "label": f"Mission : {m.title}"} for m in missions] + [
        {"id": f"account:{a.id}", "label": f"Compte : {a.alias}"} for a in accounts
    ]


@router.get("/api/me/memories/selections")
async def selections(current_user: User = Depends(get_current_user)):
    import json
    from sqlalchemy import select
    from app.database import async_session
    from app.models.memory_context import MemorySelection

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(MemorySelection)
                    .where(MemorySelection.user_id == str(current_user.id))
                    .order_by(MemorySelection.created_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "query": r.query,
                "conversation_id": r.conversation_id,
                "scope": r.scope,
                "selected": json.loads(r.selected_json),
                "tokens": r.tokens,
                "elapsed_ms": r.elapsed_ms,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


from pydantic import BaseModel, Field


class MemoryEdit(BaseModel):
    content: str = Field(min_length=1, max_length=3000)
    scope: str = Field(default="", max_length=160)
    pinned: bool = False


@router.patch("/api/me/memories/{family}/{entry_id}")
async def correct(family: str, entry_id: str, body: MemoryEdit, current_user: User = Depends(get_current_user)):
    from app.services.memory.editing import edit

    try:
        ok = await edit(str(current_user.id), family, entry_id, body.content.strip(), body.scope, body.pinned)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not ok:
        raise HTTPException(404, "Entrée introuvable.")
    return {"ok": True}


@router.get("/api/me/memories/{family}")
async def browse_family(
    family: str,
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: str | None = Query(None, description="Curseur rendu par l'appel précédent (`next_offset`)."),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Parcourir une famille, page par page.

    Pas de recherche par pertinence ici, exprès : l'audit doit être exhaustif.
    Un classement par score cacherait les entrées sous le seuil, et l'absence
    se lirait « Ely ne retient pas ça » — ce qui serait faux.
    """
    try:
        entries, next_offset = await list_entries(family, str(current_user.id), limit=limit, offset=offset)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(f"Famille de mémoire inconnue : {family!r}. Inspectables : {', '.join(inspectable_families())}."),
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
        raise HTTPException(status_code=404, detail=f"Famille de mémoire inconnue : {family!r}.")
    if not deleted:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    return {"ok": True}
