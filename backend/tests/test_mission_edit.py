# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_edit.py
# @brief      2026-06-03 — PATCH /api/missions/{id} : edit a mission's params
#             (goal, budgets, schedule) instead of delete + recreate.
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the mission edit endpoint (Franck, 2026-06-03).

Context: iterating on a complex recurring mission forced delete+recreate
every time a param (goal, max iterations) needed a tweak. PATCH lets the
user edit in place and re-run. The endpoint function is imported and
executed (not source-grepped) so the guard + field-update logic is
really exercised.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete

from app.database import async_session, init_db
from app.models.mission import Mission
from app.routers.missions import MissionUpdate, update_mission
from app.services import mission_service


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"me-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"me_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield _FakeUser(uid)
    async with async_session() as db:
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


class _FakeUser:
    def __init__(self, uid: str) -> None:
        self.id = uid


async def _set_status(mission_id: str, status: str) -> None:
    async with async_session() as db:
        m = await db.get(Mission, mission_id)
        m.status = status
        await db.commit()


@pytest.mark.asyncio
async def test_patch_updates_goal_and_iterations(_user):
    m = await mission_service.create_mission(
        user_id=_user.id, title="Factures", goal="ancien objectif à corriger",
        budget_iterations=15,
    )
    out = await update_mission(
        m.id,
        MissionUpdate(goal="nouvel objectif: réutilise le dossier existant", budget_iterations=80),
        current_user=_user,
    )
    assert out.goal.startswith("nouvel objectif")
    assert out.budget_iterations == 80
    # persisted
    async with async_session() as db:
        row = await db.get(Mission, m.id)
        assert row.goal.startswith("nouvel objectif")
        assert row.budget_iterations == 80


@pytest.mark.asyncio
async def test_patch_is_partial_only_changes_provided(_user):
    m = await mission_service.create_mission(
        user_id=_user.id, title="T", goal="objectif initial intact", budget_iterations=10,
    )
    out = await update_mission(m.id, MissionUpdate(budget_iterations=50), current_user=_user)
    assert out.budget_iterations == 50
    assert out.goal == "objectif initial intact"  # untouched


@pytest.mark.asyncio
async def test_patch_blocked_while_running(_user):
    m = await mission_service.create_mission(
        user_id=_user.id, title="T", goal="objectif en cours d'exécution",
    )
    await _set_status(m.id, "running")
    with pytest.raises(HTTPException) as exc:
        await update_mission(m.id, MissionUpdate(goal="ne devrait pas passer"), current_user=_user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_patch_foreign_mission_404(_user):
    m = await mission_service.create_mission(
        user_id=_user.id, title="T", goal="objectif d'un autre user",
    )
    other = _FakeUser("someone-else")
    with pytest.raises(HTTPException) as exc:
        await update_mission(m.id, MissionUpdate(goal="tentative interdite"), current_user=other)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_empty_body_is_noop(_user):
    m = await mission_service.create_mission(
        user_id=_user.id, title="T", goal="objectif inchangé ici", budget_iterations=12,
    )
    out = await update_mission(m.id, MissionUpdate(), current_user=_user)
    assert out.goal == "objectif inchangé ici"
    assert out.budget_iterations == 12


@pytest.mark.asyncio
async def test_patch_allowed_when_completed(_user):
    # editing then re-running a finished mission is the core use case
    m = await mission_service.create_mission(
        user_id=_user.id, title="T", goal="objectif terminé à retoucher",
    )
    await _set_status(m.id, "completed")
    out = await update_mission(m.id, MissionUpdate(budget_iterations=100), current_user=_user)
    assert out.budget_iterations == 100
