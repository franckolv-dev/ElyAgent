# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/admin.py
# @brief      Admin management endpoints
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.passwords import hash_password
from app.database import get_db
from app.models.user import User
from app.models.audit import AuditLog
from app.models.system_config import SystemConfig
from app.schemas.admin import AuditLogResponse, UserAdminResponse
from app.schemas.auth import AdminResetPasswordRequest
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


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_200_OK)
async def admin_reset_password(
    user_id: str,
    req: AdminResetPasswordRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Réinitialise le mot de passe d'un utilisateur (admin uniquement)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    if user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Utilisez /auth/change-password pour modifier votre propre mot de passe.",
        )
    user.hashed_password = await hash_password(req.new_password)
    db.add(AuditLog(
        user_id=str(admin.id),
        action="admin_reset_password",
        target_host=None,
        command=None,
        details=f"Reset password for user '{user.username}' (id={user_id})",
    ))
    await db.commit()
    return {"message": f"Mot de passe de '{user.username}' réinitialisé."}


@router.patch("/users/{user_id}/toggle-active", status_code=status.HTTP_200_OK)
async def admin_toggle_user_active(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Active ou désactive un compte utilisateur."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Impossible de désactiver son propre compte.")
    user.is_active = not user.is_active
    state = "activé" if user.is_active else "désactivé"
    db.add(AuditLog(
        user_id=str(admin.id),
        action="admin_toggle_user",
        target_host=None,
        command=None,
        details=f"User '{user.username}' (id={user_id}) {state}",
    ))
    await db.commit()
    return {"message": f"Compte '{user.username}' {state}.", "is_active": user.is_active}


@router.get("/audit", response_model=list[AuditLogResponse])
async def list_audit_logs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
    action: str | None = Query(default=None),
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    query = query.order_by(desc(AuditLog.created_at)).limit(limit)
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
    db: AsyncSession = Depends(get_db),
):
    """Create or update a system config value (admin only)."""
    await set_config(
        body.key,
        body.value,
        is_secret=body.is_secret,
        description=body.description,
    )
    db.add(AuditLog(
        user_id=str(admin.id),
        action="admin_config_set",
        target_host=None,
        command=None,
        details=f"Set config key='{body.key}' secret={body.is_secret}",
    ))
    await db.commit()
    return {"message": f"Config '{body.key}' saved."}


@router.delete("/config/{key}")
async def remove_config(
    key: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a system config entry."""
    await delete_config(key)
    db.add(AuditLog(
        user_id=str(admin.id),
        action="admin_config_delete",
        target_host=None,
        command=None,
        details=f"Deleted config key='{key}'",
    ))
    await db.commit()
    return {"message": f"Config '{key}' deleted."}


# ── Memory consolidation (on-demand) ──────────────────────────────────────────

@router.post("/memory/consolidate-now")
async def memory_consolidate_now(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a memory consolidation pass for ALL users immediately.

    Normally runs at 03:00 and 15:00 via APScheduler. Useful when the
    backlog is large (e.g. after a long session) and you don't want to
    wait for the next cron tick. The call is blocking: it returns once
    all users have been processed (usually 5-15 s for typical workloads).
    """
    from app.services.memory_service import consolidate_all_users
    await consolidate_all_users()
    db.add(AuditLog(
        user_id=str(admin.id),
        action="admin_memory_consolidate",
        target_host=None,
        command=None,
        details="Manual memory consolidation triggered",
    ))
    await db.commit()
    return {"message": "Consolidation triggered — see backend logs for per-user counts."}


# ── Métriques de charge (revue 2026-06-10 §4 — observabilité) ───────────────

@router.get("/metrics")
async def runtime_metrics(admin: User = Depends(require_admin)):
    """Photo instantanée de la charge du process — répond à « pourquoi
    c'est lent depuis 14 h » sans grep de logs Docker. Compteurs maison
    (pas de dépendance Prometheus) ; admin-only pour ne pas exposer la
    topologie interne."""
    from app.services import ws_registry
    from app.services.background_tasks import pending_count
    from app.services.conversation_filters import filter_count
    from app.services.mission_heartbeat import _in_flight as _missions_in_flight
    from app.services.run_gate import _semaphores as _run_semaphores

    try:
        from app.services.browser_manager import get_browser_manager
        browser_sessions = get_browser_manager().session_count()
    except Exception:
        browser_sessions = -1

    try:
        from app.services import frozen_memory as _fm
        from app.services import system_prompt_cache as _spc
        snapshots = len(_fm._snapshots)
        prompt_cache = len(_spc._cache)
    except Exception:
        snapshots = prompt_cache = -1

    return {
        "ws_users_connected": len(ws_registry._registry),
        "ws_sockets_total": sum(len(s) for s in ws_registry._registry.values()),
        "background_tasks_pending": pending_count(),
        "missions_ticks_in_flight": len(_missions_in_flight),
        "users_with_run_slots": len(_run_semaphores),
        "pii_filters_active": filter_count(),
        "frozen_memory_snapshots": snapshots,
        "system_prompt_cache_entries": prompt_cache,
        "browser_sessions": browser_sessions,
    }
