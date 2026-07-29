# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_sprint_3_7_schemas.py
# @brief      Sprint 3.7 Jalon 1 — pin the SQL schemas of the 4 new tables
#             (hitl_refusals, hallucination_blocks, provider_switches,
#             mission_critiques) so an accidental column rename or
#             deletion fails the suite.
# @license    Elastic License 2.0
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
    # Sprint 4d J1 — origine du tool au moment du refus ("learned"|"builtin"),
    # posée à la capture pour les gates de graduation (migration 0005).
    "tool_origin",
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
    """Les colonnes du Jalon 1 sont déclarées sur leurs modèles.

    ⚠️ Ce test grepait `_safe_columns` dans `app/database.py`. Cette liste a
    été retirée le 29/07 (ménage lot 2) : elle rejouait 19 `ALTER TABLE` sans
    effet à chaque boot, toutes ces colonnes étant déjà dans les modèles ET
    dans la base de production.

    Le pin épingle donc désormais la **propriété** — la colonne existe dans le
    schéma que `create_all` va produire — au lieu du **mécanisme** qui la
    posait. Un pin sur le mécanisme rougit dès qu'on change de mécanisme, sans
    que rien de réel ait bougé. On reste hermétique : `Base.metadata` se lit
    sans base ni boucle asynchrone.
    """
    from app.database import Base
    import app.models  # noqa: F401 — enregistre toutes les tables

    # Chaque table qui porte prompt_version, pour la corrélation A/B
    # (note de conception Jalon 1 §3).
    for table in ("feedback", "mission_steps", "error_log"):
        assert table in Base.metadata.tables, f"table {table!r} absente du schéma"
        assert "prompt_version" in Base.metadata.tables[table].columns, (
            f"{table}.prompt_version manquante — la corrélation A/B du "
            f"Jalon 1 §3 ne peut plus se faire."
        )

    # missions.critic_run_at : le cron LLM-as-judge balaye WHERE critic_run_at IS NULL
    assert "critic_run_at" in Base.metadata.tables["missions"].columns, (
        "missions.critic_run_at manquante — le cron du Jalon 4 balaye "
        "WHERE critic_run_at IS NULL."
    )
