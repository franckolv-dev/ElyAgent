# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_me_learning_skills.py
# @brief      Sprint 4b Phase 5.b — user-facing /api/me/learning-skills tests
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for `app/routers/me_learning_skills.py` — Sprint 4b Phase 5.b.

Three layers covered :
  1. `GET /api/me/learning-skills` — lists every skill the caller owns
     across all statuses, never another user's row.
  2. `POST /api/me/learning-skills/{id}/pin` — toggles `pinned`, refuses
     foreign rows with 404 (not 403, to avoid existence leaks).
  3. `POST /api/me/learning-skills/{id}/forget` — flips to ``archived``,
     idempotent on already-archived/rejected, refuses foreign rows.

Tests hit the handler functions directly so they stay hermetic — no
TestClient round-trip, no JWT decoding. The router registration is
asserted separately to catch a forgotten `include_router` in main.py.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def _two_users():
    """Seed user A (alice) and user B (bob) plus a clean slate on their
    learned_skills rows. Both users are torn down on exit so leftover
    skills from previous runs don't cross-pollute this test module.

    Returning a tuple ("alice_id", "bob_id") keeps each test concise.
    """
    await init_db()
    from app.models.user import User

    async with async_session() as db:
        for uid, username, email in (
            ("me_ls_alice", "alice_me_ls", "alice_me_ls@test.local"),
            ("me_ls_bob",   "bob_me_ls",   "bob_me_ls@test.local"),
        ):
            existing = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            if existing is None:
                db.add(User(
                    id=uid, username=username, email=email,
                    hashed_password="x",
                ))
        await db.commit()
        # Clean slate between runs.
        await db.execute(delete(LearnedSkill).where(
            LearnedSkill.user_id.in_(("me_ls_alice", "me_ls_bob"))
        ))
        await db.commit()
    yield "me_ls_alice", "me_ls_bob"
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(
            LearnedSkill.user_id.in_(("me_ls_alice", "me_ls_bob"))
        ))
        await db.commit()


def _fake_user(uid: str):
    """Tiny stand-in matching the handler's `current_user.id` access."""
    class _U:
        id = uid
    return _U()


async def _seed_skill(
    user_id: str,
    *,
    name: str = "test-skill",
    status: str = SkillStatus.ACTIVE,
    pinned: bool = False,
    source: str = SkillSource.AUTO_GENERATED,
    content: str = "# Test\nbody",
    use_count: int = 0,
) -> str:
    """Insert one LearnedSkill and return its UUID id."""
    async with async_session() as db:
        skill = LearnedSkill(
            user_id=user_id,
            name=name,
            description=f"{name} — for tests",
            content=content,
            frontmatter_json="{}",
            status=status,
            source=source,
            pinned=pinned,
            use_count=use_count,
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        return skill.id


async def _get_status(skill_id: str) -> str:
    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        return row.status


async def _get_pinned(skill_id: str) -> bool:
    async with async_session() as db:
        row = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
        return bool(row.pinned)


# ─────────────────────────────────────────────────────────────────────────
# GET /api/me/learning-skills — list
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_only_callers_skills(_two_users) -> None:
    """Bob's skills MUST NOT appear in alice's list, even if alice has
    none. Cross-user leak would be a P0 confidentiality bug."""
    alice, bob = _two_users
    await _seed_skill(bob, name="bobs-secret")
    await _seed_skill(alice, name="alices-thing")

    from app.routers.me_learning_skills import list_my_skills

    async with async_session() as db:
        rows = await list_my_skills(user=_fake_user(alice), db=db)

    names = {r.name for r in rows}
    assert names == {"alices-thing"}, (
        f"alice's list leaked bob's skills: {names}"
    )


@pytest.mark.asyncio
async def test_list_returns_all_statuses(_two_users) -> None:
    """Users should see archived / rejected / candidate skills too —
    the page is meant to show the WHOLE picture (active list AND what
    the curator has tidied away). Filtering happens client-side."""
    alice, _ = _two_users
    statuses = [
        SkillStatus.CANDIDATE,
        SkillStatus.ACTIVE,
        SkillStatus.STALE,
        SkillStatus.ARCHIVED,
        SkillStatus.REJECTED,
    ]
    for s in statuses:
        await _seed_skill(alice, name=f"skill-{s}", status=s)

    from app.routers.me_learning_skills import list_my_skills

    async with async_session() as db:
        rows = await list_my_skills(user=_fake_user(alice), db=db)

    seen = {r.status for r in rows}
    assert seen == set(statuses)


@pytest.mark.asyncio
async def test_list_empty_returns_empty_list(_two_users) -> None:
    """No skills seeded → empty list, not 404. The UI relies on an
    empty array to render its zero-state."""
    alice, _ = _two_users
    from app.routers.me_learning_skills import list_my_skills

    async with async_session() as db:
        rows = await list_my_skills(user=_fake_user(alice), db=db)
    assert rows == []


# ─────────────────────────────────────────────────────────────────────────
# POST /api/me/learning-skills/{id}/pin
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_toggles_flag_on_owned_skill(_two_users) -> None:
    alice, _ = _two_users
    sid = await _seed_skill(alice, pinned=False)

    from app.routers.me_learning_skills import PinRequest, pin_skill

    async with async_session() as db:
        out = await pin_skill(
            skill_id=sid,
            body=PinRequest(pinned=True),
            user=_fake_user(alice),
            db=db,
        )
    assert out.pinned is True
    assert await _get_pinned(sid) is True

    # And unpin should round-trip cleanly.
    async with async_session() as db:
        out = await pin_skill(
            skill_id=sid,
            body=PinRequest(pinned=False),
            user=_fake_user(alice),
            db=db,
        )
    assert out.pinned is False
    assert await _get_pinned(sid) is False


@pytest.mark.asyncio
async def test_pin_foreign_skill_returns_404_not_403(_two_users) -> None:
    """Cross-user safety: alice CANNOT pin bob's skill. The handler
    returns 404 rather than 403 so the existence of bob's row isn't
    leaked through the status code."""
    alice, bob = _two_users
    sid = await _seed_skill(bob)

    from app.routers.me_learning_skills import PinRequest, pin_skill

    with pytest.raises(HTTPException) as ctx:
        async with async_session() as db:
            await pin_skill(
                skill_id=sid,
                body=PinRequest(pinned=True),
                user=_fake_user(alice),
                db=db,
            )
    assert ctx.value.status_code == 404
    assert await _get_pinned(sid) is False  # untouched


@pytest.mark.asyncio
async def test_pin_unknown_id_returns_404(_two_users) -> None:
    alice, _ = _two_users
    from app.routers.me_learning_skills import PinRequest, pin_skill

    with pytest.raises(HTTPException) as ctx:
        async with async_session() as db:
            await pin_skill(
                skill_id="ghost-id-does-not-exist",
                body=PinRequest(pinned=True),
                user=_fake_user(alice),
                db=db,
            )
    assert ctx.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# POST /api/me/learning-skills/{id}/forget
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_archives_active_skill(_two_users) -> None:
    alice, _ = _two_users
    sid = await _seed_skill(alice, status=SkillStatus.ACTIVE)

    from app.routers.me_learning_skills import forget_skill

    async with async_session() as db:
        out = await forget_skill(
            skill_id=sid, user=_fake_user(alice), db=db,
        )
    assert out.status == SkillStatus.ARCHIVED
    assert await _get_status(sid) == SkillStatus.ARCHIVED


@pytest.mark.asyncio
async def test_forget_is_noop_on_already_archived(_two_users) -> None:
    """Idempotence: re-forgetting an archived skill must NOT raise and
    must NOT change anything (no spurious updated_at bump, no side
    effects). The frontend can fire the request without first checking
    state."""
    alice, _ = _two_users
    sid = await _seed_skill(alice, status=SkillStatus.ARCHIVED)

    from app.routers.me_learning_skills import forget_skill

    async with async_session() as db:
        out = await forget_skill(
            skill_id=sid, user=_fake_user(alice), db=db,
        )
    assert out.status == SkillStatus.ARCHIVED
    assert await _get_status(sid) == SkillStatus.ARCHIVED


@pytest.mark.asyncio
async def test_forget_is_noop_on_rejected(_two_users) -> None:
    """Rejected skills are terminal forensic history — forget is a no-op
    rather than transitioning them to archived (which would lose the
    'rejected' signal)."""
    alice, _ = _two_users
    sid = await _seed_skill(alice, status=SkillStatus.REJECTED)

    from app.routers.me_learning_skills import forget_skill

    async with async_session() as db:
        out = await forget_skill(
            skill_id=sid, user=_fake_user(alice), db=db,
        )
    assert out.status == SkillStatus.REJECTED
    assert await _get_status(sid) == SkillStatus.REJECTED


@pytest.mark.asyncio
async def test_forget_foreign_skill_returns_404(_two_users) -> None:
    """Same cross-user safety as pin — 404, not 403."""
    alice, bob = _two_users
    sid = await _seed_skill(bob, status=SkillStatus.ACTIVE)

    from app.routers.me_learning_skills import forget_skill

    with pytest.raises(HTTPException) as ctx:
        async with async_session() as db:
            await forget_skill(
                skill_id=sid, user=_fake_user(alice), db=db,
            )
    assert ctx.value.status_code == 404
    # Bob's skill is untouched.
    assert await _get_status(sid) == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_forget_does_not_delete_failure_cases(_two_users) -> None:
    """Semantic invariant: forget archives the skill, but the underlying
    `failure_cases` rows must remain so the skill_creator can re-process
    the same pattern later if it surfaces again."""
    alice, _ = _two_users
    sid = await _seed_skill(alice, status=SkillStatus.ACTIVE)

    # Seed a failure_case row owned by alice independently of the skill,
    # to verify the forget handler doesn't touch the table at all.
    from app.models.failure_case import FailureCase
    async with async_session() as db:
        fc = FailureCase(
            user_id=alice,
            signal_table="hitl_refusals",
            signal_id=999_111,
            conversation_id="conv-forget-noop",
            replay_payload="{}",
            pattern_hash="forget_noop",
            tier_llm="B",
        )
        db.add(fc)
        await db.commit()
        fc_id = fc.id

    from app.routers.me_learning_skills import forget_skill
    async with async_session() as db:
        await forget_skill(skill_id=sid, user=_fake_user(alice), db=db)

    async with async_session() as db:
        still_there = (await db.execute(
            select(FailureCase).where(FailureCase.id == fc_id)
        )).scalar_one_or_none()
        # Cleanup so we don't pollute other suites.
        if still_there is not None:
            await db.delete(still_there)
            await db.commit()
    assert still_there is not None, "forget must NOT cascade-delete failure_cases"


# ─────────────────────────────────────────────────────────────────────────
# Router registration — pin the path and the main.py wire-up
# ─────────────────────────────────────────────────────────────────────────


def test_router_paths_are_registered() -> None:
    from app.routers.me_learning_skills import router
    paths = {r.path for r in router.routes}
    assert "/api/me/learning-skills" in paths
    assert "/api/me/learning-skills/{skill_id}/pin" in paths
    assert "/api/me/learning-skills/{skill_id}/forget" in paths


def test_router_registered_in_main_app() -> None:
    """Catch the classic 'forgot to include_router' regression in main.py."""
    import inspect

    import app.main as main_module
    src = inspect.getsource(main_module)
    assert "me_learning_skills_router" in src
    assert "me_learning_skills_router.router" in src
