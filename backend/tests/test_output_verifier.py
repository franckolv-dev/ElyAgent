# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_output_verifier.py
# @brief      Tests for the common OutcomeVerifier — the shared "response
#             verified before delivery" step extracted from the web caller
#             (audit SOL §6.3). Wraps completion_guard + the uniform
#             hallucination learning signal so every surface (web, channels,
#             scheduler, voice) verifies identically.
#
# @license    MIT
#            https://opensource.org/licenses/MIT
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

from pathlib import Path

import pytest

from app.services.completion_guard import GuardVerdict
from app.services.output_verifier import (
    VerifiedOutcome,
    _hallucination_signal_kwargs,
    verify_outcome,
    verify_outcome_from_result,
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
        # C4-4 — la trace des ToolMessages du tour fait partie du contrat
        # du signal (matière du replay shadow) ; absente → liste vide.
        "tool_trace": [],
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


# ──────────────────────────────────────────────────────────────────────
# verify_outcome_from_result — the buffered (ainvoke) surface convenience.
# Channels + scheduler have the full result["messages"], from which the
# tools-in-turn list is derived (no streaming instrumentation needed).
# ──────────────────────────────────────────────────────────────────────


def _ai_with_tool(tool_name: str):
    from langchain_core.messages import AIMessage, ToolMessage

    return [
        AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": {}, "id": "call_1"}],
        ),
        ToolMessage(content="ok", name=tool_name, tool_call_id="call_1"),
    ]


def test_from_result_backed_by_tool_in_messages_passes(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.output_verifier._spawn_hallucination_signal",
        lambda **kw: calls.append(kw),
    )
    invoke_result = {"messages": _ai_with_tool("gmail_trash_by_query")}
    out = verify_outcome_from_result(
        invoke_result, _LYING, surface="telegram", user_message="supprime"
    )
    assert out.blocked is False
    assert out.content == _LYING
    assert calls == []  # backed → no signal


def test_from_result_unbacked_blocks_and_records(monkeypatch):
    from langchain_core.messages import AIMessage

    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.output_verifier._spawn_hallucination_signal",
        lambda **kw: calls.append(kw),
    )
    invoke_result = {"messages": [AIMessage(content=_LYING)]}  # no tool ran
    out = verify_outcome_from_result(
        invoke_result,
        _LYING,
        surface="scheduler",
        user_message="nettoie ma boîte",
        user_id="u1",
        conversation_id="c1",
    )
    assert out.blocked is True
    assert "garde-fou" in out.content.lower()
    assert len(calls) == 1
    assert calls[0]["surface"] == "scheduler"


def test_from_result_non_dict_defaults_to_no_tools():
    """Defensive: a malformed / non-dict result → tools=[] → an unbacked
    completion claim is still caught rather than silently trusted."""
    out = verify_outcome_from_result(
        None, _LYING, surface="telegram", record_signal=False
    )
    assert out.blocked is True


def test_from_result_derives_tools_for_backing():
    """The tools list really comes from the result messages (not passed in):
    a non-destructive tool does not back a completion claim."""
    invoke_result = {"messages": _ai_with_tool("github_repo_stats")}
    out = verify_outcome_from_result(
        invoke_result, _LYING, surface="scheduler", record_signal=False
    )
    assert out.blocked is True  # read-only tool doesn't back "j'ai supprimé"


# ──────────────────────────────────────────────────────────────────────
# Wiring pins (source-grep) — C3c-2 applied the shared verifier to every
# delivery surface. These pins fail loudly if a surface stops routing its
# final response through the OutcomeVerifier before delivery.
# ──────────────────────────────────────────────────────────────────────

_REPO = Path(__file__).resolve().parents[1]

# (relative module path, expected wiring needle). Buffered surfaces use the
# result-deriving helper; the streaming surfaces (web, voice) call
# verify_outcome directly with their own tools_called.
_WIRED_SURFACES = [
    ("app/routers/chat.py", "verify_outcome"),
    ("app/routers/voice.py", 'surface="voice"'),
    ("app/channels/telegram_bot.py", 'surface="telegram"'),
    ("app/services/scheduler.py", 'surface="scheduler"'),
    ("app/mcp_server.py", 'surface="mcp"'),
]


@pytest.mark.parametrize("rel_path, needle", _WIRED_SURFACES)
def test_surface_wires_outcome_verifier(rel_path: str, needle: str):
    src = (_REPO / rel_path).read_text(encoding="utf-8")
    assert "output_verifier" in src, (
        f"{rel_path} must import the shared OutcomeVerifier."
    )
    assert needle in src, (
        f"{rel_path} must route its final response through the OutcomeVerifier "
        f"before delivery (missing {needle!r})."
    )


def test_buffered_surfaces_use_the_result_helper():
    """Channels + scheduler run a buffered ainvoke; they must derive the
    tools-in-turn list via verify_outcome_from_result, not pass [] blindly."""
    for rel_path in (
        "app/channels/telegram_bot.py",
        "app/services/scheduler.py",
        "app/mcp_server.py",
    ):
        src = (_REPO / rel_path).read_text(encoding="utf-8")
        assert "verify_outcome_from_result" in src, (
            f"{rel_path} (buffered ainvoke surface) must use "
            "verify_outcome_from_result so tools are derived from result messages."
        )

# mcp_server.py (ely_chat) était la surface différée de C3c-2 (consommateur
# machine, pas de suivi d'outils) — câblée en C3d-1 : le helper dérive les
# outils du result, l'avertissement honnête s'applique aussi aux clients MCP.
