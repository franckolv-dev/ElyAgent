# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/error_store.py
# @brief      Error memory — write-only in V1. Read path lands in Sprint 3.7.
# @license    MIT
# @version    1.3.0
# =============================================================================
"""Error store — Sprint 2.5 §7.

V1 status — write-only. Every tool/mission failure is captured here so
the data is ready when Sprint 3.7 (auto-improvement loop) consumes it.
There is no `get_relevant` in V1: the design note (§7) calls for the
read path to land alongside the agent self-reflection loop, not before.

Source of truth = SQL table `error_log` (Sprint 2.5 Jalon 1). No Qdrant
collection in V1 — errors are searched by exact tool name + error class,
not by semantic similarity (yet).
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ErrorStore:
    """Write-only capture of tool/mission failures."""

    async def store(
        self,
        session: "AsyncSession",
        *,
        user_id: str,
        tool_name: str,
        args_redacted: dict,
        error_type: str,
        error_msg: str,
        traceback: str | None = None,
        mission_id: str | None = None,
        tier_llm: str | None = None,
        recovered: bool = False,
        prompt_version: str | None = None,
        tool_origin: str | None = None,
    ) -> int | None:
        """Persist one error row. Returns the row id or None on failure.

        Caller passes the AsyncSession because errors fire deep in the
        agent loop where a fresh session would be heavier than reusing
        the request-scoped one. Failure here never raises — error capture
        must never break the outer flow.

        Sprint 3.7 Jalon 3 — `prompt_version` (sha256[:8] of the system
        prompt active when the error fired) is optional ; if omitted the
        method tries the live ``current_system_prompt_version()``.
        """
        if prompt_version is None:
            try:
                from app.services.learning import current_system_prompt_version
                prompt_version = current_system_prompt_version()
            except Exception:
                prompt_version = None
        try:
            from app.models.error_log import ErrorLog
            row = ErrorLog(
                user_id=user_id,
                mission_id=mission_id,
                tool_name=tool_name,
                args_redacted=json.dumps(args_redacted, ensure_ascii=False),
                error_type=error_type,
                error_msg=error_msg,
                traceback=traceback,
                tier_llm=tier_llm,
                recovered=recovered,
                prompt_version=prompt_version,
                tool_origin=tool_origin,
            )
            session.add(row)
            await session.flush()
            return row.id
        except Exception as exc:
            logger.warning("ErrorStore.store failed (swallowed): %s", exc)
            return None
