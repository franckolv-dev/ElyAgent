# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/tool_policy.py
# @brief      Tool policy API — per-user allow / deny / require_hitl rules
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Tool policy API.

CRUD endpoints for per-user tool policies, plus YAML import/export so an
admin can mass-edit a user's rules outside the UI (`config/tool_policies/`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.tool_policy_service import (
    PolicyMode,
    get_tool_policy_service,
)

router = APIRouter(prefix="/api/tool-policy", tags=["tool-policy"])


class PolicyIn(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=100)
    mode: PolicyMode  # type: ignore[type-arg]
    reason: str | None = None


class PolicyOut(BaseModel):
    id: str
    tool_name: str
    mode: str
    reason: str | None
    source: str
    created_at: str | None
    updated_at: str | None


class YamlImport(BaseModel):
    yaml: str
    replace: bool = False


@router.get("/", response_model=list[PolicyOut])
async def list_policies(user: User = Depends(get_current_user)):
    return await get_tool_policy_service().list_policies(user.id)


@router.put("/", response_model=PolicyOut)
async def upsert_policy(
    body: PolicyIn,
    user: User = Depends(get_current_user),
):
    try:
        row = await get_tool_policy_service().set_policy(
            user_id=user.id,
            tool_name=body.tool_name,
            mode=body.mode,
            reason=body.reason,
            source="ui",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PolicyOut(
        id=row.id,
        tool_name=row.tool_name,
        mode=row.mode,
        reason=row.reason,
        source=row.source,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/{tool_name}")
async def delete_policy(
    tool_name: str,
    user: User = Depends(get_current_user),
):
    deleted = await get_tool_policy_service().delete_policy(user.id, tool_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Aucune règle pour cet outil")
    return {"message": f"Règle pour '{tool_name}' supprimée"}


@router.get("/export", response_class=Response)
async def export_yaml(user: User = Depends(get_current_user)):
    yaml_text = await get_tool_policy_service().export_to_yaml(user.id)
    return Response(
        content=yaml_text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="tool-policy-{user.id}.yaml"'},
    )


@router.post("/import")
async def import_yaml(
    body: YamlImport,
    user: User = Depends(get_current_user),
):
    try:
        summary = await get_tool_policy_service().import_from_yaml(
            user_id=user.id, yaml_text=body.yaml, replace=body.replace
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summary
