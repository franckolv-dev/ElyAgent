# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/failure_capture.py
# @brief      Sprint 4b Phase 1 — capture replay-able failure cases from signals
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#             https://opensource.org/licenses/MIT
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
SIGNAL_TOOL_ABSENT = "tool_absent"  # find_tool searched the catalog and found nothing
SIGNAL_USER_FEEDBACK = "user_feedback"  # C4-5 — explicit 👎 on an assistant response

# C4-4 — caps of the recorded tool trace (shadow replay re-serves these).
# Wider than MAX_FIELD_CHARS on purpose: a truncated tool result would make
# the replayed LLM see a DIFFERENT context than the original turn. The DB
# `messages` table only persists user/assistant/system rows (verified), so
# the trace captured at signal time is the ONLY source for shadow replay.
# Contents are stored exactly as the original LLM saw them (anonymized
# placeholders) — the replay LLM sees the same, and no cleartext PII is
# ever re-sent to the cloud.
TOOL_TRACE_CHARS: int = 3000
MAX_TOOL_TRACE_ENTRIES: int = 6


def tool_trace_from_messages(messages) -> list[dict]:
    """Extract the ordered ToolMessage trace of a turn: [{tool, content}].

    Best-effort and tolerant (dict/object shapes, garbage skipped) — same
    spirit as ``facade_detection.tools_called_from_messages`` but keeps
    the CONTENTS, which the shadow replay (C4-4) re-serves. Capped at
    MAX_TOOL_TRACE_ENTRIES entries × TOOL_TRACE_CHARS chars.
    """
    trace: list[dict] = []
    for m in (messages or []):
        try:
            is_tool_msg = (
                getattr(m, "type", None) == "tool"
                or m.__class__.__name__ == "ToolMessage"
            )
            if not is_tool_msg:
                continue
            name = getattr(m, "name", None)
            if not name:
                continue
            content = getattr(m, "content", "")
            if not isinstance(content, str):
                content = str(content)
            trace.append({"tool": str(name), "content": content[:TOOL_TRACE_CHARS]})
            if len(trace) >= MAX_TOOL_TRACE_ENTRIES:
                break
        except Exception:  # noqa: BLE001 — un message pourri ne casse pas la capture
            continue
    return trace


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


async def record_tool_absent(
    *,
    user_id: str,
    capability: str,
    conversation_id: str | None = None,
    mission_id: str | None = None,
) -> int | None:
    """Record a genuine capability gap (find_tool Phase 2 — the
    ``tool_absent_acknowledged`` signal).

    Called when ``find_tool`` searched the FULL catalog and found nothing
    matching ``capability`` — i.e. it's not a binding gap (find_tool would
    have surfaced it), it's a real missing capability. Persisted as a
    ``FailureCase`` so the auto-dev pipeline (V3) and humans can review/act on
    it; in the meantime it's a queryable backlog of "what users needed but ELY
    lacks". Deduped on the capability fingerprint while still unprocessed, so a
    repeated gap doesn't pile up rows.

    Best-effort, never raises. Returns the FailureCase.id (new or the existing
    unprocessed one), or None.
    """
    capability = (capability or "").strip()
    if not user_id or not capability:
        return None
    try:
        from sqlalchemy import select

        from app.models.failure_case import FailureCase

        fp = _fingerprint(SIGNAL_TOOL_ABSENT, capability[:120])
        payload = {
            "signal_kind": "tool_absent_acknowledged",
            "capability": _truncate(capability),
        }
        async with async_session() as db:
            # Dedup: don't re-record the same gap while it's still unprocessed.
            existing = (await db.execute(
                select(FailureCase.id).where(
                    FailureCase.signal_table == SIGNAL_TOOL_ABSENT,
                    FailureCase.pattern_hash == fp,
                    FailureCase.processed_at.is_(None),
                ).limit(1)
            )).scalar_one_or_none()
            if existing is not None:
                return existing
            row = FailureCase(
                user_id=user_id,
                signal_table=SIGNAL_TOOL_ABSENT,
                signal_id=0,  # synthetic — no upstream signal-table row
                conversation_id=conversation_id,
                mission_id=mission_id,
                replay_payload=_dump_payload(payload),
                expected_outcome=_truncate(capability),
                pattern_hash=fp,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("record_tool_absent failed (swallowed): %s", exc)
        return None


async def capture_from_user_feedback(
    *,
    user_id: str,
    user_message: str,
    conversation_id: str | None = None,
    model_used: str | None = None,
    feedback_id: str | None = None,
) -> int | None:
    """C4-5 — a thumbs-down becomes a first-class learning signal.

    Before this, 👎 rows were written to the ``feedback`` table and read
    by dashboards only — nobody ACTED on them. Each rating=-1 now lands a
    ``FailureCase`` (family ``user_feedback``) that the skill_autocreate
    cron picks up naturally (its scan has no family filter): ≥ 3 cases
    clustering on a pattern → candidate playbook.

    ``signal_id`` is synthetic (0) like ``record_tool_absent`` — the
    upstream Feedback row has a String UUID id, which doesn't fit the
    Integer column; the real id travels in the payload instead.

    Deduped on the truncated user_message fingerprint while unprocessed
    (two 👎 on the same ask = one case). Best-effort, never raises.
    Returns the FailureCase.id (new or existing unprocessed), or None.
    """
    user_message = (user_message or "").strip()
    if not user_id or not user_message:
        return None
    try:
        from sqlalchemy import select

        from app.models.failure_case import FailureCase

        fp = _fingerprint(SIGNAL_USER_FEEDBACK, user_message[:120])
        payload = {
            "signal_kind": "user_feedback_negative",
            "user_message": _truncate(user_message),
            "model_used": _truncate(model_used),
            "feedback_id": feedback_id or "",
        }
        async with async_session() as db:
            existing = (await db.execute(
                select(FailureCase.id).where(
                    FailureCase.signal_table == SIGNAL_USER_FEEDBACK,
                    FailureCase.pattern_hash == fp,
                    FailureCase.processed_at.is_(None),
                ).limit(1)
            )).scalar_one_or_none()
            if existing is not None:
                return existing
            row = FailureCase(
                user_id=user_id,
                signal_table=SIGNAL_USER_FEEDBACK,
                signal_id=0,  # synthetic — Feedback.id is a String UUID
                conversation_id=conversation_id,
                replay_payload=_dump_payload(payload),
                pattern_hash=fp,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("capture_from_user_feedback failed (swallowed): %s", exc)
        return None


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
    tool_trace: list[dict] | None = None,
) -> int | None:
    """Build a FailureCase from a completion_guard rewrite signal.

    Trigger pattern: the agent claimed it had performed a destructive
    action without actually calling the corresponding tool. Replay
    payload captures the original (rewritten) response + the tools
    that WERE invoked vs the destructive tools that SHOULD have been.

    C4-4 : ``tool_trace`` ([{tool, content}], already capped by
    ``tool_trace_from_messages``) is the recorded ToolMessage sequence of
    the turn — the shadow replay re-serves it instead of re-executing
    anything.

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
            "tool_trace": list(tool_trace or [])[:MAX_TOOL_TRACE_ENTRIES],
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
