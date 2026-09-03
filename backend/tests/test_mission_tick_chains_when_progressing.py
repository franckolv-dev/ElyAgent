# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_tick_chains_when_progressing.py
# @brief      Une mission qui avance ne fait pas la queue : son tick suivant
#             est immédiat.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le temps mort entre deux actions (31/08/2026).

Mission « Prospection LKDN », trace en base :

    22:58:16  act   drive_list_files
    22:58:25  eval
    22:59:46  act   drive_read_file      ← 81 secondes plus tard

Chaque tick reprogrammait le suivant à `now + 60 s`, puis le battement de
30 s du heartbeat ajoutait sa propre attente. Vingt actions ont pris trente
minutes, dont une vingtaine à ne rien faire. Hermes enchaîne ses actions sans
attendre ; une mission qui vient d'AGIR doit être reprise au battement
suivant.

Les deux autres cas ne changent pas : un tick qui n'a rien fait (des items
attendent une réponse humaine) garde son délai, et un intervalle EXPLICITE
posé par l'utilisateur reste respecté — c'est lui qui sait s'il veut une
veille toutes les heures.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def _mission_demarree(uid: str, **kw) -> str:
    from app.services import mission_service

    m = await mission_service.create_mission(
        user_id=uid, title="Cadence", goal="prospecter", **kw,
    )
    await mission_service.start_mission(m.id)
    return m.id


@pytest_asyncio.fixture
async def user():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import (
        Mission, MissionDailyCounter, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_cadence_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        from sqlalchemy import select
        ids = (await db.execute(
            select(Mission.id).where(Mission.user_id == uid)
        )).scalars().all()
        for modele in (MissionDailyCounter, MissionStepRun, MissionStep,
                       MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id.in_(ids)))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


async def _tick_qui_agit(mission_id, _uid, _goal):
    """Un tick où l'acteur a joué un outil : une ligne `act` de plus."""
    from app.services import mission_service

    await mission_service.add_step(
        mission_id, phase="act", tool_name="web_search",
        tool_input={"query": "négoce"}, tool_output="8 résultats", success=True,
    )
    return {"iteration": 2, "done": False, "plan_version": 1}


async def _tick_sans_action(_mid, _uid, _goal):
    """Un tick no-op : les items attendent une réponse de l'utilisateur."""
    return {
        "iteration": 2, "done": False, "plan_version": 1,
        "last_eval_reason": "1 item(s) en attente de réponse utilisateur",
    }


async def _delai_apres_tick(monkeypatch, mid: str, tick) -> float:
    """Secondes entre l'instant du tick et le `next_tick_at` reprogrammé."""
    from app.database import async_session
    from app.models.mission import Mission
    from app.services import mission_heartbeat as hb

    monkeypatch.setattr(hb, "_tick_one_mission", tick)
    async with async_session() as db:
        m = await db.get(Mission, mid)
    avant = _naive(hb._utcnow())
    await hb._process_one_mission(m)
    async with async_session() as db:
        apres = await db.get(Mission, mid)
    assert apres.status == "running"
    assert apres.next_tick_at is not None
    return (_naive(apres.next_tick_at) - avant).total_seconds()


@pytest.mark.asyncio
async def test_un_tick_qui_a_agi_est_repris_sans_attendre(user, monkeypatch) -> None:
    mid = await _mission_demarree(user)
    delai = await _delai_apres_tick(monkeypatch, mid, _tick_qui_agit)
    assert delai <= 1, (
        f"le tick suivant est reporté de {delai:.0f} s alors que la mission "
        "vient d'agir — c'est là que partait une vingtaine de minutes sur trente"
    )


@pytest.mark.asyncio
async def test_un_tick_sans_action_garde_son_delai(user, monkeypatch) -> None:
    """Rien à enchaîner : on ne martèle pas une mission qui attend un humain."""
    mid = await _mission_demarree(user)
    delai = await _delai_apres_tick(monkeypatch, mid, _tick_sans_action)
    assert delai >= 50


@pytest.mark.asyncio
async def test_un_intervalle_explicite_reste_respecte(user, monkeypatch) -> None:
    """« Toutes les cinq minutes » est un choix de l'utilisateur, pas une cadence."""
    mid = await _mission_demarree(user, tick_interval_seconds=300)
    delai = await _delai_apres_tick(monkeypatch, mid, _tick_qui_agit)
    assert delai >= 290
