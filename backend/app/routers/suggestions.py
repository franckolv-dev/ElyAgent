# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/suggestions.py
# @brief      C5 — endpoints /api/me/suggestions (anticipation V1)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Suggestions d'anticipation — surface utilisateur (C5 V1).

Trois gestes : lister ses suggestions, en refuser une (définitif — le
pattern ne sera jamais re-proposé), en accepter une (posé par le
frontend APRÈS que l'utilisateur a créé la tâche planifiée via la modal
pré-remplie — Ely ne crée jamais la tâche elle-même).

Scope strict par user_id ; row étrangère → 404 (pas 403, anti-fuite
d'existence — pattern me_learning_skills).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.anticipation import AnticipationSuggestion, SuggestionStatus
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me/suggestions", tags=["suggestions"])


def _to_dict(s: AnticipationSuggestion) -> dict:
    try:
        evidence = json.loads(s.evidence_json or "[]")
    except Exception:  # noqa: BLE001
        evidence = []
    return {
        "id": s.id,
        "status": s.status,
        "suggested_prompt": s.suggested_prompt,
        "suggested_cadence": s.suggested_cadence,
        "evidence": evidence,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


async def _load_own_or_404(db, suggestion_id: int, user_id: str) -> AnticipationSuggestion:
    row = (await db.execute(
        select(AnticipationSuggestion).where(
            AnticipationSuggestion.id == suggestion_id,
            AnticipationSuggestion.user_id == user_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Suggestion {suggestion_id} not found.")
    return row


@router.get("")
async def list_suggestions(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Les suggestions de l'appelant — par défaut TOUTES (le panneau
    affiche les proposed en tête ; ?status=proposed pour filtrer)."""
    async with async_session() as db:
        q = select(AnticipationSuggestion).where(
            AnticipationSuggestion.user_id == str(current_user.id)
        )
        if status:
            q = q.where(AnticipationSuggestion.status == status)
        rows = (await db.execute(
            q.order_by(AnticipationSuggestion.created_at.desc())
        )).scalars().all()
    return {"suggestions": [_to_dict(s) for s in rows]}


@router.post("/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Refus DÉFINITIF : la row reste (c'est l'anti-spam), le pattern ne
    sera jamais re-proposé. Idempotent."""
    async with async_session() as db:
        row = await _load_own_or_404(db, suggestion_id, str(current_user.id))
        if row.status != SuggestionStatus.DISMISSED:
            row.status = SuggestionStatus.DISMISSED
            await db.commit()
            await db.refresh(row)
        return _to_dict(row)


@router.post("/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Marque acceptée — appelé par le frontend une fois la tâche
    planifiée créée par L'UTILISATEUR (la modal pré-remplie). Idempotent."""
    async with async_session() as db:
        row = await _load_own_or_404(db, suggestion_id, str(current_user.id))
        if row.status != SuggestionStatus.ACCEPTED:
            row.status = SuggestionStatus.ACCEPTED
            await db.commit()
            await db.refresh(row)
        return _to_dict(row)
