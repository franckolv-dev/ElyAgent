# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_critic.py
# @brief      Sprint 3.7 Jalon 4 — pin the LLM-as-judge mission critic :
#             policy B+C sampling, prompt assembly, verdict parsing,
#             persistence, cron entry point.
# @license    MIT
# =============================================================================
"""Tests for app/services/learning/mission_critic.py — Sprint 3.7 Jalon 4."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.learning import mission_critic as mc
from app.services.learning.mission_critic import (
    COMPLETED_SAMPLE_DENOMINATOR,
    _CRITIC_PROMPT,
    compose_prompt,
    parse_verdict,
    should_critique,
)


def _mk_mission(**overrides):
    """Build a duck-typed Mission row the policy/prompt code accepts."""
    base = {
        "id": "m-test-001",
        "goal": "Find duplicate files in Drive",
        "title": None,
        "status": "completed",
        "final_summary": "I removed 12 duplicates.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mk_step(iteration, phase, **overrides):
    base = {
        "iteration": iteration,
        "phase": phase,
        "tool_name": None,
        "tool_output": None,
        "evaluation": None,
        "success": None,
        "duration_ms": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── should_critique policy ────────────────────────────────────────────


@pytest.mark.parametrize("status", ["failed", "aborted"])
def test_should_critique_always_true_on_failed_or_aborted(status) -> None:
    m = _mk_mission(id="any-id", status=status)
    assert should_critique(m) is True


@pytest.mark.parametrize("status", ["draft", "planning", "running", "paused"])
def test_should_critique_false_on_non_terminal_status(status) -> None:
    m = _mk_mission(status=status)
    assert should_critique(m) is False


def test_should_critique_completed_samples_at_one_in_N() -> None:
    """Over many random IDs the rate should land near 1/N (B+C policy)."""
    selected = 0
    total = 500
    for i in range(total):
        m = _mk_mission(id=f"mission-{i:04d}", status="completed")
        if should_critique(m):
            selected += 1
    expected_rate = 1.0 / COMPLETED_SAMPLE_DENOMINATOR
    actual_rate = selected / total
    # Allow ±5 percentage points jitter
    assert abs(actual_rate - expected_rate) < 0.05, (
        f"completed sampling drifted: {actual_rate:.3f} vs target {expected_rate:.3f}"
    )


def test_should_critique_is_deterministic_for_same_id() -> None:
    """Same mission_id → same decision every time. Cron retries must be no-ops."""
    m = _mk_mission(id="stable-mission", status="completed")
    decisions = [should_critique(m) for _ in range(10)]
    assert len(set(decisions)) == 1


# ── compose_prompt shape ─────────────────────────────────────────────


def test_compose_prompt_embeds_goal_status_final_summary() -> None:
    m = _mk_mission(
        goal="Clean my Gmail",
        status="failed",
        final_summary="All clean.",
    )
    steps = [_mk_step(1, "plan"), _mk_step(2, "act", tool_name="gmail_list_emails", success=True)]
    prompt = compose_prompt(m, steps)
    assert "Clean my Gmail" in prompt
    assert "status=" in prompt.lower() or "Status final" in prompt
    assert "failed" in prompt
    assert "All clean." in prompt
    assert "gmail_list_emails" in prompt


def test_compose_prompt_truncates_to_last_30_steps() -> None:
    m = _mk_mission()
    steps = [_mk_step(i, "act", tool_name=f"tool_{i}") for i in range(1, 51)]
    prompt = compose_prompt(m, steps)
    # Last 30 should appear, first 20 shouldn't
    assert "tool_50" in prompt
    assert "tool_21" in prompt
    assert "tool_20" not in prompt
    assert "tool_1\n" not in prompt and "tool_1 " not in prompt


def test_compose_prompt_handles_empty_steps_list() -> None:
    m = _mk_mission()
    prompt = compose_prompt(m, [])
    assert "aucune étape" in prompt.lower()


# ── parse_verdict robustness ─────────────────────────────────────────


def test_parse_verdict_clean_json() -> None:
    raw = json.dumps({
        "quality_score": 85,
        "honest_completion": True,
        "wasted_effort": False,
        "user_should_have_been_warned": False,
        "main_issue": "",
    })
    v = parse_verdict(raw)
    assert v == {
        "quality_score": 85,
        "honest_completion": True,
        "wasted_effort": False,
        "user_should_have_been_warned": False,
        "main_issue": None,  # empty string becomes None
    }


def test_parse_verdict_strips_markdown_fences() -> None:
    raw = "```json\n" + json.dumps({"quality_score": 50}) + "\n```"
    v = parse_verdict(raw)
    assert v is not None
    assert v["quality_score"] == 50
    # missing fields default safely
    assert v["honest_completion"] is True
    assert v["wasted_effort"] is False


def test_parse_verdict_clamps_quality_score_to_0_100() -> None:
    over = parse_verdict(json.dumps({"quality_score": 9999}))
    assert over["quality_score"] == 100
    under = parse_verdict(json.dumps({"quality_score": -50}))
    assert under["quality_score"] == 0


def test_parse_verdict_returns_none_on_invalid_json() -> None:
    assert parse_verdict("totally not JSON, sorry.") is None
    assert parse_verdict("") is None


def test_parse_verdict_returns_none_on_top_level_array() -> None:
    """LLMs sometimes wrap in a list. We refuse — only objects pass."""
    assert parse_verdict("[1, 2, 3]") is None


# ── Disabled toggle ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_critique_mission_short_circuits_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CRITIC_DISABLED", "true")
    # Even with a "happy" mission id, returns None without touching DB
    result = await mc.critique_mission("does-not-exist-anyway")
    assert result is None


# ── run_pending_critiques cron entry ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_pending_critiques_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CRITIC_DISABLED", "true")
    assert await mc.run_pending_critiques() == 0


# ── list-content coercion (cron crash regression) ────────────────────


@pytest.mark.asyncio
async def test_call_critic_llm_flattens_list_content(monkeypatch) -> None:
    """Regression — providers like openai-codex (Responses API v0) and
    Gemini multimodal return ``content`` as a LIST of typed blocks
    ``[{"type": "text", "text": "..."}]`` rather than a string.

    Left raw, that list flows into ``parse_verdict`` → ``_strip_json_fences``
    → ``raw.strip()`` and the cron dies every 5 min with
    ``'list' object has no attribute 'strip'`` — silently killing the whole
    mission-critique / self-improvement signal. ``_call_critic_llm`` must
    flatten the content to a plain string at the boundary.
    """
    import app.services.llm_provider as llm_provider

    verdict_json = '{"quality_score": 70, "honest_completion": false}'

    class _FakeLLM:
        model = "fake-codex-model"

        async def ainvoke(self, messages, config=None):
            return SimpleNamespace(
                content=[{"type": "text", "text": verdict_json, "index": 0}],
                response_metadata={},
            )

    monkeypatch.setattr(llm_provider, "get_llm_for_tier", lambda tier: _FakeLLM())

    raw, _tokens, model_name = await mc._call_critic_llm("some prompt")

    assert isinstance(raw, str), f"content must be flattened to str, got {type(raw)}"
    assert raw == verdict_json
    assert model_name == "fake-codex-model"
    # The exact thing that crashed must now succeed end-to-end.
    verdict = parse_verdict(raw)
    assert verdict is not None
    assert verdict["quality_score"] == 70
    assert verdict["honest_completion"] is False


# ── main.py wiring guard ─────────────────────────────────────────────


def test_main_py_schedules_mission_critic_cron() -> None:
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")
    assert "mission_critic_loop" in src, (
        "main.py must schedule the mission_critic_loop APScheduler job — "
        "without it the Jalon 4 cron never runs in production."
    )
    assert "run_pending_critiques" in src
    assert "minutes=5" in src or "minutes = 5" in src


# ── prompt template version is hashable + stable ─────────────────────


def test_critic_prompt_template_is_non_empty_and_unicode_safe() -> None:
    from app.services.learning.prompt_version import prompt_hash
    h = prompt_hash(_CRITIC_PROMPT)
    assert len(h) == 8
    # Sanity check: must contain key instructions
    assert "succès en façade" in _CRITIC_PROMPT
    assert "quality_score" in _CRITIC_PROMPT
    assert "JSON STRICT" in _CRITIC_PROMPT
