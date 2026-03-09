from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.models.audit import AuditLog
from app.schemas.admin import AuditLogResponse, UserAdminResponse

router = APIRouter()


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
