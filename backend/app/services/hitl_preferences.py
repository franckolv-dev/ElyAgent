# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/hitl_preferences.py
# @brief      Per-user HITL preferences resolver
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Per-user HITL preferences — resolve whether a tool needs confirmation.

Used by the sub-agent factory's HITL block. The function falls back to the
secure default (``True`` = HITL required) on any error so a misconfigured
DB row can never make the system silently bypass approval.
"""
from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import select

from app.database import async_session
from app.models.hitl_preference import HitlPreference

logger = logging.getLogger(__name__)


# Tools where HITL is FORCED on, even if the user toggles it off in Settings.
# These are the most destructive / costly / irreversible operations. The UI
# greys out the slider for these so the user understands they can't disable.
LOCKED_HITL_TOOLS: Final[frozenset[str]] = frozenset({
    # Mass / batch destructive Gmail operations
    "gmail_batch_modify",
    "gmail_trash_emails",
    "gmail_move_emails",
    # Query-based bulk trash — a single bad Gmail query
    # (e.g. "from:gmail.com") can match thousands of mails. MORE
    # dangerous than gmail_trash_emails (which takes a specific ID list)
    # because the agent constructs the query string itself from the
    # user's free-text request. Always lock. Added 2026-05-17 alongside
    # its inclusion in the default toolset profile.
    "gmail_trash_by_query",
    # PERMANENT trash purge — irreversible, no Gmail API recovers a
    # batchDelete'd message. By default Gmail auto-purges trash after
    # 30 days, so calling this tool is only justified when the user
    # explicitly wants immediate erasure (disk-space, data-retention
    # policy, sensitive content). Always lock to force confirmation.
    "gmail_empty_trash",
    # Account-level Gmail settings (filters, signature, vacation,
    # forwarding). A filter rule persists and silently affects every
    # future incoming mail — far more impactful than trashing 10 mails.
    # Forwarding can leak the inbox to a 3rd-party address. Always lock.
    "gmail_update_settings",
    # Filesystem destructive — all four locked. The user always confirms
    # before any change to local files; non-disableable per preferences.
    "desktop_delete_file",
    "desktop_write_file",   # overwrites existing files
    "desktop_move_file",    # rename / move can clobber the destination
    "desktop_create_dir",   # creates directories — low risk but still a write
    # Drive destructive
    "drive_delete_file",
    "drive_share_file",     # privacy-sensitive (could expose private docs)
    # Calendar destructive
    "calendar_delete_event",
    # SSH (could rm -rf)
    "ssh_execute",
    # Raw API escape hatches — by design unrestricted, must always confirm
    "gmail_raw_api_call",
    "calendar_raw_api_call",
    "drive_raw_api_call",
    "docs_raw_api_call",
    "sheets_raw_api_call",
    "tasks_raw_api_call",
    "contacts_raw_api_call",
    # Vault — sensitive secret operations
    "vault_unlock",
    "vault_set_secret",
    # Contacts batch (can delete up to 200 contacts in one shot)
    "contacts_batch_operations",
    # Tasks bulk delete via raw
    "tasks_delete",
    # ⚠ Deliberately NOT here: scheduler_delete_task. When the user explicitly
    # asks in chat to remove a scheduled task they themselves set up, asking
    # again for confirmation is pure friction (Franck audit 2026-05-14):
    # "du moment que c'est moi qui lui demande de supprimer mes propres
    # taches, je ne trouve pas génant de ne pas avoir à confirmer une de
    # mes demandes". The HITL mechanism is meant for irreversible actions
    # that touch third parties (mails, shares, SSH) or autonomous behavior
    # (cron run unattended), not for user-initiated cleanup of their own
    # cron jobs. If a user wants confirmation, they can enable it from
    # Settings → HITL preferences (the tool is intentionally toggleable).
    # Memory — persisting permanent constraints affects ALL future
    # conversations. A model that hallucinates "I can't do X" and saves it
    # as a constraint will poison every subsequent chat for every model.
    # Force HITL so the user must approve any permanent rule.
    # (Discovered 2026-05-06 — Ministral 3 8B + Kimi K2.6 + Qwen 3.6 Flash
    # all refused screenshot/email workflow because of self-saved constraints.)
    "save_constraint",
})


async def set_user_preference(
    user_id: str,
    tool_name: str,
    *,
    requires_confirmation: bool,
) -> bool:
    """Upsert a per-user HITL preference. Returns True on success.

    Sprint 3.7 follow-up (2026-05-23) — backs the "Toujours autoriser" /
    "Toujours interdire" buttons on the HITL panel. When the user picks
    "always allow", we save ``requires_confirmation=False`` so the next
    invocation of the same tool by the same user skips the HITL prompt.

    ``LOCKED_HITL_TOOLS`` cannot be overridden — for those we accept the
    write (the row exists, useful for audit) but ``user_requires_hitl``
    will keep returning True regardless. The frontend should grey out
    the "always" buttons for locked tools, but we belt-and-suspender
    server-side too.

    Never raises — any DB error returns False, caller may log + skip.
    """
    if not user_id or not tool_name:
        return False
    try:
        from datetime import datetime, timezone
        async with async_session() as db:
            row = await db.execute(
                select(HitlPreference).where(
                    HitlPreference.user_id == user_id,
                    HitlPreference.tool_name == tool_name,
                )
            )
            pref = row.scalar_one_or_none()
            if pref is None:
                pref = HitlPreference(
                    user_id=user_id,
                    tool_name=tool_name,
                    requires_confirmation=requires_confirmation,
                )
                db.add(pref)
            else:
                pref.requires_confirmation = requires_confirmation
                pref.updated_at = datetime.now(timezone.utc)
            await db.commit()
        return True
    except Exception as exc:
        logger.warning(
            "set_user_preference failed for %s/%s: %s",
            user_id[:8], tool_name, exc,
        )
        return False


async def user_requires_hitl(user_id: str, tool_name: str) -> bool:
    """Return True if HITL approval is required for ``user_id`` on ``tool_name``.

    Resolution order :
      1. If ``tool_name`` is in ``LOCKED_HITL_TOOLS`` → always True.
      2. If a user-specific row exists in ``hitl_preferences`` → use it.
      3. Otherwise fall back to True (= secure default, HITL on).

    Never raises — any DB error degrades to True.
    """
    if not user_id or not tool_name:
        return True
    if tool_name in LOCKED_HITL_TOOLS:
        return True
    try:
        async with async_session() as db:
            row = await db.execute(
                select(HitlPreference.requires_confirmation).where(
                    HitlPreference.user_id == user_id,
                    HitlPreference.tool_name == tool_name,
                )
            )
            val = row.scalar_one_or_none()
            if val is None:
                return True   # no override → secure default
            return bool(val)
    except Exception as exc:
        logger.warning("HITL preference lookup failed for %s/%s: %s — default True", user_id[:8], tool_name, exc)
        return True
