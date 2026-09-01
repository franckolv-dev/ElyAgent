# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_iterations_count_actions.py
# @brief      Le budget d'itérations compte les tours de l'acteur, pas les
#             lignes du journal.
# @license    Elastic License 2.0
# =============================================================================
"""Une itération est un tour de l'acteur (31/08/2026).

`add_step` incrémentait `iterations_used` à CHAQUE ligne écrite : le plan,
l'action, l'évaluation. Un appel d'outil coûtait donc deux itérations
(act + eval), et une mission créée avec le budget par défaut (30) n'avait
droit qu'à une quinzaine d'actions. La mission « Prospection LKDN » a
consommé 41 itérations pour 18 appels d'outils.

Le budget que l'utilisateur règle dans l'interface s'appelle « itérations » :
il doit compter ce qu'il croit compter — les tours où l'acteur agit.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionPlan, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service

    await init_db()
    uid = f"test_iter_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Compteur", goal="compter juste",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep, MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_une_action_vaut_une_iteration_pas_deux(mission) -> None:
    """Plan + action + évaluation = UNE itération : celle où l'acteur a agi."""
    from app.services import mission_service

    _uid, mid = mission
    await mission_service.add_step(
        mid, phase="plan", evaluation="plan v1", success=True,
    )
    await mission_service.add_step(
        mid, phase="act", tool_name="web_search", tool_input={"query": "x"},
        tool_output="10 résultats", success=True,
    )
    await mission_service.add_step(
        mid, phase="eval", evaluation="fait", success=True,
    )
    m = await mission_service.get_mission(mid)
    assert m.iterations_used == 1


@pytest.mark.asyncio
async def test_un_tour_de_l_acteur_sans_outil_compte_aussi(mission) -> None:
    """Un cas particulier signalé (EDGE_CASE) est un tour de l'acteur : il compte."""
    from app.services import mission_service

    _uid, mid = mission
    await mission_service.add_step(
        mid, phase="act", thought="EDGE_CASE not_found",
        evaluation="Cas particulier signalé : not_found", success=True,
    )
    await mission_service.add_step(
        mid, phase="eval", evaluation="Handler spec : not_found → skip",
        success=True,
    )
    m = await mission_service.get_mission(mid)
    assert m.iterations_used == 1
