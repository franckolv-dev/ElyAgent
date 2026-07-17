# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/output_verifier.py
# @brief      OutcomeVerifier — the single "response verified before delivery"
#             step, shared by every surface (web, messaging channels,
#             scheduler, voice). Extracted from routers/chat.py so the
#             anti-hallucination guarantee is uniform, not web-only
#             (audit SOL §6.3, roadmap §12/§14).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.0.0
# =============================================================================
"""Common output verification step (the audit's ``OutcomeVerifier``).

Why this module exists
----------------------
The anti-hallucination *detection* is a pure function in
``app.services.completion_guard`` (``detect_unbacked_completion_claim`` +
``build_warning_replacement``). But the *wiring* around it — log the block,
record the learning signal, replace the lying text with an honest warning —
used to live inlined only in ``routers/chat.py`` (the web surface). The
audit (SOL §6.3) flagged that messaging channels, scheduled tasks and other
paths therefore deliver unverified responses: a dubious "c'est supprimé"
could already be sent before any check.

``verify_outcome`` is that wiring, extracted once so all surfaces run the
*same* verification at the *same* point in their pipeline:

    LLM final → text transforms (deanonymize…) → verify_outcome → delivery

Design
------
- **Pure detection stays in completion_guard.** This module only composes it
  with the side effects (learning signal) and returns the safe text.
- **Iso-comportement with the web caller.** The kwargs handed to the
  learning signal match ``routers/chat.py``'s previous inline ``spawn(
  record_hallucination_block(...))`` exactly (``model_used or "unknown"``,
  ``original_response`` = the pre-replacement text).
- **Surface-specific extras stay in the caller.** The web surface still emits
  its own ``hallucination_blocked`` websocket event on top of the returned
  verdict — that is a UI concern, not part of the shared step. ``verify_outcome``
  returns ``blocked`` + ``verdict`` precisely so callers can layer such extras.
- **Never breaks delivery.** The learning-signal spawn is best-effort
  (swallowed on failure). Detection itself is regex-only and side-effect free.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.completion_guard import (
    DESTRUCTIVE_TOOLS,
    GuardVerdict,
    build_warning_replacement,
    detect_unbacked_completion_claim,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifiedOutcome:
    """Result of running the shared verifier on one assistant response.

    Attributes:
        content: The text safe to deliver. Identical to the input when nothing
            was blocked; the honest warning (``build_warning_replacement``)
            when a hallucinated completion was intercepted.
        blocked: True when an unbacked completion claim was caught and the
            content was replaced.
        verdict: The underlying ``GuardVerdict`` — exposed so callers can layer
            surface-specific reactions (e.g. the web ``hallucination_blocked``
            websocket event) without re-running detection.
    """

    content: str
    blocked: bool
    verdict: GuardVerdict


def _hallucination_signal_kwargs(
    *,
    verdict: GuardVerdict,
    user_id: str | None,
    conversation_id: str | None,
    model_used: str | None,
    original_content: str,
) -> dict:
    """Map a blocking ``GuardVerdict`` to ``record_hallucination_block`` kwargs.

    Kept pure and separate from the spawn so the mapping is unit-testable and
    stays locked to the web caller's historical contract
    (``model_used_out or "unknown"``, ``original_response`` = the suspect text).
    ``record_hallucination_block`` no-ops on empty ids, so ``None`` collapses to
    ``""`` safely.
    """
    return {
        "user_id": user_id or "",
        "conversation_id": conversation_id or "",
        "model_used": model_used or "unknown",
        "matched_patterns": list(verdict.matched_patterns),
        "tools_invoked": list(verdict.tools_invoked),
        "destructive_tools_invoked": list(verdict.destructive_tools_invoked),
        "reason": verdict.reason,
        "original_response": original_content,
    }


def _spawn_hallucination_signal(
    *,
    surface: str,
    user_id: str | None,
    conversation_id: str | None,
    model_used: str | None,
    verdict: GuardVerdict,
    original_content: str,
) -> None:
    """Fire-and-forget the ``record_hallucination_block`` learning signal.

    Best-effort: any failure (no running loop, import error, DB down) is
    swallowed — the guarantee is that verification never breaks delivery.
    Imported lazily to avoid pulling the learning package at import time and
    to keep a single, monkeypatchable seam for tests.
    """
    try:
        from app.services.background_tasks import spawn
        from app.services.learning import record_hallucination_block

        kwargs = _hallucination_signal_kwargs(
            verdict=verdict,
            user_id=user_id,
            conversation_id=conversation_id,
            model_used=model_used,
            original_content=original_content,
        )
        spawn(
            record_hallucination_block(**kwargs),
            label=f"hallucination-signal-{surface}",
        )
    except Exception as exc:  # noqa: BLE001 — never break delivery
        logger.debug(
            "hallucination signal spawn skipped (surface=%s): %s", surface, exc
        )


def verify_outcome(
    content: str,
    *,
    tools_invoked: list[str],
    surface: str,
    user_message: str | None = None,
    locale: str = "fr",
    user_id: str | None = None,
    conversation_id: str | None = None,
    model_used: str | None = None,
    record_signal: bool = True,
    destructive_tools: frozenset[str] = DESTRUCTIVE_TOOLS,
) -> VerifiedOutcome:
    """Verify one final assistant response before it is delivered.

    Runs the completion guard on *content* (the fully-transformed,
    deanonymized text about to be sent). If it claims a state-changing action
    was performed without a matching destructive tool call this turn, the
    content is replaced by an honest warning and the incident is recorded.

    Args:
        content: The final assistant text about to be persisted/delivered.
        tools_invoked: Tool names invoked since the user's last message. On
            ``ainvoke`` surfaces derive this via
            ``learning.facade_detection.tools_called_from_messages(result["messages"])``;
            on streaming surfaces (web, voice) it is the accumulated
            ``on_tool_start`` list.
        surface: Short surface tag ("web", "telegram", "scheduler", …) — used
            in logs and the learning-signal label.
        user_message: The user's last message, so recall questions
            ("qu'as-tu enregistré sur X ?") bypass the guard (else the honest
            recall answer trips it).
        locale: "fr" or "en" for the replacement warning.
        user_id / conversation_id / model_used: forwarded to the learning
            signal (which no-ops without ids).
        record_signal: set False to skip the learning signal (tests, or
            surfaces that record their outcome elsewhere).
        destructive_tools: override the destructive tool set (defaults to the
            module-level snapshot).

    Returns:
        A ``VerifiedOutcome``. Deliver ``.content``; inspect ``.blocked`` /
        ``.verdict`` for any surface-specific reaction.
    """
    verdict = detect_unbacked_completion_claim(
        content,
        tools_invoked,
        destructive_tools=destructive_tools,
        user_message=user_message,
    )

    if not verdict.is_hallucination:
        return VerifiedOutcome(content=content, blocked=False, verdict=verdict)

    logger.error(
        "OutcomeVerifier: HALLUCINATION BLOCKED "
        "(surface=%s user=%s conv=%s model=%s reason=%s)",
        surface,
        user_id or "?",
        conversation_id or "?",
        model_used or "unknown",
        verdict.reason,
    )

    if record_signal:
        _spawn_hallucination_signal(
            surface=surface,
            user_id=user_id,
            conversation_id=conversation_id,
            model_used=model_used,
            verdict=verdict,
            original_content=content,
        )

    safe = build_warning_replacement(content, verdict, locale=locale)
    return VerifiedOutcome(content=safe, blocked=True, verdict=verdict)


def verify_outcome_from_result(
    invoke_result,
    content: str,
    *,
    surface: str,
    user_message: str | None = None,
    locale: str = "fr",
    user_id: str | None = None,
    conversation_id: str | None = None,
    model_used: str | None = None,
    record_signal: bool = True,
    destructive_tools: frozenset[str] = DESTRUCTIVE_TOOLS,
) -> VerifiedOutcome:
    """Verify a response on a buffered (``ainvoke``) surface.

    Convenience wrapper for the messaging channels and the scheduler, which run
    the agent with a single buffered ``agent.ainvoke(...)`` and therefore hold
    the whole turn in ``invoke_result["messages"]`` — no streaming
    ``on_tool_start`` instrumentation. The tools-in-turn list is derived from
    those messages (``AIMessage.tool_calls`` + ``ToolMessage.name``) exactly the
    way the scheduler already does for facade detection, then handed to
    :func:`verify_outcome`.

    A malformed / non-dict ``invoke_result`` degrades to an empty tool list —
    fail-safe: an unbacked completion claim is caught rather than trusted.

    Streaming surfaces (web, voice) accumulate their own ``tools_called`` and
    should call :func:`verify_outcome` directly instead.
    """
    from app.services.learning.facade_detection import tools_called_from_messages

    messages = invoke_result.get("messages") if isinstance(invoke_result, dict) else None
    tools_invoked = tools_called_from_messages(messages)
    return verify_outcome(
        content,
        tools_invoked=tools_invoked,
        surface=surface,
        user_message=user_message,
        locale=locale,
        user_id=user_id,
        conversation_id=conversation_id,
        model_used=model_used,
        record_signal=record_signal,
        destructive_tools=destructive_tools,
    )
