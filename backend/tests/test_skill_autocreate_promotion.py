# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_autocreate_promotion.py
# @brief      Jalon 1 (portage Hermes) — autonomous skill creation + promotion
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for the Jalon-1 skill funnel revival.

Covers the three pieces that were missing (and that make Hermes' loop live
where Ely's was dead) :
  1. ``promote_candidate_to_active`` — markdown candidate → active, idempotent,
     and python_tool skills stay gated (frozen funnel B).
  2. ``run_full_loop(auto_promote=True)`` — a passing playbook goes live.
  3. ``run_pending_skill_creation`` — kill switch + autonomous drive.
  4. ``load_seed_playbooks`` — idempotent warm library.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "j1_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"j1_{uid}",
            email=f"{uid}@test.local",
            hashed_password="x",
        ))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.commit()


async def _seed_skill(
    uid: str,
    *,
    status: str = SkillStatus.CANDIDATE,
    content_format: str = SkillContentFormat.MARKDOWN_PLAYBOOK,
    name: str | None = None,
) -> str:
    name = name or ("pb-" + uuid.uuid4().hex[:6])
    async with async_session() as db:
        s = LearnedSkill(
            user_id=uid,
            name=name,
            description="test playbook",
            content="# Body\nstep 1",
            status=status,
            source=SkillSource.AUTO_GENERATED,
            content_format=content_format,
        )
        db.add(s)
        await db.commit()
        return s.id


async def _status_of(skill_id: str) -> str:
    async with async_session() as db:
        return (await db.execute(
            select(LearnedSkill.status).where(LearnedSkill.id == skill_id)
        )).scalar_one()


# ── 1. promotion ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_promote_markdown_candidate_to_active(_user):
    from app.services.learning.skill_promotion import promote_candidate_to_active
    sid = await _seed_skill(_user, status=SkillStatus.CANDIDATE)
    ok = await promote_candidate_to_active(sid, reason="test")
    assert ok is True
    assert await _status_of(sid) == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_promote_idempotent_on_active(_user):
    from app.services.learning.skill_promotion import promote_candidate_to_active
    sid = await _seed_skill(_user, status=SkillStatus.ACTIVE)
    ok = await promote_candidate_to_active(sid)
    assert ok is True
    assert await _status_of(sid) == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_promote_skips_python_tool(_user):
    """Funnel B (python_tool) stays gated behind HITL admin — never auto-active."""
    from app.services.learning.skill_promotion import promote_candidate_to_active
    sid = await _seed_skill(
        _user, status=SkillStatus.CANDIDATE,
        content_format=SkillContentFormat.PYTHON_TOOL,
    )
    ok = await promote_candidate_to_active(sid)
    assert ok is False
    assert await _status_of(sid) == SkillStatus.CANDIDATE


@pytest.mark.asyncio
async def test_promote_missing_skill():
    from app.services.learning.skill_promotion import promote_candidate_to_active
    assert await promote_candidate_to_active("does-not-exist") is False
    assert await promote_candidate_to_active("") is False


# ── 2. run_full_loop auto-promotion ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_full_loop_auto_promotes_pass(_user, monkeypatch):
    """A drafted playbook that passes eval is promoted to active when
    auto_promote=True (the autonomous path)."""
    import app.services.learning.skill_orchestrator as orch

    sid = await _seed_skill(_user, status=SkillStatus.CANDIDATE)

    async def _fake_creator(*, user_id, batch_size):
        return {
            "skills_created": 1,
            "drafts": [{
                "status": "drafted",
                "learned_skill_id": sid,
                "skill_name": "pb",
            }],
        }

    async def _fake_eval(skill_id):
        return {"status": "evaluated", "verdict": "pass", "score": 80}

    monkeypatch.setattr(orch, "run_skill_creator_batch", _fake_creator)
    monkeypatch.setattr(orch, "evaluate_skill", _fake_eval)

    result = await orch.run_full_loop(user_id=_user, auto_promote=True)
    assert result["totals"]["passed"] == 1
    assert result["loops"][0].get("auto_promoted") is True
    assert await _status_of(sid) == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_run_full_loop_no_auto_promote_by_default(_user, monkeypatch):
    """Admin path (default) leaves a passing draft as candidate for review."""
    import app.services.learning.skill_orchestrator as orch

    sid = await _seed_skill(_user, status=SkillStatus.CANDIDATE)

    async def _fake_creator(*, user_id, batch_size):
        return {"skills_created": 1, "drafts": [
            {"status": "drafted", "learned_skill_id": sid, "skill_name": "pb"},
        ]}

    async def _fake_eval(skill_id):
        return {"status": "evaluated", "verdict": "pass", "score": 80}

    monkeypatch.setattr(orch, "run_skill_creator_batch", _fake_creator)
    monkeypatch.setattr(orch, "evaluate_skill", _fake_eval)

    result = await orch.run_full_loop(user_id=_user)  # auto_promote defaults False
    assert result["totals"]["passed"] == 1
    assert "auto_promoted" not in result["loops"][0]
    assert await _status_of(sid) == SkillStatus.CANDIDATE


# ── 3. autonomous tick ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_autocreate_kill_switch(monkeypatch):
    import app.services.learning.skill_autocreate as sac
    monkeypatch.setenv("SKILL_AUTOCREATE_DISABLED", "true")
    out = await sac.run_pending_skill_creation()
    assert out["status"] == "disabled"


@pytest.mark.asyncio
async def test_autocreate_drives_loop_with_auto_promote(monkeypatch):
    """The tick runs run_full_loop with auto_promote=True for users with
    pending failure_cases."""
    import app.services.learning.skill_autocreate as sac
    monkeypatch.delenv("SKILL_AUTOCREATE_DISABLED", raising=False)

    calls = {}

    async def _fake_users(limit):
        return ["u1"]

    async def _fake_loop(*, user_id, batch_size, auto_promote):
        calls["auto_promote"] = auto_promote
        calls["user_id"] = user_id
        return {
            "totals": {"drafts": 1, "passed": 1, "rejected": 0, "errored": 0},
            "loops": [{"final_status": "pass", "auto_promoted": True}],
        }

    monkeypatch.setattr(sac, "_users_with_pending_cases", _fake_users)
    monkeypatch.setattr(sac, "run_full_loop", _fake_loop)

    out = await sac.run_pending_skill_creation()
    assert calls["auto_promote"] is True
    assert out["users"] == 1
    assert out["passed"] == 1
    assert out["promoted"] == 1


# ── 4. seed playbooks ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_playbooks_idempotent(_user):
    from app.services.learning.seed_playbooks import (
        SEED_PLAYBOOKS,
        load_seed_playbooks,
    )
    # First load inserts the bundle for at least our user.
    out1 = await load_seed_playbooks()
    assert out1["inserted"] >= len(SEED_PLAYBOOKS)

    async with async_session() as db:
        rows = (await db.execute(
            select(LearnedSkill).where(
                LearnedSkill.user_id == _user,
                LearnedSkill.source == SkillSource.BUNDLED,
            )
        )).scalars().all()
    assert len(rows) == len(SEED_PLAYBOOKS)
    assert all(r.status == SkillStatus.ACTIVE for r in rows)
    assert all(r.content_format == SkillContentFormat.MARKDOWN_PLAYBOOK for r in rows)

    # Second load is a no-op for our user (idempotent on user_id + name).
    out2 = await load_seed_playbooks()
    async with async_session() as db:
        rows2 = (await db.execute(
            select(LearnedSkill).where(
                LearnedSkill.user_id == _user,
                LearnedSkill.source == SkillSource.BUNDLED,
            )
        )).scalars().all()
    assert len(rows2) == len(SEED_PLAYBOOKS)  # no duplicates
