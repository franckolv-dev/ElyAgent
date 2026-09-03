# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/io_tool_audit.py
# @brief      Sprint 4b V3 J6.c.1 — per-call audit recorder for io
#             python_tool dispatches.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""One function: ``record_dispatch`` — fire-and-forget audit insert.

Design constraints (Sprint 4b V3 J6.c §audit):
  - **NEVER** breaks the dispatch path. A DB hiccup logs a warning and
    swallows: the LLM has already seen the result string, the user is
    not blocked on us getting the row in. We catch broad and continue.
  - Stores LABELS of secrets used (never values) and DECLARED network
    domains (never actual URLs). The privacy boundary is one-sided:
    audit can lose detail, but it must never gain leakage.
  - Caps `tool_name` (64), `outcome` (24), `error_truncated` (500) at the
    string level so SQLite truncation never surprises us.

Reads: nothing — the UI/admin reads the table directly with SQLAlchemy.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def record_dispatch(
    *,
    user_id: str,
    skill_id: str,
    tool_name: str,
    outcome: str,
    duration_s: float = 0.0,
    secrets_used: tuple[str, ...] | list[str] = (),
    network_allow: tuple[str, ...] | list[str] = (),
    error: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """Insert one IoToolDispatch row. Returns None.

    Best-effort: any failure (DB down, schema drift, etc.) is logged at
    WARNING level and swallowed. The caller is the io tool dispatcher,
    which has already produced a result string for the LLM — we don't
    want a postgres glitch to break the user's tool call.

    Args:
        user_id, skill_id: owner + skill the dispatch came from.
        tool_name: snapshot of the tool's display name at dispatch.
        outcome: one of the SandboxResult outcomes (returned / raised /
            timeout / nonserializable / crashed / error / unavailable).
            New runner-side outcomes pass through unchanged — the column
            is `String(24)`, future-proofed.
        duration_s: SandboxResult.duration_s. Converted to int ms here.
        secrets_used: tuple of secret LABELS the dispatcher resolved
            (never values). Empty for tools that declare none.
        network_allow: tuple of declared egress domains, snapshotted so
            a later edit of the skill doesn't lose the trace.
        error: truncated error/detail when outcome != returned. Capped
            to 500 chars at the model level.
        conversation_id: optional — io tools can be dispatched outside
            a chat context (mission scheduler, cron, V3.x).
    """
    try:
        # Import inside the function — keeps this module importable in
        # contexts where the DB layer hasn't initialised (tests, CLI).
        from app.database import async_session
        from app.models.io_tool_dispatch import IoToolDispatch

        async with async_session() as db:
            db.add(IoToolDispatch(
                user_id=user_id,
                skill_id=skill_id,
                tool_name=(tool_name or "<unknown>")[:64],
                conversation_id=conversation_id,
                outcome=(outcome or "error")[:24],
                duration_ms=max(0, int(round(duration_s * 1000))),
                secrets_used_json=json.dumps(
                    list(secrets_used), ensure_ascii=False,
                ),
                network_allow_json=json.dumps(
                    list(network_allow), ensure_ascii=False,
                ),
                error_truncated=(error or None) and error[:500],
            ))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "io_tool_audit.record_dispatch failed for skill=%s tool=%s: %s",
            skill_id, tool_name, exc,
        )
