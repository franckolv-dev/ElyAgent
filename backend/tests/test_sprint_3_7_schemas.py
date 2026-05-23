# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sprint_3_7_schemas.py
# @brief      Sprint 3.7 Jalon 1 — pin the SQL schemas of the 4 new tables
#             (hitl_refusals, hallucination_blocks, provider_switches,
#             mission_critiques) so an accidental column rename or
#             deletion fails the suite.
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Schema pin for Sprint 3.7 V1 Jalon 1.

Why: the four new tables are the foundation for all auto-improvement
work that follows (Jalons 2-7). Drift here cascades — every downstream
service that reads/writes these tables will silently break or insert
NULL where a value is expected. This test fails loudly the moment a
column moves.
"""
from __future__ import annotations

import pytest

from app.models.hallucination_block import HallucinationBlock
from app.models.hitl_refusal import HitlRefusal
from app.models.mission_critique import MissionCritique
from app.models.provider_switch import ProviderSwitch


# ── Table names are part of the contract — services reference them ────


@pytest.mark.parametrize(
    "model,expected_table",
    [
        (HitlRefusal, "hitl_refusals"),
        (HallucinationBlock, "hallucination_blocks"),
        (ProviderSwitch, "provider_switches"),
        (MissionCritique, "mission_critiques"),
    ],
)
def test_model_tablename_is_stable(model, expected_table) -> None:
    assert model.__tablename__ == expected_table


# ── Each table must carry the columns the design note §2 + §4 calls for ─


_HITL_REFUSAL_COLUMNS = {
    "id", "user_id", "conversation_id", "mission_id", "tool_name",
    "args_redacted", "action_description", "decision", "reason",
    "tier_llm", "prompt_version", "created_at",
}
_HALLUCINATION_BLOCK_COLUMNS = {
    "id", "user_id", "conversation_id", "mission_id", "model_used",
    "tier_llm", "matched_patterns", "tools_invoked",
    "destructive_tools_invoked", "reason", "original_response",
    "prompt_version", "created_at",
}
_PROVIDER_SWITCH_COLUMNS = {
    "id", "user_id", "conversation_id", "tier_llm", "from_provider",
    "to_provider", "reason", "position_in_chain", "prompt_version",
    "created_at",
}
_MISSION_CRITIQUE_COLUMNS = {
    "id", "mission_id", "critic_model", "quality_score",
    "honest_completion", "wasted_effort", "user_should_have_been_warned",
    "main_issue", "prompt_version", "tokens_used", "duration_ms",
    "created_at",
}


@pytest.mark.parametrize(
    "model,expected_columns",
    [
        (HitlRefusal, _HITL_REFUSAL_COLUMNS),
        (HallucinationBlock, _HALLUCINATION_BLOCK_COLUMNS),
        (ProviderSwitch, _PROVIDER_SWITCH_COLUMNS),
        (MissionCritique, _MISSION_CRITIQUE_COLUMNS),
    ],
)
def test_model_columns_match_design_note(model, expected_columns) -> None:
    actual = {c.name for c in model.__table__.columns}
    missing = expected_columns - actual
    extra = actual - expected_columns
    assert not missing, (
        f"{model.__name__} is missing columns the design note requires: {sorted(missing)}"
    )
    assert not extra, (
        f"{model.__name__} has unexpected columns (drift from design note): {sorted(extra)}"
    )


# ── prompt_version typing — sha256[:8] = 8 chars, allow up to 16 ─────


@pytest.mark.parametrize(
    "model",
    [HitlRefusal, HallucinationBlock, ProviderSwitch, MissionCritique],
)
def test_prompt_version_column_is_short_string(model) -> None:
    col = model.__table__.columns["prompt_version"]
    # SQLAlchemy String length is on col.type.length
    assert col.type.length == 16, (
        f"{model.__name__}.prompt_version should be VARCHAR(16) for sha256[:8] + headroom"
    )


# ── mission_critique uniqueness — one critique per mission ──────────


def test_mission_critique_is_unique_per_mission() -> None:
    """A mission gets critiqued at most once (design note §4.3 — UNIQUE
    on mission_id). Re-runs should update in place, not duplicate."""
    col = MissionCritique.__table__.columns["mission_id"]
    assert col.unique is True, (
        "mission_critiques.mission_id must be UNIQUE — the cron updates "
        "in place, doesn't append. Drift here causes silent duplicate rows."
    )


# ── _safe_columns in database.py adds prompt_version to existing tables ─


def test_database_module_declares_prompt_version_columns() -> None:
    """The Jalon 1 colonnes added via _safe_columns must be declared in
    database.py. We grep the source rather than introspecting a live
    SQLite to keep the test hermetic."""
    from pathlib import Path

    db_path = Path(__file__).resolve().parents[1] / "app" / "database.py"
    src = db_path.read_text(encoding="utf-8")

    # Every table receiving prompt_version must be in _safe_columns
    for table in ("feedback", "mission_steps", "error_log"):
        marker = f'("{table}", "prompt_version"'
        assert marker in src, (
            f"_safe_columns is missing prompt_version on table {table!r}. "
            f"Jalon 1 design note §3 requires it for A/B correlation."
        )
    # Missions table gets critic_run_at for the LLM-as-judge cron
    assert '("missions", "critic_run_at"' in src, (
        "_safe_columns is missing critic_run_at on missions table. "
        "Jalon 4 cron will scan WHERE critic_run_at IS NULL."
    )
