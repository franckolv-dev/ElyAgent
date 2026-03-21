"""Android webhook endpoints for HITL validation.

ntfy action buttons call these URLs directly:
  POST /validation/{action_id}/allow  → execute once
  POST /validation/{action_id}/deny   → cancel this time
  POST /validation/{action_id}/ban    → cancel + store permanent rule
"""
from fastapi import APIRouter, Body, HTTPException

from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager

router = APIRouter(prefix="/validation", tags=["validation"])


async def _resolve(action_id: str, decision: str, reason: str | None) -> dict:
    resolved = await get_hitl_manager().resolve(action_id, decision, reason)
    if not resolved:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")
    return {"status": "ok", "decision": decision}


@router.post("/{action_id}/allow")
async def allow_action(action_id: str):
    """Authorize the action for this occurrence only."""
    return await _resolve(action_id, "allow", None)


@router.post("/{action_id}/deny")
async def deny_action(action_id: str, reason: str = Body(default=None, embed=True)):
    """Refuse the action for this occurrence only."""
    return await _resolve(action_id, "deny", reason)


@router.post("/{action_id}/ban")
async def ban_action(
    action_id: str,
    reason: str = Body(default=None, embed=True),
    user_id: str = Body(..., embed=True),
    description: str = Body(..., embed=True),
):
    """Refuse and permanently memorise a security rule derived from this action."""
    rule = f"INTERDICTION PERMANENTE: {description}"
    if reason:
        rule += f" — Raison: {reason}"
    await get_memory_manager().store_constraint(rule, user_id)
    return await _resolve(action_id, "ban", reason)
