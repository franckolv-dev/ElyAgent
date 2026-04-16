# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/validation.py
# @brief      Android webhook endpoints for HITL validation
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Android webhook endpoints for HITL validation.

ntfy action buttons call these URLs directly:
  POST /validation/{action_id}/allow  → execute once
  POST /validation/{action_id}/deny   → cancel this time
  POST /validation/{action_id}/ban    → cancel + store permanent rule
"""
import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager

router = APIRouter(prefix="/validation", tags=["validation"])


async def _resolve(
    action_id: str,
    decision: str,
    reason: str | None,
    current_user: User,
) -> dict:
    hitl = get_hitl_manager()
    pending = hitl._pending.get(action_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")
    # Verify the action belongs to the requesting user
    if pending.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this action")
    resolved = await hitl.resolve(action_id, decision, reason)
    if not resolved:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")

    # Log HITL decision for dashboard analytics (non-critical, fire-and-forget)
    try:
        from app.services.analytics_service import log_usage
        asyncio.create_task(log_usage(
            user_id=current_user.id,
            model="",
            provider="hitl",
            input_tokens=0,
            output_tokens=0,
            hitl_decision=decision,
            hitl_action=action_id,
            channel="web",
        ))
    except Exception:
        pass

    return {"status": "ok", "decision": decision}


@router.post("/{action_id}/allow")
async def allow_action(
    action_id: str,
    current_user: User = Depends(get_current_user),
):
    """Authorize the action for this occurrence only."""
    return await _resolve(action_id, "allow", None, current_user)


@router.post("/{action_id}/deny")
async def deny_action(
    action_id: str,
    current_user: User = Depends(get_current_user),
    reason: str = Body(default=None, embed=True),
):
    """Refuse the action for this occurrence only."""
    return await _resolve(action_id, "deny", reason, current_user)


@router.post("/{action_id}/ban")
async def ban_action(
    action_id: str,
    current_user: User = Depends(get_current_user),
    reason: str = Body(default=None, embed=True),
    user_id: str = Body(default=None, embed=True),
    description: str = Body(default=None, embed=True),
):
    """Refuse and permanently memorise a security rule derived from this action.

    When called from ntfy (empty body), the constraint is stored via the
    pending action's own description so no body params are required.
    """
    hitl = get_hitl_manager()
    # Fallback: read description / user_id from the pending action itself
    pending = hitl._pending.get(action_id)
    # Verify ownership before proceeding
    if pending and pending.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this action")
    actual_desc = description or (pending.description if pending else action_id)
    actual_user = user_id or (pending.user_id if pending else "")

    rule = f"INTERDICTION PERMANENTE: {actual_desc}"
    if reason:
        rule += f" — Raison: {reason}"
    await get_memory_manager().store_constraint(rule, actual_user)
    return await _resolve(action_id, "ban", reason, current_user)
