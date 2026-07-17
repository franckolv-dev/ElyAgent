# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_output_verifier.py
# @brief      Tests for the common OutcomeVerifier — the shared "response
#             verified before delivery" step extracted from the web caller
#             (audit SOL §6.3). Wraps completion_guard + the uniform
#             hallucination learning signal so every surface (web, channels,
#             scheduler, voice) verifies identically.
#
# @license    Elastic License 2.0
# =============================================================================
"""Tests for ``app.services.output_verifier``.

C3c-1 — extraction iso-comportement. The pure detection lives in
``completion_guard``; this module is the *wiring* (verdict → log →
learning signal → honest replacement) that used to be inlined only in
``routers/chat.py``. These tests pin the wiring contract so channels /
scheduler / voice can reuse it in C3c-2 without drift.

Run with:
    cd backend && .venv/bin/python -m pytest tests/test_output_verifier.py -v
"""
from __future__ import annotations

import pytest

from app.services.completion_guard import GuardVerdict
from app.services.output_verifier import (
    VerifiedOutcome,
    _hallucination_signal_kwargs,
    verify_outcome,
)


# A canonical unbacked completion claim (FR) + no tool invoked → hallucination.
_LYING = "Voilà, j'ai supprimé les 50 mails de la corbeille."
# A backed claim: same phrasing, but a destructive tool actually ran.
_BACKED_TOOL = "gmail_trash_by_query"


# ──────────────────────────────────────────────────────────────────────
# Passthrough — nothing to block
# ──────────────────────────────────────────────────────────────────────


def test_clean_content_passes_through_unchanged():
    """No completion claim → content is returned verbatim, not blocked."""
    content = "Le projet a 3 forks et 12 stars sur GitHub."
    out = verify_outcome(content, tools_invoked=[], surface="web")
    assert isinstance(out, VerifiedOutcome)
    assert out.blocked is False
    assert out.content == content
    assert out.verdict.is_hallucination is False


def test_backed_completion_passes_through_unchanged():
    """Completion claim + a real destructive tool this turn → not blocked."""
    out = verify_outcome(
        _LYING, tools_invoked=[_BACKED_TOOL], surface="telegram"
    )
    assert out.blocked is False
    assert out.content == _LYING
    assert out.verdict.is_hallucination is False
    assert _BACKED_TOOL in out.verdict.destructive_tools_invoked


def test_memory_recall_question_bypasses_guard():
    """A recall answer full of past-tense verbs must not be blocked when the
    user explicitly asked what was memorised."""
    out = verify_outcome(
        "Voici ce que j'ai enregistré : ton compte Amazon.",
        tools_invoked=[],
        surface="web",
        user_message="qu'as-tu enregistré sur mon compte amazon ?",
    )
    assert out.blocked is False
    assert out.content.startswith("Voici ce que j'ai enregistré")


# ──────────────────────────────────────────────────────────────────────
# Blocking — the core promise
# ──────────────────────────────────────────────────────────────────────


def test_unbacked_completion_is_blocked_and_replaced():
    """Completion claim with no tool call → blocked, content replaced by the
    honest warning, original phrasing quoted inside it."""
    out = verify_outcome(
        _LYING, tools_invoked=[], surface="web", record_signal=False
    )
    assert out.blocked is True
    assert out.verdict.is_hallucination is True
    assert out.content != _LYING
    assert "garde-fou" in out.content.lower()
    # original suspect text is preserved inside the warning (auditability)
    assert _LYING in out.content
    assert out.verdict.matched_patterns  # at least one pattern fired


def test_locale_en_produces_english_warning():
    out = verify_outcome(
        _LYING,
        tools_invoked=[],
        surface="web",
        locale="en",
        record_signal=False,
    )
    assert out.blocked is True
    assert "safety guard" in out.content.lower()


# ──────────────────────────────────────────────────────────────────────
# Learning signal — uniform side effect (the §6.8 funnel win)
# ──────────────────────────────────────────────────────────────────────


def test_block_records_learning_signal_tagged_with_surface(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.output_verifier._spawn_hallucination_signal",
        lambda **kw: calls.append(kw),
    )
    out = verify_outcome(
        _LYING,
        tools_invoked=[],
        surface="scheduler",
        user_id="u1",
        conversation_id="c1",
        model_used="gemma",
    )
    assert out.blocked is True
    assert len(calls) == 1
    kw = calls[0]
    assert kw["surface"] == "scheduler"
    assert kw["user_id"] == "u1"
    assert kw["conversation_id"] == "c1"
    assert kw["original_content"] == _LYING
    assert kw["verdict"].is_hallucination is True


def test_record_signal_false_skips_the_signal(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.output_verifier._spawn_hallucination_signal",
        lambda **kw: calls.append(kw),
    )
    out = verify_outcome(
        _LYING, tools_invoked=[], surface="web", record_signal=False
    )
    assert out.blocked is True
    assert calls == []


def test_clean_content_never_records_a_signal(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.output_verifier._spawn_hallucination_signal",
        lambda **kw: calls.append(kw),
    )
    verify_outcome("Rien à signaler.", tools_invoked=[], surface="web")
    assert calls == []


# ──────────────────────────────────────────────────────────────────────
# Signal kwarg mapping — must match record_hallucination_block's contract
# ──────────────────────────────────────────────────────────────────────


def test_signal_kwargs_map_verdict_fields():
    verdict = GuardVerdict(
        is_hallucination=True,
        matched_patterns=["fr.first_person_past"],
        tools_invoked=["memory_recall"],
        destructive_tools_invoked=[],
        reason="completion_claim_without_destructive_tool_call",
    )
    kw = _hallucination_signal_kwargs(
        verdict=verdict,
        user_id="u1",
        conversation_id="c1",
        model_used="gemma",
        original_content=_LYING,
    )
    assert kw == {
        "user_id": "u1",
        "conversation_id": "c1",
        "model_used": "gemma",
        "matched_patterns": ["fr.first_person_past"],
        "tools_invoked": ["memory_recall"],
        "destructive_tools_invoked": [],
        "reason": "completion_claim_without_destructive_tool_call",
        "original_response": _LYING,
    }


def test_signal_kwargs_default_missing_ids_and_model():
    """record_hallucination_block no-ops on empty ids; model defaults to
    'unknown' — mirror the web caller's ``model_used_out or 'unknown'``."""
    verdict = GuardVerdict(is_hallucination=True, reason="x")
    kw = _hallucination_signal_kwargs(
        verdict=verdict,
        user_id=None,
        conversation_id=None,
        model_used=None,
        original_content="",
    )
    assert kw["user_id"] == ""
    assert kw["conversation_id"] == ""
    assert kw["model_used"] == "unknown"
