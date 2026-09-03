# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/audit_log.py
# @brief      Centralized helper to write AuditLog rows from anywhere.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Centralized audit log writer.

Avant ce helper (mai 2026), AuditLog n'était écrit qu'à 5 endroits dans
``routers/admin.py``. La page **Admin → Logs** restait donc désespérément
vide même après des semaines d'usage normal (chat / missions / HITL).

Usage :
    from app.services.audit_log import audit
    await audit(user_id, "mission_start", details=mission_title)

L'écriture est **best-effort fire-and-forget** : un échec d'audit ne doit
JAMAIS bloquer ni faire échouer l'action utilisateur sous-jacente.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def audit(
    user_id: Optional[str],
    action: str,
    *,
    tool_used: str | None = None,
    target_host: str | None = None,
    command: str | None = None,
    result_code: int | None = None,
    details: str | None = None,
    channel: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Write one AuditLog row. Never raises (best-effort).

    Action conventions in use :
      - ``hitl_allow`` / ``hitl_deny`` / ``hitl_ban``  (validation router)
      - ``mission_start`` / ``mission_abort`` / ``mission_complete`` /
        ``mission_pause`` / ``mission_restart``
      - ``admin_config_set``  (admin router)
      - ``ssh_command``  (ssh tool)
      - ``channel_link`` / ``channel_unlink``
    """
    if not user_id:
        return  # rows sans user_id sont inutilisables côté admin UI
    try:
        from app.database import async_session
        from app.models.audit import AuditLog
        async with async_session() as db:
            db.add(AuditLog(
                user_id=user_id,
                action=action,
                tool_used=tool_used,
                target_host=target_host,
                command=(command or "")[:1000] if command else None,
                result_code=result_code,
                details=(details or "")[:1000] if details else None,
                channel=channel,
                ip_address=ip_address,
            ))
            await db.commit()
    except Exception as exc:
        logger.debug("audit() write failed for action=%s user_id=%s: %s",
                     action, (user_id or "")[:8], exc)
