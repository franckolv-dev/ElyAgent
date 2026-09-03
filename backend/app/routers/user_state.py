# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/user_state.py
# @brief      Sprint 3 Jalon 3 — endpoints exposing the User State Vector :
#             `GET /api/me/state` (read the current snapshot) and
#             `POST /api/me/state/recompute` (force the MAINTENANCE LLM
#             to refresh the state now, return the new value).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.7.0
# =============================================================================
"""User State Vector HTTP surface — Sprint 3 §3.

Two endpoints :

  - ``GET  /api/me/state``           → JSON {mood, current_focus,
                                        recent_topics, open_loops,
                                        energy_budget, updated_at?,
                                        prompt_version?}
  - ``POST /api/me/state/recompute`` → triggers ``compute_user_state``
                                        on the user's most recent
                                        conversation, invalidates the
                                        frozen-memory snapshot, returns
                                        the freshly-merged state.

Content-negotiation parity with ``/api/me/learning-report`` :
``Accept: application/json`` (or ``?format=json``) always wins ; the
state is intrinsically structured so JSON is the only sensible default
anyway. A `?format=markdown` variant returns the state rendered through
``format_user_state_block`` for "raw view" UIs and downloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import desc, select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.conversation import Conversation
from app.models.user import User
from app.models.user_state import UserState
from app.services.learning.user_state import (
    compute_user_state,
    format_user_state_block,
    get_user_state,
    is_disabled,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _augment_with_metadata(user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Add ``updated_at`` + ``prompt_version`` from the row (best-effort —
    if the row doesn't exist yet the values are ``None``)."""
    out = dict(state)
    try:
        async with async_session() as db:
            row = (await db.execute(
                select(UserState).where(UserState.user_id == user_id)
            )).scalar_one_or_none()
    except Exception:
        row = None
    out["updated_at"] = row.updated_at.isoformat() if row and row.updated_at else None
    out["prompt_version"] = row.prompt_version if row else None
    out["disabled"] = is_disabled()
    return out


async def _latest_conversation_id(user_id: str) -> str | None:
    """Most recent conversation for the user — used as the source slice
    when the recompute endpoint is hit without an explicit conv_id."""
    try:
        async with async_session() as db:
            row = (await db.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .order_by(desc(Conversation.created_at))
                .limit(1)
            )).scalar_one_or_none()
        return str(row) if row else None
    except Exception:
        return None


def _wants_json(format_q: str | None, accept_header: str) -> bool:
    if format_q:
        return format_q.lower() == "json"
    return "application/json" in (accept_header or "").lower() or "text/markdown" not in (accept_header or "").lower()


# ─────────────────────────────────────────────────────────────────────────
# GET /api/me/state
# ─────────────────────────────────────────────────────────────────────────


@router.get("/api/me/state")
async def read_user_state(
    format: str | None = Query(
        None,
        description="Force the response format : 'json' or 'markdown'. "
                    "If omitted, content negotiation uses Accept header.",
    ),
    accept: str = Header(default="application/json"),
    current_user: User = Depends(get_current_user),
):
    """Return the live user state for the authenticated user.

    JSON shape ::

        {
          "mood": "focused",
          "current_focus": "Sprint 3 User State Vector",
          "recent_topics": [...],
          "open_loops": [...],
          "energy_budget": "high",
          "updated_at": "2026-05-24T14:00:00+00:00" | null,
          "prompt_version": "abcd1234" | null,
          "disabled": false
        }

    The ``disabled`` field surfaces the ``USER_STATE_DISABLED`` env kill-
    switch so the UI can render a visible "feature off" banner instead of
    silently showing stale data.
    """
    user_id = str(current_user.id)
    state = await get_user_state(user_id)
    enriched = await _augment_with_metadata(user_id, state)

    if _wants_json(format, accept):
        return JSONResponse(enriched)
    return PlainTextResponse(
        format_user_state_block(state) or "(état vide)\n",
        media_type="text/markdown; charset=utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────
# POST /api/me/state/recompute
# ─────────────────────────────────────────────────────────────────────────


@router.post("/api/me/state/recompute")
async def recompute_user_state(
    conversation_id: str | None = Query(
        None,
        description="Specific conversation to read from. If omitted, "
                    "the user's most recent conversation is used.",
    ),
    current_user: User = Depends(get_current_user),
):
    """Force a state refresh now (synchronous — the caller waits for the
    MAINTENANCE LLM to return). Returns the new state ; on failure
    returns the previous state with ``"refreshed": false`` so the UI can
    surface a discreet "could not refresh" indicator.

    The endpoint is intentionally idempotent : calling twice with no
    intervening conversation activity yields the same state.
    """
    user_id = str(current_user.id)

    # IDOR fix A-2 (revue 2026-06-10) — an explicit conversation_id may be
    # any UUID; verify ownership BEFORE compute_user_state reads its
    # messages (_load_recent_messages has no user filter). 404 — not 403 —
    # mirrors conversations._get_owned_conversation so the response never
    # confirms that a foreign conversation id exists.
    if conversation_id:
        async with async_session() as db:
            owned = (await db.execute(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )).scalar_one_or_none()
        if owned is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    before = await get_user_state(user_id)

    if is_disabled():
        enriched = await _augment_with_metadata(user_id, before)
        enriched["refreshed"] = False
        enriched["reason"] = "disabled"
        return JSONResponse(enriched, status_code=200)

    conv_id = conversation_id or await _latest_conversation_id(user_id)
    if not conv_id:
        # No conversation history yet → nothing to learn from. Return the
        # current state untouched rather than 404 — the UI can still
        # display the empty defaults.
        enriched = await _augment_with_metadata(user_id, before)
        enriched["refreshed"] = False
        enriched["reason"] = "no_conversations"
        return JSONResponse(enriched, status_code=200)

    try:
        new_state = await compute_user_state(
            user_id=user_id, conversation_id=conv_id,
        )
        # Invalidate caches so the very next agent turn sees the refresh
        try:
            from app.services.frozen_memory import invalidate as _fm_invalidate
            _fm_invalidate(conv_id)
        except Exception:
            pass
        refreshed = new_state != before
    except Exception:
        new_state = before
        refreshed = False

    enriched = await _augment_with_metadata(user_id, new_state)
    enriched["refreshed"] = refreshed
    enriched["source_conversation_id"] = conv_id
    if not refreshed and new_state == before:
        # Either nothing actionable in the conv slice, or compute_user_state
        # swallowed an internal error. Either way the UX is the same.
        enriched["reason"] = "no_change"
    return JSONResponse(enriched, status_code=200)


# ─────────────────────────────────────────────────────────────────────────
# Bookkeeping (used by tests + admin diagnostics)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/api/me/state/_health")
async def health(current_user: User = Depends(get_current_user)) -> dict:
    """Tiny health endpoint that surfaces the kill-switch + a timestamp.
    Not part of the public contract — kept untyped under ``_health`` so
    we can iterate on it without breaking clients."""
    return {
        "ok": True,
        "disabled": is_disabled(),
        "user_id_known": str(current_user.id) != "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
