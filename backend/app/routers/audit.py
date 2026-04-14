# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Audit API — consultation, export et statistiques des logs d'audit (admin)."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models.audit import AuditLog
from app.models.usage_log import UsageLog
from app.models.user import User
from app.schemas.admin import AuditLogDetailResponse

router = APIRouter()


# ── GET /audit/logs — Liste paginée avec filtres ─────────────────────────────

@router.get("/audit/logs", response_model=list[AuditLogDetailResponse])
async def list_audit_logs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Query(default=None, description="Filtrer par user_id"),
    action: str | None = Query(default=None, description="Filtrer par type d'action"),
    channel: str | None = Query(default=None, description="Filtrer par canal (web, telegram, ...)"),
    from_date: datetime | None = Query(default=None, description="Date de début (ISO 8601)"),
    to_date: datetime | None = Query(default=None, description="Date de fin (ISO 8601)"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Retourne les logs d'audit avec jointure User pour le username."""
    query = (
        select(
            AuditLog,
            User.username.label("username"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(desc(AuditLog.created_at))
    )

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    if channel:
        query = query.where(AuditLog.channel == channel)
    if from_date:
        query = query.where(AuditLog.created_at >= from_date)
    if to_date:
        query = query.where(AuditLog.created_at <= to_date)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return [
        AuditLogDetailResponse(
            id=row.AuditLog.id,
            user_id=row.AuditLog.user_id,
            username=row.username,
            action=row.AuditLog.action,
            channel=row.AuditLog.channel,
            tool_used=row.AuditLog.tool_used,
            target_host=row.AuditLog.target_host,
            command=row.AuditLog.command,
            result_code=row.AuditLog.result_code,
            details=row.AuditLog.details,
            ip_address=row.AuditLog.ip_address,
            created_at=row.AuditLog.created_at,
        )
        for row in rows
    ]


# ── GET /audit/logs/export — Export CSV ──────────────────────────────────────

@router.get("/audit/logs/export")
async def export_audit_logs_csv(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=10000, ge=1, le=50000),
):
    """Export des logs d'audit au format CSV (conformité / RGPD)."""
    query = (
        select(
            AuditLog,
            User.username.label("username"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(desc(AuditLog.created_at))
    )

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    if channel:
        query = query.where(AuditLog.channel == channel)
    if from_date:
        query = query.where(AuditLog.created_at >= from_date)
    if to_date:
        query = query.where(AuditLog.created_at <= to_date)

    query = query.limit(limit)
    result = await db.execute(query)
    rows = result.all()

    # Construction du CSV en mémoire
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "user_id", "username", "action", "channel", "tool_used",
        "target_host", "command", "result_code", "details", "ip_address",
        "created_at",
    ])
    for row in rows:
        log = row.AuditLog
        writer.writerow([
            log.id,
            log.user_id,
            row.username or "",
            log.action,
            log.channel or "",
            log.tool_used or "",
            log.target_host or "",
            log.command or "",
            log.result_code if log.result_code is not None else "",
            log.details or "",
            log.ip_address or "",
            log.created_at.isoformat() if log.created_at else "",
        ])

    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_logs_{timestamp}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── GET /audit/stats — Statistiques agrégées ─────────────────────────────────

@router.get("/audit/stats")
async def audit_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
):
    """Statistiques d'audit agrégées sur les N derniers jours."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 1. Actions par type
    actions_result = await db.execute(
        select(
            AuditLog.action,
            func.count(AuditLog.id).label("count"),
        )
        .where(AuditLog.created_at >= since)
        .group_by(AuditLog.action)
        .order_by(desc(func.count(AuditLog.id)))
    )
    actions_by_type = [
        {"action": r.action, "count": r.count}
        for r in actions_result.all()
    ]

    # 2. Actions par canal
    channels_result = await db.execute(
        select(
            func.coalesce(AuditLog.channel, "unknown").label("channel"),
            func.count(AuditLog.id).label("count"),
        )
        .where(AuditLog.created_at >= since)
        .group_by("channel")
        .order_by(desc(func.count(AuditLog.id)))
    )
    actions_by_channel = [
        {"channel": r.channel, "count": r.count}
        for r in channels_result.all()
    ]

    # 3. Actions par utilisateur (top 20)
    users_result = await db.execute(
        select(
            AuditLog.user_id,
            User.username.label("username"),
            func.count(AuditLog.id).label("count"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(AuditLog.created_at >= since)
        .group_by(AuditLog.user_id, User.username)
        .order_by(desc(func.count(AuditLog.id)))
        .limit(20)
    )
    actions_by_user = [
        {"user_id": r.user_id, "username": r.username or "unknown", "count": r.count}
        for r in users_result.all()
    ]

    # 4. Décisions HITL (depuis usage_logs pour compatibilité)
    hitl_result = await db.execute(
        select(
            UsageLog.hitl_decision,
            func.count(UsageLog.id).label("count"),
        )
        .where(
            UsageLog.timestamp >= since,
            UsageLog.hitl_decision.isnot(None),
        )
        .group_by(UsageLog.hitl_decision)
    )
    hitl_breakdown = {"allow": 0, "deny": 0, "ban": 0}
    for r in hitl_result.all():
        if r.hitl_decision in hitl_breakdown:
            hitl_breakdown[r.hitl_decision] = r.count

    return {
        "period_days": days,
        "actions_by_type": actions_by_type,
        "actions_by_channel": actions_by_channel,
        "actions_by_user": actions_by_user,
        "hitl_decisions": hitl_breakdown,
    }
