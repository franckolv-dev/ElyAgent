# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_curator.py
# @brief      Sprint 4b Phase 5.a — tests for the auto-skill curator
# @license    Elastic License 2.0
# =============================================================================
"""Tests for `app/services/learning/skill_curator.py`.

Three layers :
  1. Pure helper tests — stale / archivable detection on a fake row
  2. Eligible-skills query — filters out pinned / candidate / rejected /
     user_added / imported_marketplace
  3. End-to-end `run_curator_cycle` with seeded skills at various
     ages — verifies the right transitions happen + idempotence
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning.skill_curator import (
    DEFAULT_ARCHIVE_AFTER_DAYS,
    DEFAULT_STALE_AFTER_DAYS,
    _is_active_stale,
    _is_stale_archivable,
    _load_eligible_skills,
    run_curator_cycle,
)


@pytest_asyncio.fixture
async def _seeded_user():
    await init_db()
    from app.models.user import User
    async with async_session() as db:
        existing = (await db.execute(
            select(User).where(User.id == "cu1")
        )).scalar_one_or_none()
        if existing is None:
            db.add(User(
                id="cu1",
                username="curator_test",
                email="cu1@test.local",
                hashed_password="x",
            ))
            await db.commit()
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == "cu1"))
        await db.commit()
    yield "cu1"


async def _seed_skill(
    user_id: str,
    *,
    name: str | None = None,
    status: str = SkillStatus.ACTIVE,
    source: str = SkillSource.AUTO_GENERATED,
    last_used_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    pinned: bool = False,
) -> str:
    """Insert a skill with custom timestamps (useful for the age tests)."""
    async with async_session() as db:
        skill = LearnedSkill(
            user_id=user_id,
            name=name or f"skill-{uuid.uuid4().hex[:8]}",
            description="a curator test skill",
            content="# x",
            frontmatter_json="{}",
            status=status,
            source=source,
            iteration_count=1,
            from_failure_case_ids="[]",
            pinned=pinned,
        )
        db.add(skill)
        await db.flush()
        # Override timestamps after flush (default values are set by ORM)
        if last_used_at is not None:
            skill.last_used_at = last_used_at
        if created_at is not None:
            skill.created_at = created_at
        if updated_at is not None:
            skill.updated_at = updated_at
        await db.commit()
        await db.refresh(skill)
        return skill.id


# ────────────────────────────────────────────────────────────────────────
# _is_active_stale + _is_stale_archivable
# ────────────────────────────────────────────────────────────────────────


def test_is_active_stale_recent_skill_is_not_stale():
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.ACTIVE,
        last_used_at=now - timedelta(days=5),
        created_at=now - timedelta(days=30),
    )
    assert _is_active_stale(skill, now, stale_after_days=30) is False


def test_is_active_stale_old_skill_is_stale():
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.ACTIVE,
        last_used_at=now - timedelta(days=45),
        created_at=now - timedelta(days=60),
    )
    assert _is_active_stale(skill, now, stale_after_days=30) is True


def test_is_active_stale_never_used_falls_back_to_created_at():
    """A skill that was just promoted today (last_used_at=None) shouldn't
    be stale on its very first curator run — we fall back to created_at."""
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.ACTIVE,
        last_used_at=None,
        created_at=now - timedelta(days=2),
    )
    assert _is_active_stale(skill, now, stale_after_days=30) is False

    # Same skill, but created 60 days ago and never used → stale
    skill = SimpleNamespace(
        status=SkillStatus.ACTIVE,
        last_used_at=None,
        created_at=now - timedelta(days=60),
    )
    assert _is_active_stale(skill, now, stale_after_days=30) is True


def test_is_active_stale_only_runs_on_active_status():
    """Curator must not 'stale' a candidate or rejected skill — those
    have separate semantics."""
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.CANDIDATE,
        last_used_at=None,
        created_at=now - timedelta(days=365),
    )
    assert _is_active_stale(skill, now, stale_after_days=30) is False


def test_is_stale_archivable_handles_stale_status_only():
    """A skill that's still active should never be archivable by this
    helper — caller (run_curator_cycle) uses _is_active_stale first."""
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.ACTIVE,
        last_used_at=now - timedelta(days=365),
        updated_at=now - timedelta(days=200),
        created_at=now - timedelta(days=400),
    )
    assert _is_stale_archivable(skill, now, archive_after_days=90) is False


def test_is_stale_archivable_old_stale_is_archivable():
    now = datetime.now(timezone.utc)
    skill = SimpleNamespace(
        status=SkillStatus.STALE,
        last_used_at=now - timedelta(days=150),
        updated_at=now - timedelta(days=120),
        created_at=now - timedelta(days=300),
    )
    assert _is_stale_archivable(skill, now, archive_after_days=90) is True


def test_default_thresholds_documented():
    assert DEFAULT_STALE_AFTER_DAYS == 30
    assert DEFAULT_ARCHIVE_AFTER_DAYS == 90


# ────────────────────────────────────────────────────────────────────────
# _load_eligible_skills — filters
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_eligible_skips_pinned(_seeded_user):
    await _seed_skill(_seeded_user, name="pinned-skill", pinned=True)
    await _seed_skill(_seeded_user, name="not-pinned")
    async with async_session() as db:
        rows = await _load_eligible_skills(db)
    names = [r.name for r in rows if r.user_id == _seeded_user]
    assert "not-pinned" in names
    assert "pinned-skill" not in names


@pytest.mark.asyncio
async def test_load_eligible_skips_candidate_and_rejected(_seeded_user):
    await _seed_skill(_seeded_user, name="active-active", status=SkillStatus.ACTIVE)
    await _seed_skill(_seeded_user, name="stale-stale", status=SkillStatus.STALE)
    await _seed_skill(_seeded_user, name="archived-archived", status=SkillStatus.ARCHIVED)
    await _seed_skill(_seeded_user, name="candidate-candidate", status=SkillStatus.CANDIDATE)
    await _seed_skill(_seeded_user, name="rejected-rejected", status=SkillStatus.REJECTED)
    async with async_session() as db:
        rows = await _load_eligible_skills(db)
    statuses = {r.name: r.status for r in rows if r.user_id == _seeded_user}
    assert statuses == {
        "active-active": SkillStatus.ACTIVE,
        "stale-stale":   SkillStatus.STALE,
    }


@pytest.mark.asyncio
async def test_load_eligible_skips_user_added_and_imported(_seeded_user):
    """The curator only touches auto-generated skills — user-added and
    marketplace-imported are immune."""
    await _seed_skill(_seeded_user, name="auto", source=SkillSource.AUTO_GENERATED)
    await _seed_skill(_seeded_user, name="user", source=SkillSource.USER_ADDED)
    await _seed_skill(_seeded_user, name="market", source=SkillSource.IMPORTED_MARKETPLACE)
    async with async_session() as db:
        rows = await _load_eligible_skills(db)
    names = [r.name for r in rows if r.user_id == _seeded_user]
    assert "auto" in names
    assert "user" not in names
    assert "market" not in names


# ────────────────────────────────────────────────────────────────────────
# run_curator_cycle — end-to-end transitions
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_curator_no_skills_zero_result(_seeded_user):
    summary = await run_curator_cycle()
    # We may have other users' skills in the DB ; just check ours had 0
    # state changes (the assertion below targets us specifically).
    async with async_session() as db:
        ours = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.user_id == _seeded_user)
        )).scalars().all()
    assert ours == []  # didn't accidentally create anything


@pytest.mark.asyncio
async def test_curator_disabled_env_short_circuits(_seeded_user, monkeypatch):
    monkeypatch.setenv("LEARNED_SKILLS_CURATOR_DISABLED", "true")
    # Seed an obviously-stale skill — must NOT transition
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ACTIVE,
        last_used_at=now - timedelta(days=365),
        created_at=now - timedelta(days=400),
    )
    summary = await run_curator_cycle(now=now)
    assert summary["skipped_disabled"] is True
    assert summary["promoted_to_stale"] == 0

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_curator_promotes_inactive_active_to_stale(_seeded_user):
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ACTIVE,
        last_used_at=now - timedelta(days=45),
        created_at=now - timedelta(days=60),
    )
    summary = await run_curator_cycle(now=now)
    assert summary["promoted_to_stale"] >= 1

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.STALE


@pytest.mark.asyncio
async def test_curator_promotes_old_stale_to_archived(_seeded_user):
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.STALE,
        last_used_at=now - timedelta(days=150),
        updated_at=now - timedelta(days=120),
        created_at=now - timedelta(days=300),
    )
    summary = await run_curator_cycle(now=now)
    assert summary["promoted_to_archived"] >= 1

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ARCHIVED


@pytest.mark.asyncio
async def test_curator_pinned_skill_bypasses_transitions(_seeded_user):
    """A pinned skill with old age must NOT be touched by the curator."""
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ACTIVE, pinned=True,
        last_used_at=now - timedelta(days=365),
        created_at=now - timedelta(days=400),
    )
    await run_curator_cycle(now=now)
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_curator_user_added_skill_immune(_seeded_user):
    """User-added (manually written) skills are NEVER curator-touched."""
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ACTIVE,
        source=SkillSource.USER_ADDED,
        last_used_at=now - timedelta(days=365),
        created_at=now - timedelta(days=400),
    )
    await run_curator_cycle(now=now)
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_curator_does_not_revisit_candidates(_seeded_user):
    """Candidates must stay candidate — the HITL admin promotion path
    owns that state, not the curator."""
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.CANDIDATE,
        last_used_at=now - timedelta(days=200),
        created_at=now - timedelta(days=400),
    )
    await run_curator_cycle(now=now)
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.CANDIDATE


@pytest.mark.asyncio
async def test_curator_does_not_re_archive(_seeded_user):
    """Re-running the curator over already-archived skills must not
    crash or mutate them again."""
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ARCHIVED,
        last_used_at=now - timedelta(days=365),
        created_at=now - timedelta(days=400),
    )
    await run_curator_cycle(now=now)
    await run_curator_cycle(now=now)  # idempotent
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ARCHIVED


@pytest.mark.asyncio
async def test_curator_active_to_stale_anchors_on_created_when_never_used(_seeded_user):
    """A skill never `skill_view`ed must use created_at as the age
    anchor — so a 2-day-old never-used skill is not stale at 30d threshold."""
    now = datetime.now(timezone.utc)
    skill_id = await _seed_skill(
        _seeded_user, status=SkillStatus.ACTIVE,
        last_used_at=None,
        created_at=now - timedelta(days=2),
    )
    await run_curator_cycle(now=now, stale_after_days=30)
    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    assert skill.status == SkillStatus.ACTIVE
