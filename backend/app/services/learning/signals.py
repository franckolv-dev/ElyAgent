# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/signals.py
# @brief      Sprint 3.7 Jalon 2 — service exposing 4 typed write methods
#             for the auto-improvement learning signals.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.5.0
# =============================================================================
"""Learning signals persistence — Sprint 3.7 §2.5.

The auto-improvement loop reads from four typed tables (HitlRefusal,
HallucinationBlock, ErrorLog, ProviderSwitch). Each one captures a
different shape of "the agent got it wrong" event. This module gives
the rest of the codebase a single import path + 4 async functions to
record those events.

Three invariants every method enforces :

  1. **Never raise.** A learning-signal write must never break the user
     turn. Every exception is swallowed and logged at DEBUG.
  2. **Best-effort prompt_version.** If the caller passes an explicit
     hash, use it ; otherwise grab the live `current_system_prompt_version`.
     Either way, the column is never blocked by a missing hash.
  3. **Best-effort args scrubbing.** `args_redacted` strings are
     truncated to MAX_VALUE_CHARS to limit PII leak ; a future V2
     hook will use the per-conversation `SecurityFilter` for proper
     redaction (same pattern as orchestrate_rpc Jalon 6).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.database import async_session
from app.services.learning.prompt_version import current_system_prompt_version

logger = logging.getLogger(__name__)


# Best-effort safety net : truncate string values in tool args to this many
# chars before serialization. Full PII scrubbing is V2 (per-conv
# SecurityFilter, same pattern as orchestrate_rpc Jalon 6).
MAX_VALUE_CHARS: int = 200


def _scrub_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Defensive value truncation before JSON dump.

    Not a real anonymisation — just a length cap so an oversized tool
    argument (e.g. a 50 KB email body) doesn't blow up the row.
    """
    if not args:
        return {}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            out[k] = v if len(v) <= MAX_VALUE_CHARS else v[:MAX_VALUE_CHARS] + "…"
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, dict)):
            # Recursive truncation would be richer ; for V1 a JSON repr cap is enough.
            blob = json.dumps(v, ensure_ascii=False, default=str)
            out[k] = blob if len(blob) <= MAX_VALUE_CHARS else blob[:MAX_VALUE_CHARS] + "…"
        else:
            out[k] = str(v)[:MAX_VALUE_CHARS]
    return out


def _safe_prompt_version() -> str | None:
    try:
        return current_system_prompt_version()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# 1. HITL refusals
# ─────────────────────────────────────────────────────────────────────────


async def record_hitl_refusal(
    *,
    user_id: str,
    conversation_id: str,
    tool_name: str,
    args: dict | None,
    action_description: str,
    decision: str,
    reason: str,
    mission_id: str | None = None,
    tier_llm: str | None = None,
    prompt_version: str | None = None,
) -> int | None:
    """Persist a HITL refusal — design note §2.1.

    `decision` ∈ {"deny", "ban"} ; `reason` ∈ {"user-provided", "timeout", ...}.
    """
    if not user_id or not conversation_id:
        return None
    if prompt_version is None:
        prompt_version = _safe_prompt_version()
    try:
        from app.models.hitl_refusal import HitlRefusal
        row = HitlRefusal(
            user_id=user_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
            tool_name=tool_name,
            args_redacted=json.dumps(_scrub_args(args), ensure_ascii=False, default=str),
            action_description=str(action_description)[:1000],
            decision=decision,
            reason=reason,
            tier_llm=tier_llm,
            prompt_version=prompt_version,
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
        # Sprint 4b Phase 1 — capture into failure_cases for the skill_creator.
        # Best-effort hook, never blocks the signal itself.
        try:
            from app.services.learning.failure_capture import capture_from_hitl_refusal
            await capture_from_hitl_refusal(
                signal_id=row.id,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name=tool_name,
                args_redacted=row.args_redacted,
                action_description=action_description,
                decision=decision,
                reason=reason,
                mission_id=mission_id,
                tier_llm=tier_llm,
                prompt_version=prompt_version,
            )
        except Exception as exc:
            logger.debug("hitl_refusal failure_case capture skipped (swallowed): %s", exc)
        return row.id
    except Exception as exc:
        logger.debug("record_hitl_refusal failed (swallowed): %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────
# 2. Hallucination blocks
# ─────────────────────────────────────────────────────────────────────────


async def record_hallucination_block(
    *,
    user_id: str,
    conversation_id: str,
    model_used: str,
    matched_patterns: list[str],
    tools_invoked: list[str],
    destructive_tools_invoked: list[str],
    reason: str,
    original_response: str,
    tier_llm: str | None = None,
    mission_id: str | None = None,
    prompt_version: str | None = None,
) -> int | None:
    """Persist a completion_guard rewrite — design note §2.2."""
    if not user_id or not conversation_id:
        return None
    if prompt_version is None:
        prompt_version = _safe_prompt_version()
    try:
        from app.models.hallucination_block import HallucinationBlock
        row = HallucinationBlock(
            user_id=user_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
            model_used=str(model_used)[:120],
            tier_llm=(str(tier_llm)[:8] if tier_llm else None),
            matched_patterns=json.dumps(list(matched_patterns), ensure_ascii=False),
            tools_invoked=json.dumps(list(tools_invoked), ensure_ascii=False),
            destructive_tools_invoked=json.dumps(
                list(destructive_tools_invoked), ensure_ascii=False
            ),
            reason=str(reason)[:120],
            original_response=str(original_response)[:1000],
            prompt_version=prompt_version,
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
        # Sprint 4b Phase 1 — capture into failure_cases for the skill_creator.
        try:
            from app.services.learning.failure_capture import capture_from_hallucination_block
            await capture_from_hallucination_block(
                signal_id=row.id,
                user_id=user_id,
                conversation_id=conversation_id,
                model_used=model_used,
                matched_patterns=list(matched_patterns),
                tools_invoked=list(tools_invoked),
                destructive_tools_invoked=list(destructive_tools_invoked),
                reason=reason,
                original_response=str(original_response),
                tier_llm=tier_llm,
                mission_id=mission_id,
                prompt_version=prompt_version,
            )
        except Exception as exc:
            logger.debug("hallucination_block failure_case capture skipped (swallowed): %s", exc)
        return row.id
    except Exception as exc:
        logger.debug("record_hallucination_block failed (swallowed): %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────
# 3. Tool errors (wraps Sprint 2.5 ErrorStore + opens its own session)
# ─────────────────────────────────────────────────────────────────────────


async def record_tool_error(
    *,
    user_id: str,
    tool_name: str,
    args: dict | None,
    error_type: str,
    error_msg: str,
    traceback: str | None = None,
    mission_id: str | None = None,
    tier_llm: str | None = None,
    recovered: bool = False,
    prompt_version: str | None = None,
) -> int | None:
    """Persist a tool/LLM exception — wraps Sprint 2.5 ErrorStore.

    Differs from `ErrorStore.store()` (which expects an existing
    session) by opening its own session — convenient for fire-and-forget
    callers in nodes.py / orchestrate_runner where the request session
    isn't easily reachable.
    """
    if not user_id:
        return None
    if prompt_version is None:
        prompt_version = _safe_prompt_version()
    try:
        from app.services.memory.error_store import ErrorStore
        store = ErrorStore()
        async with async_session() as db:
            row_id = await store.store(
                db,
                user_id=user_id,
                tool_name=tool_name,
                args_redacted=_scrub_args(args),
                error_type=str(error_type)[:120],
                error_msg=str(error_msg)[:2000],
                traceback=str(traceback)[:5000] if traceback else None,
                mission_id=mission_id,
                tier_llm=tier_llm,
                recovered=recovered,
                prompt_version=prompt_version,
            )
            await db.commit()
            return row_id
    except Exception as exc:
        logger.debug("record_tool_error failed (swallowed): %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────
# 4. Provider switches
# ─────────────────────────────────────────────────────────────────────────


async def record_provider_switch(
    *,
    user_id: str,
    conversation_id: str,
    tier_llm: str,
    from_provider: str,
    to_provider: str,
    reason: str,
    position_in_chain: int,
    prompt_version: str | None = None,
) -> int | None:
    """Persist a fallback_manager `provider.switched` event — §2.4."""
    if not user_id or not conversation_id:
        return None
    if prompt_version is None:
        prompt_version = _safe_prompt_version()
    try:
        from app.models.provider_switch import ProviderSwitch
        row = ProviderSwitch(
            user_id=user_id,
            conversation_id=conversation_id,
            tier_llm=str(tier_llm)[:8],
            from_provider=str(from_provider)[:64],
            to_provider=str(to_provider)[:64],
            reason=str(reason)[:32],
            position_in_chain=int(position_in_chain),
            prompt_version=prompt_version,
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
        return row.id
    except Exception as exc:
        logger.debug("record_provider_switch failed (swallowed): %s", exc)
        return None
