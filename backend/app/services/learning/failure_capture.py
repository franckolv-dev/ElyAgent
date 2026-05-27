# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/failure_capture.py
# @brief      Sprint 4b Phase 1 — capture replay-able failure cases from signals
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# =============================================================================
"""Failure capture — Sprint 4b Phase 1.

Best-effort bridge from Sprint 3.7 signals (hitl_refusals, hallucination_blocks,
mission_critiques) to `failure_cases` rows that the skill_creator (Phase 3)
will later consume.

The functions in this module are called *right after* each
``record_<signal>`` succeeds in ``signals.py``. They never raise — a failed
capture is logged at DEBUG and the original signal row remains intact.

Pattern d'inspiration : Hermes ``tools/skill_usage.py`` (best-effort sidecar
that never blocks the underlying tool call). Voir
docs/external-references/hermes-skills-self-improvement.md §5 Phase 1.
Implémentation : code maison, multi-signal ELY.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.database import async_session

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────────────

# Each replay_payload string field is capped at this many chars. The
# rationale (cf. design note §5 Phase 1) is to keep rows under ~10 KB
# while preserving enough context for a tier S LLM to understand the
# pattern. Full replay can always re-fetch the original conversation row.
MAX_FIELD_CHARS: int = 2000

# Signal table identifiers — must match the values stored in
# FailureCase.signal_table (single source of truth).
SIGNAL_HITL_REFUSAL = "hitl_refusals"
SIGNAL_HALLUCINATION = "hallucination_blocks"
SIGNAL_MISSION_CRITIQUE = "mission_critiques"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _truncate(s: str | None) -> str:
    """Cap a string at MAX_FIELD_CHARS so a single oversized field can't
    blow up the row."""
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= MAX_FIELD_CHARS else s[:MAX_FIELD_CHARS] + "…"


def _fingerprint(*parts: str | None) -> str:
    """Compute a sha256[:16] hex digest from the joined parts.

    Used to cluster similar failures: two failures with the same
    {signal_table + tool_name + truncated_keyword} fingerprint are
    likely the same pattern, so the skill_creator can address them
    with one playbook rather than N near-duplicates.
    """
    joined = "|".join((p or "").strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _dump_payload(payload: dict[str, Any]) -> str:
    """JSON-encode the replay payload with sane defaults.

    Keeps booleans/numbers as-is, coerces unknowns to string via
    ``default=str`` so the dump never crashes on a custom object.
    """
    return json.dumps(payload, ensure_ascii=False, default=str)


# ── Per-signal capture functions ───────────────────────────────────────────


async def capture_from_hitl_refusal(
    *,
    signal_id: int,
    user_id: str,
    conversation_id: str,
    tool_name: str,
    args_redacted: str,
    action_description: str,
    decision: str,
    reason: str,
    mission_id: str | None = None,
    tier_llm: str | None = None,
    prompt_version: str | None = None,
) -> int | None:
    """Build a FailureCase from a HITL refusal signal.

    Trigger pattern: user said "no" to a proposed action. The replay
    payload captures the tool name + args + the action description the
    user actually saw, so the skill_creator can write a playbook of the
    form "in this user/tool/args combo, propose Y instead of X".

    Returns the new FailureCase.id, or None on error (swallowed).
    """
    if not user_id or not conversation_id:
        return None
    try:
        from app.models.failure_case import FailureCase

        payload = {
            "signal_kind": "hitl_refusal",
            "tool_name": _truncate(tool_name),
            "args_redacted": _truncate(args_redacted),
            "action_description": _truncate(action_description),
            "decision": decision,
            "reason": reason,
            "tier_llm": tier_llm,
        }
        # Clustering key: same tool + same decision pattern → same skill candidate
        fp = _fingerprint(SIGNAL_HITL_REFUSAL, tool_name, decision)

        async with async_session() as db:
            row = FailureCase(
                user_id=user_id,
                signal_table=SIGNAL_HITL_REFUSAL,
                signal_id=signal_id,
                conversation_id=conversation_id,
                mission_id=mission_id,
                replay_payload=_dump_payload(payload),
                pattern_hash=fp,
                tier_llm=tier_llm,
                prompt_version=prompt_version,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("capture_from_hitl_refusal failed (swallowed): %s", exc)
        return None


async def capture_from_hallucination_block(
    *,
    signal_id: int,
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
    """Build a FailureCase from a completion_guard rewrite signal.

    Trigger pattern: the agent claimed it had performed a destructive
    action without actually calling the corresponding tool. Replay
    payload captures the original (rewritten) response + the tools
    that WERE invoked vs the destructive tools that SHOULD have been.

    Returns the new FailureCase.id, or None on error.
    """
    if not user_id or not conversation_id:
        return None
    try:
        from app.models.failure_case import FailureCase

        payload = {
            "signal_kind": "hallucination_block",
            "model_used": _truncate(model_used),
            "matched_patterns": list(matched_patterns)[:20],
            "tools_invoked": list(tools_invoked)[:30],
            "destructive_tools_invoked": list(destructive_tools_invoked)[:30],
            "reason": reason,
            "original_response": _truncate(original_response),
            "tier_llm": tier_llm,
        }
        # Clustering key: same model + same "destructive verb claimed but no
        # tool" pattern → same skill candidate
        first_pattern = (matched_patterns[0] if matched_patterns else "")
        fp = _fingerprint(SIGNAL_HALLUCINATION, model_used, first_pattern)

        async with async_session() as db:
            row = FailureCase(
                user_id=user_id,
                signal_table=SIGNAL_HALLUCINATION,
                signal_id=signal_id,
                conversation_id=conversation_id,
                mission_id=mission_id,
                replay_payload=_dump_payload(payload),
                pattern_hash=fp,
                tier_llm=tier_llm,
                prompt_version=prompt_version,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("capture_from_hallucination_block failed (swallowed): %s", exc)
        return None


async def capture_from_mission_critique(
    *,
    signal_id: int,
    user_id: str,
    mission_id: str,
    critic_model: str,
    quality_score: int,
    honest_completion: bool,
    wasted_effort: bool,
    user_should_have_been_warned: bool,
    main_issue: str | None,
    prompt_version: str | None = None,
    # The critique is fired post-mission so there's no live conversation
    # at write time, but the mission row carries one.
    conversation_id: str | None = None,
    tier_llm: str | None = None,
) -> int | None:
    """Build a FailureCase from a LLM-as-judge mission critique.

    Only critiques with ``quality_score < 60`` OR ``honest_completion is
    False`` are turned into a FailureCase — high-score honest completions
    don't need a playbook. This keeps the failure queue focused on
    actionable signals.

    Returns the new FailureCase.id, or None on error / not-actionable.
    """
    if not user_id or not mission_id:
        return None
    # Filter: only capture missions worth fixing.
    if quality_score >= 60 and honest_completion:
        return None
    try:
        from app.models.failure_case import FailureCase

        payload = {
            "signal_kind": "mission_critique",
            "critic_model": _truncate(critic_model),
            "quality_score": quality_score,
            "honest_completion": honest_completion,
            "wasted_effort": wasted_effort,
            "user_should_have_been_warned": user_should_have_been_warned,
            "main_issue": _truncate(main_issue),
            "tier_llm": tier_llm,
        }
        # Clustering key: same main_issue truncated to keywords → same skill
        issue_kw = (main_issue or "")[:80].strip().lower()
        fp = _fingerprint(SIGNAL_MISSION_CRITIQUE, str(quality_score < 30), issue_kw)

        async with async_session() as db:
            row = FailureCase(
                user_id=user_id,
                signal_table=SIGNAL_MISSION_CRITIQUE,
                signal_id=signal_id,
                conversation_id=conversation_id,
                mission_id=mission_id,
                replay_payload=_dump_payload(payload),
                pattern_hash=fp,
                tier_llm=tier_llm,
                prompt_version=prompt_version,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("capture_from_mission_critique failed (swallowed): %s", exc)
        return None
