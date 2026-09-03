# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_bench_base.py
# @brief      Sprint 3.7.3 J1 — unit tests for bench/scenarios/_base.py
# @license    MIT
# =============================================================================
"""Pin the contract of the bench scenario helper module.

These are pure-function tests (anonymisation, tag normalisation, check
conversion) plus one async integration test for the throwaway_user
context manager.

Important: the unit tests run inside pytest, the bench harness runs
standalone. The two suites share the helper module so we ping its
behaviour from both sides to catch breakage early.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make `bench.scenarios._base` importable from pytest (which lives under
# backend/) without polluting sys.path globally.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────
# normalise_tags + tags_intersect
# ─────────────────────────────────────────────────────────────────────────


def test_normalise_tags_default_when_missing() -> None:
    from bench.scenarios._base import DEFAULT_TAGS, normalise_tags
    assert normalise_tags(None)   == list(DEFAULT_TAGS)
    assert normalise_tags([])     == list(DEFAULT_TAGS)
    assert normalise_tags("")     == list(DEFAULT_TAGS)


def test_normalise_tags_accepts_string_form() -> None:
    """A scenario author may write ``TAGS = "shallow"`` instead of a list."""
    from bench.scenarios._base import normalise_tags
    assert normalise_tags("shallow") == ["shallow"]
    assert normalise_tags("MEDIUM")  == ["medium"]  # case-insensitive


def test_normalise_tags_drops_unknown_values() -> None:
    """Unknown tags are forward-compatible: silently dropped, no raise."""
    from bench.scenarios._base import normalise_tags
    assert normalise_tags(["shallow", "exotic", "deep"]) == ["shallow", "deep"]


def test_normalise_tags_deduplicates() -> None:
    from bench.scenarios._base import normalise_tags
    assert normalise_tags(["shallow", "shallow", "deep"]) == ["shallow", "deep"]


def test_normalise_tags_all_unknown_falls_back_to_default() -> None:
    """All-junk input should not yield an empty list — the harness needs
    SOMETHING to filter on. We fall back to the documented default."""
    from bench.scenarios._base import DEFAULT_TAGS, normalise_tags
    assert normalise_tags(["nope", "zzz"]) == list(DEFAULT_TAGS)


def test_tags_intersect_matches_on_any_overlap() -> None:
    from bench.scenarios._base import tags_intersect
    assert tags_intersect(["shallow"], ["shallow", "medium"]) is True
    assert tags_intersect(["deep"],    ["shallow", "medium"]) is False
    assert tags_intersect([],          ["shallow"])           is False


# ─────────────────────────────────────────────────────────────────────────
# anonymise_text
# ─────────────────────────────────────────────────────────────────────────


def test_anonymise_text_handles_none_and_empty() -> None:
    from bench.scenarios._base import anonymise_text
    assert anonymise_text(None) == ""
    assert anonymise_text("")   == ""


def test_anonymise_text_scrubs_email() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Envoyer à franck.ollivier@example.com SVP")
    assert "franck.ollivier" not in out
    assert "<email>" in out


def test_anonymise_text_scrubs_phone() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Appelez moi au +33 6 12 34 56 78")
    assert "12 34 56 78" not in out
    assert "<phone>" in out


def test_anonymise_text_scrubs_iban() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text("Mon IBAN FR7630006000011234567890189 svp")
    assert "FR7630006000011234567890189" not in out
    assert "<iban>" in out


def test_anonymise_text_scrubs_url_and_gmaps() -> None:
    from bench.scenarios._base import anonymise_text
    out = anonymise_text(
        "RDV https://google.fr/maps/place/Tour+Eiffel/@48.8584 demain"
    )
    # Either <maps> (more specific) or <url> (fallback) is acceptable.
    assert "google.fr" not in out
    assert any(token in out for token in ("<maps>", "<url>"))


def test_anonymise_text_preserves_innocuous_text() -> None:
    """Pure prose with no PII shouldn't be altered."""
    from bench.scenarios._base import anonymise_text
    text = "L'utilisateur a refusé la suppression des mails marketing."
    assert anonymise_text(text) == text


# ─────────────────────────────────────────────────────────────────────────
# from_checks
# ─────────────────────────────────────────────────────────────────────────


def test_from_checks_all_pass_marks_pass_true() -> None:
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True, "b": True})
    assert out["pass"] is True
    assert out["checks"] == {"a": True, "b": True}
    assert "failed_checks" not in out  # only present on failure


def test_from_checks_any_fail_lists_failed_keys() -> None:
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True, "b": False, "c": False})
    assert out["pass"] is False
    assert out["failed_checks"] == ["b", "c"]


def test_from_checks_passes_extra_through() -> None:
    """Caller's metadata must reach the result dict untouched."""
    from bench.scenarios._base import from_checks
    out = from_checks({"a": True}, signal_id=42, reason="check")
    assert out["signal_id"] == 42
    assert out["reason"]    == "check"


# ─────────────────────────────────────────────────────────────────────────
# throwaway_user (real DB integration)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_throwaway_user_creates_and_cleans_up() -> None:
    """Smoke the context manager: user exists during the block, gone after."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.user import User
    from bench.scenarios._base import throwaway_user

    async with throwaway_user(prefix="bench_unittest") as uid:
        assert uid.startswith("bench_unittest_")
        async with async_session() as db:
            u = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            assert u is not None, "user should exist inside the block"

    # After exit, the row must be gone.
    async with async_session() as db:
        u = (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one_or_none()
        assert u is None, "user should be wiped on context exit"


@pytest.mark.asyncio
async def test_throwaway_user_cleans_user_scoped_artefacts() -> None:
    """If the scenario writes user-scoped rows, the cleanup must wipe them
    so re-runs stay idempotent."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning import record_hitl_refusal
    from bench.scenarios._base import throwaway_user

    async with throwaway_user(prefix="bench_scope") as uid:
        await record_hitl_refusal(
            user_id=uid,
            conversation_id="conv-cleanup",
            tool_name="dummy",
            args={},
            action_description="x",
            decision="deny",
            reason="test",
        )
        async with async_session() as db:
            rows = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.user_id == uid)
            )).scalars().all()
            assert len(rows) == 1

    # After exit, the row must be gone too.
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlRefusal).where(HitlRefusal.user_id == uid)
        )).scalars().all()
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────
# seed_mission_with_critique + mission cleanup (J2)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_mission_with_critique_creates_both_rows() -> None:
    """The J2 seeder must insert a Mission AND its MissionCritique, linked
    on mission_id, both reclaimed by throwaway_user on exit (no user_id on
    MissionCritique, so this exercises _cleanup_missions)."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.mission import Mission
    from app.models.mission_critique import MissionCritique
    from bench.scenarios._base import (
        seed_mission_with_critique,
        throwaway_user,
    )

    async with throwaway_user(prefix="bench_seed") as uid:
        mission_id, critique_id = await seed_mission_with_critique(
            uid,
            status="completed",
            goal="Tâche de test",
            critic_model="deepseek-v4-pro",
            quality_score=20,
            honest_completion=False,
            wasted_effort=False,
            user_should_have_been_warned=True,
            main_issue="prétend avoir fini sans appel d'outil",
        )
        assert mission_id and critique_id is not None
        async with async_session() as db:
            mission = (await db.execute(
                select(Mission).where(Mission.id == mission_id)
            )).scalar_one_or_none()
            critique = (await db.execute(
                select(MissionCritique).where(
                    MissionCritique.id == critique_id
                )
            )).scalar_one_or_none()
        assert mission is not None and mission.user_id == uid
        assert mission.critic_run_at is not None  # mirrors the real cron
        assert critique is not None
        assert critique.mission_id == mission_id
        assert critique.quality_score == 20

    # After exit, BOTH mission + critique must be gone (FK-aware cleanup).
    async with async_session() as db:
        mission = (await db.execute(
            select(Mission).where(Mission.id == mission_id)
        )).scalar_one_or_none()
        critique = (await db.execute(
            select(MissionCritique).where(MissionCritique.id == critique_id)
        )).scalar_one_or_none()
    assert mission is None, "mission should be wiped on context exit"
    assert critique is None, "critique should be wiped on context exit"


# ─────────────────────────────────────────────────────────────────────────
# gen_critique_scenarios catalogue invariants (J2)
# ─────────────────────────────────────────────────────────────────────────


def test_catalogue_has_30_unique_slugs() -> None:
    from bench.gen_critique_scenarios import CATALOGUE
    slugs = [p["slug"] for p in CATALOGUE]
    assert len(slugs) == 30
    assert len(set(slugs)) == 30


def test_catalogue_validates_clean() -> None:
    from bench.gen_critique_scenarios import _validate_catalogue
    assert _validate_catalogue() == []


def test_catalogue_covers_status_and_score_spread() -> None:
    """Regression net needs breadth: all 3 terminal statuses, both honesty
    values, and the capture/fingerprint boundaries present."""
    from bench.gen_critique_scenarios import CATALOGUE
    statuses = {p["status"] for p in CATALOGUE}
    assert statuses == {"completed", "failed", "aborted"}
    assert any(not p["honest_completion"] for p in CATALOGUE)
    assert any(p["honest_completion"] for p in CATALOGUE)
    scores = {p["quality_score"] for p in CATALOGUE}
    assert 59 in scores and 60 in scores      # capture boundary, both sides
    assert any(s < 30 for s in scores)        # fingerprint boundary
    assert any(s >= 80 for s in scores)       # high-quality end


def test_is_actionable_matches_capture_filter() -> None:
    """is_actionable() must mirror capture_from_mission_critique's filter:
    captured iff quality_score < 60 OR dishonest."""
    from bench.gen_critique_scenarios import is_actionable
    assert is_actionable({"quality_score": 59, "honest_completion": True})
    assert not is_actionable({"quality_score": 60, "honest_completion": True})
    assert is_actionable({"quality_score": 85, "honest_completion": False})
    assert not is_actionable({"quality_score": 95, "honest_completion": True})


def test_catalogue_actionable_split_is_balanced() -> None:
    """Both branches of the filter must be exercised — a net that only
    tests 'captured' would miss a tool wrongly capturing good missions."""
    from bench.gen_critique_scenarios import CATALOGUE, is_actionable
    actionable = [p for p in CATALOGUE if is_actionable(p)]
    skipped = [p for p in CATALOGUE if not is_actionable(p)]
    assert len(actionable) >= 15
    assert len(skipped) >= 5


def test_rendered_scenario_compiles_and_has_contract() -> None:
    """Every generated module must be valid Python exposing the runner
    contract (NAME / TAGS / async def run)."""
    from bench.gen_critique_scenarios import CATALOGUE, _render_scenario
    src = _render_scenario(1, CATALOGUE[0])
    compile(src, "<scenario_critique_01>", "exec")  # raises on syntax error
    assert "async def run()" in src
    assert 'TAGS = ["shallow"]' in src
    assert "AUTO-GENERATED" in src


@pytest.mark.asyncio
async def test_is_actionable_predicts_real_capture_outcome() -> None:
    """Tie the catalogue's actionability label to the REAL failure_capture
    function on the 59/60 boundary + dishonest-high-score — so a drift in
    the production filter breaks this test, not just the bench."""
    from app.services.learning.failure_capture import (
        capture_from_mission_critique,
    )
    from bench.scenarios._base import (
        seed_mission_with_critique,
        throwaway_user,
    )

    cases = [
        # (quality_score, honest, expect_failure_case)
        (59, True, True),    # just under threshold → captured
        (60, True, False),   # at threshold + honest → skipped
        (85, False, True),   # dishonest high score → captured
    ]
    async with throwaway_user(prefix="bench_pred") as uid:
        for score, honest, expect in cases:
            mission_id, critique_id = await seed_mission_with_critique(
                uid,
                status="completed",
                goal=f"case {score}/{honest}",
                critic_model="deepseek-v4-pro",
                quality_score=score,
                honest_completion=honest,
                wasted_effort=False,
                user_should_have_been_warned=False,
                main_issue=None if honest and score >= 60 else "souci",
            )
            fc_id = await capture_from_mission_critique(
                signal_id=critique_id,
                user_id=uid,
                mission_id=mission_id,
                critic_model="deepseek-v4-pro",
                quality_score=score,
                honest_completion=honest,
                wasted_effort=False,
                user_should_have_been_warned=False,
                main_issue=None if honest and score >= 60 else "souci",
            )
            assert (fc_id is not None) is expect, (
                f"score={score} honest={honest}: expected "
                f"{'capture' if expect else 'skip'}"
            )


@pytest.mark.asyncio
async def test_throwaway_user_cleans_hitl_preference() -> None:
    """J3 added ``HitlPreference`` to the cleanup list (scenario I writes
    one). Verify a preference row is reclaimed on context exit so re-runs
    stay idempotent on the shared SQLite file."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.hitl_preference import HitlPreference
    from app.services.hitl_preferences import set_user_preference
    from bench.scenarios._base import throwaway_user

    async with throwaway_user(prefix="bench_pref") as uid:
        ok = await set_user_preference(
            uid, "gmail_list_emails", requires_confirmation=False
        )
        assert ok is True
        async with async_session() as db:
            rows = (await db.execute(
                select(HitlPreference).where(HitlPreference.user_id == uid)
            )).scalars().all()
            assert len(rows) == 1

    async with async_session() as db:
        rows = (await db.execute(
            select(HitlPreference).where(HitlPreference.user_id == uid)
        )).scalars().all()
        assert rows == [], "hitl_preferences must be wiped on context exit"
