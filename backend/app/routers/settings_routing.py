# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/settings_routing.py
# @brief      Admin endpoints to manage learned routing keywords (self-improving router).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Admin CRUD for learned routing keywords.

Companion to the maintenance LLM job in `services/routing_learning.py`. The job
auto-proposes keywords; this router lets an admin :
  * list (active + pending)
  * push manually (immediate active)
  * delete bad proposals
  * promote per-user → global (POST .../{id}/promote)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.models.user import User
from app.services.routing_learning import (
    add_manual_keyword, delete_keyword, list_keywords, reload_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/routing", tags=["settings-routing"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LearnedKeywordCreate(BaseModel):
    keyword: str
    domain: str  # research / workspace / infra / creative / data / memory / desktop / general
    user_id: Optional[str] = None  # None = global (admin only)
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/keywords")
async def list_learned_keywords(
    include_inactive: bool = False,
    user_id: Optional[str] = None,
    admin: User = Depends(require_admin),
) -> list[dict]:
    """List all learned keywords (active by default).

    Pass ``include_inactive=true`` to also see auto-proposed entries that
    haven't yet reached the confirmation threshold.
    Pass ``user_id`` to filter to a single user (otherwise returns all).
    """
    return await list_keywords(user_id=user_id, include_inactive=include_inactive)


@router.post("/keywords", status_code=status.HTTP_201_CREATED)
async def create_learned_keyword(
    body: LearnedKeywordCreate,
    admin: User = Depends(require_admin),
) -> dict:
    """Manually add a routing keyword (skips the auto-confirmation queue)."""
    try:
        return await add_manual_keyword(
            keyword=body.keyword,
            domain=body.domain,
            user_id=body.user_id,
            rationale=body.rationale,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.delete("/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_learned_keyword(
    keyword_id: str,
    admin: User = Depends(require_admin),
) -> None:
    """Delete a learned keyword by ID."""
    if not await delete_keyword(keyword_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Keyword {keyword_id} not found.",
        )


@router.post("/keywords/reload", status_code=status.HTTP_200_OK)
async def reload_learned_cache(
    admin: User = Depends(require_admin),
) -> dict:
    """Force reload the in-memory keyword cache from DB."""
    await reload_cache()
    return {"ok": True}


@router.post("/learn/run-now", status_code=status.HTTP_200_OK)
async def run_learning_tick_now(
    admin: User = Depends(require_admin),
) -> dict:
    """Manually trigger one iteration of the reformulation analysis job.

    Normalement exécuté toutes les 6h via APScheduler. Cet endpoint permet
    de forcer un run immédiat (utile pour debug ou pour rattraper après un
    redémarrage).
    """
    from app.services.routing_learning import analyze_reformulations_tick
    return await analyze_reformulations_tick()
