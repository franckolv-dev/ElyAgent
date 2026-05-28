# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_ab_testing.py
# @brief      Sprint 3.7 Jalon 5 — pin select_variant determinism, the
#             composite ab_score formula, and the score_variants
#             aggregation contract.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for app/services/learning/ab_testing.py — Sprint 3.7 Jalon 5."""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from app.services.learning import ab_testing as ab
from app.services.learning.ab_testing import (
    DEFAULT_WEIGHTS,
    ab_score,
    register_variant,
    score_variants,
    select_variant,
)


@pytest.fixture(autouse=True)
def _isolate_variants(monkeypatch):
    """Reset the variants registry between tests so envs don't bleed."""
    monkeypatch.setattr(ab, "_VARIANTS", None)
    yield
    monkeypatch.setattr(ab, "_VARIANTS", None)


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    """Ensure all tables exist before any test queries them.

    Locally the dev DB persists between runs so this is a no-op, but CI
    uses ``sqlite+aiosqlite:///:memory:`` (fresh per session) where the
    ``mission_steps`` table only exists after ``init_db()``. Without
    this, the integration tests that call ``score_variants`` blow up
    with ``no such table: mission_steps``.
    """
    from app.database import init_db
    await init_db()


# ── select_variant ────────────────────────────────────────────────────


def test_select_variant_single_variant_returns_it() -> None:
    """V1 default state : only "A" registered → always pick it."""
    name, text = select_variant("system_prompt_base", "user-1")
    assert name == "A"
    assert isinstance(text, str)
    assert len(text) > 0


def test_select_variant_is_deterministic_per_user(monkeypatch) -> None:
    """Same user_id → same variant every time. Required so a person
    doesn't drift between A and B across sessions."""
    register_variant("system_prompt_base", "B", "VARIANT B PROMPT")
    monkeypatch.setenv("AB_SYSTEM_PROMPT_BASE_B_PCT", "50")
    picks = [select_variant("system_prompt_base", "stable-user")[0] for _ in range(20)]
    assert len(set(picks)) == 1, f"variant drifted across calls: {picks}"


def test_select_variant_distributes_at_50_percent(monkeypatch) -> None:
    """Over many user_ids, AB_X_B_PCT=50 yields roughly 50/50."""
    register_variant("system_prompt_base", "B", "VARIANT B PROMPT")
    monkeypatch.setenv("AB_SYSTEM_PROMPT_BASE_B_PCT", "50")
    picks = [
        select_variant("system_prompt_base", f"user-{i:04d}")[0]
        for i in range(500)
    ]
    b_count = picks.count("B")
    a_count = picks.count("A")
    # Allow ±5 percentage points jitter
    assert abs(b_count - a_count) < 50, (
        f"distribution skewed: A={a_count} B={b_count}"
    )


def test_select_variant_at_zero_pct_only_picks_A(monkeypatch) -> None:
    register_variant("system_prompt_base", "B", "VARIANT B PROMPT")
    monkeypatch.setenv("AB_SYSTEM_PROMPT_BASE_B_PCT", "0")
    for i in range(100):
        name, _ = select_variant("system_prompt_base", f"user-{i}")
        assert name == "A"


def test_select_variant_at_100_pct_only_picks_B(monkeypatch) -> None:
    register_variant("system_prompt_base", "B", "VARIANT B PROMPT")
    monkeypatch.setenv("AB_SYSTEM_PROMPT_BASE_B_PCT", "100")
    for i in range(100):
        name, _ = select_variant("system_prompt_base", f"user-{i}")
        assert name == "B"


def test_select_variant_falls_back_to_A_when_B_missing(monkeypatch) -> None:
    """Even if AB_X_B_PCT=100, if "B" isn't registered → fall back to A."""
    # Only A in registry (no register_variant call here)
    monkeypatch.setenv("AB_SYSTEM_PROMPT_BASE_B_PCT", "100")
    name, _ = select_variant("system_prompt_base", "any-user")
    assert name == "A"


def test_select_variant_unknown_key_falls_back_to_base_prompt() -> None:
    """An unknown prompt key shouldn't crash. Emergency fallback to live
    _SYSTEM_PROMPT_BASE."""
    name, text = select_variant("never-registered-key", "u1")
    assert name == "A"
    assert isinstance(text, str)
    assert len(text) > 0


def test_select_variant_empty_user_id_does_not_crash() -> None:
    name, _ = select_variant("system_prompt_base", "")
    assert name == "A"


# ── ab_score formula ──────────────────────────────────────────────────


def test_ab_score_perfect_metrics_yields_1() -> None:
    score = ab_score({
        "hitl_refusal_rate": 0.0,
        "hallucination_rate": 0.0,
        "feedback_mean": 1.0,
        "completion_rate": 1.0,
    })
    assert score == pytest.approx(1.0, abs=1e-9)


def test_ab_score_worst_metrics_yields_0() -> None:
    score = ab_score({
        "hitl_refusal_rate": 1.0,
        "hallucination_rate": 1.0,
        "feedback_mean": -1.0,
        "completion_rate": 0.0,
    })
    assert score == pytest.approx(0.0, abs=1e-9)


def test_ab_score_weights_sum_to_one() -> None:
    """The default weights must form a convex combination."""
    s = sum(DEFAULT_WEIGHTS.values())
    assert s == pytest.approx(1.0)


def test_ab_score_handles_missing_metrics_as_worst_case() -> None:
    score = ab_score({})
    assert 0.0 <= score <= 0.3, (
        f"missing metrics should fall toward worst-case, got {score}"
    )


def test_ab_score_clips_out_of_range_inputs() -> None:
    # Rates > 1 or feedback > 1 / < -1 must not break the score
    score = ab_score({
        "hitl_refusal_rate": -0.5,    # below 0 → clipped to 0
        "hallucination_rate": 2.0,    # above 1 → clipped to 1
        "feedback_mean": 5.0,         # above 1 → clipped to 1
        "completion_rate": -0.1,      # below 0 → clipped to 0
    })
    expected = (
        0.30 * (1 - 0.0)  # hitl
        + 0.30 * (1 - 1.0)  # hallu (worst)
        + 0.20 * 1.0  # feedback (best after clip)
        + 0.20 * 0.0  # completion (worst)
    )
    assert score == pytest.approx(expected, abs=1e-9)


def test_ab_score_with_custom_weights() -> None:
    """Custom weights override the defaults for an experiment-specific
    composite formula."""
    custom = {
        "hitl_refusal_rate": 0.50,
        "hallucination_rate": 0.50,
        "feedback_mean": 0.0,
        "completion_rate": 0.0,
    }
    score = ab_score(
        {"hitl_refusal_rate": 0.0, "hallucination_rate": 0.0,
         "feedback_mean": -1.0, "completion_rate": 0.0},
        weights=custom,
    )
    # 0.5 * 1.0 + 0.5 * 1.0 + 0 + 0 = 1.0
    assert score == pytest.approx(1.0, abs=1e-9)


# ── score_variants integration (no LLM, no signals) ──────────────────


@pytest.mark.asyncio
async def test_score_variants_single_variant_returns_warning(monkeypatch) -> None:
    """With only "A" registered, there's no real A/B test to run. The
    function must return the metrics + an explicit warning, not crash."""
    result = await score_variants("system_prompt_base", timedelta(days=7))
    assert result["key"] == "system_prompt_base"
    assert result["winner"] is None
    assert "only one variant" in result["warning"]
    assert "A" in result["variants"]
    # The metrics block exists even if it's all zeros (no data yet)
    metrics_A = result["variants"]["A"]["metrics"]
    assert "n_messages" in metrics_A


@pytest.mark.asyncio
async def test_score_variants_unknown_key_returns_warning() -> None:
    result = await score_variants("nope-this-key-does-not-exist", timedelta(days=7))
    assert result["winner"] is None
    assert "no variants registered" in result["warning"]


@pytest.mark.asyncio
async def test_score_variants_two_variants_no_data_yet_returns_insufficient_warning(
    monkeypatch,
) -> None:
    """A and B both registered but no rows in the signal tables → must
    refuse to declare a winner."""
    register_variant("system_prompt_base", "B", "VARIANT B PROMPT WITH UNIQUE TEXT")
    result = await score_variants("system_prompt_base", timedelta(days=7))
    assert set(result["variants"].keys()) == {"A", "B"}
    assert result["winner"] is None
    assert "insufficient samples" in result["warning"]


# ── _parse_window ─────────────────────────────────────────────────────


@pytest.mark.parametrize("inp,expected_days", [
    ("7d", 7), ("30d", 30), ("90d", 90), ("1d", 1),
])
def test_parse_window_days(inp, expected_days) -> None:
    from app.services.learning.ab_testing import _parse_window
    assert _parse_window(inp).days == expected_days


def test_parse_window_hours() -> None:
    from app.services.learning.ab_testing import _parse_window
    assert _parse_window("24h").total_seconds() == 86400


def test_parse_window_garbage_defaults_to_7d() -> None:
    from app.services.learning.ab_testing import _parse_window
    assert _parse_window("not-a-window").days == 7
    assert _parse_window("").days == 7


# ── Admin endpoint wiring guard ──────────────────────────────────────


def test_admin_py_exposes_ab_score_route() -> None:
    """Hermetic source-grep guard : the admin router must declare the
    /ab/score endpoint, otherwise the frontend (and humans) can't read
    A/B results."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "routers" / "admin.py"
    ).read_text(encoding="utf-8")
    assert '"/ab/score"' in src or "'/ab/score'" in src or "/ab/score" in src
    assert "score_variants" in src
