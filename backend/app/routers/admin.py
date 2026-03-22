from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.models.audit import AuditLog
from app.models.system_config import SystemConfig
from app.schemas.admin import AuditLogResponse, UserAdminResponse
from app.services.system_config import set_config, delete_config, list_configs

router = APIRouter()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserAdminResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(desc(User.created_at)))
    return result.scalars().all()


@router.get("/audit", response_model=list[AuditLogResponse])
async def list_audit_logs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    action: str | None = Query(default=None),
):
    query = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    result = await db.execute(query)
    return result.scalars().all()


# ── System config (OAuth credentials, etc.) ──────────────────────────────────

class ConfigUpsertRequest(BaseModel):
    key: str
    value: str
    is_secret: bool = False
    description: str = ""


class ConfigResponse(BaseModel):
    key: str
    value: str | None   # masked for secrets
    is_secret: bool
    description: str | None


@router.get("/config", response_model=list[ConfigResponse])
async def get_configs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all system config entries. Secret values are masked."""
    rows = await list_configs(db)
    return [
        ConfigResponse(
            key=r.key,
            value="••••••••" if r.is_secret else r.value,
            is_secret=r.is_secret,
            description=r.description,
        )
        for r in rows
    ]


@router.put("/config")
async def upsert_config(
    body: ConfigUpsertRequest,
    admin: User = Depends(require_admin),
):
    """Create or update a system config value (admin only)."""
    await set_config(
        body.key,
        body.value,
        is_secret=body.is_secret,
        description=body.description,
    )
    return {"message": f"Config '{body.key}' saved."}


@router.delete("/config/{key}")
async def remove_config(
    key: str,
    admin: User = Depends(require_admin),
):
    """Delete a system config entry."""
    await delete_config(key)
    return {"message": f"Config '{key}' deleted."}
