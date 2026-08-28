# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_repeated_action.py
# @brief      Rejouer une action DÉJÀ jouée à l'identique ne fait pas avancer
#             une mission. L'évaluateur juge si l'outil a fonctionné, pas si
#             la mission progresse — il validait donc la même requête trois
#             fois de suite.
# @license    Elastic License 2.0
# =============================================================================
"""Garde-fou d'action répétée (incident du 28/08/2026).

Mission « Prospection Print LinkedIn », 2 sociétés demandées, 1 livrée :

    it6   web_search  "LinkedIn CEO … PUBLIGIFTS"  -> eval ok
    it8   web_search  "LinkedIn CEO … PUBLIGIFTS"  -> eval ok   (identique)
    it10  web_search  "LinkedIn CEO … PUBLIGIFTS"  -> eval ok   (identique)

Les étapes 4 et 5 du plan visaient la DEUXIÈME société. Elles ont été
consommées à refaire la recherche de la première, et l'évaluateur a dit oui
trois fois : « l'outil a renvoyé des résultats pertinents » — vrai à chaque
fois, et sans intérêt dès la deuxième.

Le verdict de répétition est rendu SANS appel au modèle : une action dont on
sait déjà qu'elle n'apprend rien ne mérite pas qu'on paie son évaluation.
"""
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def free_mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_repeat_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="trouver 2 sociétés",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStep).where(MissionStep.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


_REQUETE = {"query": 'LinkedIn CEO Directeur Marketing "PUBLIGIFTS"'}


def _llm_toujours_ok():
    """L'évaluateur d'origine : il valide, parce que l'outil a répondu."""
    class _FakeLLM:
        appels = 0

        async def ainvoke(self, _payload, **_kw):
            _FakeLLM.appels += 1
            return types.SimpleNamespace(content=json.dumps({
                "success": True,
                "reason": "l'outil a renvoyé des résultats pertinents",
                "all_done": False,
            }))
    _FakeLLM.appels = 0
    return _FakeLLM()


def _plan() -> dict:
    return {
        "steps": [
            {"id": "3", "description": "Contacts de la 1re société"},
            {"id": "4", "description": "Contacts de la 2e société"},
            {"id": "5", "description": "Profils LinkedIn de la 2e société"},
        ],
    }


async def _jouer(mn, uid: str, mid: str, plan_json: dict, step_id: str) -> dict:
    """Un tour complet act→eval sur la MÊME recherche."""
    from app.services import mission_service

    # act_node journalise l'action ; on reproduit sa trace en base.
    await mission_service.add_step(
        mid, phase="act", tool_name="web_search",
        tool_input=_REQUETE,
        tool_output="8 résultats", success=True, duration_ms=10,
    )
    return await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "trouver 2 sociétés",
        "plan_json": plan_json, "current_step_id": step_id,
        "last_tool_name": "web_search",
        "last_tool_input": _REQUETE,
        "last_tool_output": "8 résultats",
    })


@pytest.mark.asyncio
async def test_la_troisieme_action_identique_est_refusee(
    free_mission, monkeypatch,
) -> None:
    """Deux fois passe (droit à l'erreur), la troisième non."""
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: _llm_toujours_ok())

    plan = _plan()
    premier = await _jouer(mn, uid, mid, plan, "3")
    assert premier["last_eval_success"] is True, "la 1re recherche est légitime"

    deuxieme = await _jouer(mn, uid, mid, premier["plan_json"], "4")
    assert deuxieme["last_eval_success"] is True, "la 2e reste tolérée"

    troisieme = await _jouer(mn, uid, mid, deuxieme["plan_json"], "5")
    assert troisieme["last_eval_success"] is False, (
        "la 3e action identique n'apprend rien — elle doit être refusée"
    )
    assert "identique" in (troisieme["last_eval_reason"] or "").lower()


@pytest.mark.asyncio
async def test_le_refus_ne_coute_aucun_appel_au_modele(
    free_mission, monkeypatch,
) -> None:
    """Une action qu'on sait stérile ne mérite pas qu'on paie son évaluation."""
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    faux = _llm_toujours_ok()
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: faux)

    plan = _plan()
    out = await _jouer(mn, uid, mid, plan, "3")
    out = await _jouer(mn, uid, mid, out["plan_json"], "4")
    appels_avant = type(faux).appels

    await _jouer(mn, uid, mid, out["plan_json"], "5")

    assert type(faux).appels == appels_avant, (
        "le verdict de répétition se rend sans appeler le modèle"
    )


@pytest.mark.asyncio
async def test_une_requete_differente_reste_libre(
    free_mission, monkeypatch,
) -> None:
    """Le garde-fou vise l'IDENTIQUE, pas la ressemblance."""
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    uid, mid = free_mission
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: _llm_toujours_ok())

    plan = _plan()
    out = await _jouer(mn, uid, mid, plan, "3")
    out = await _jouer(mn, uid, mid, out["plan_json"], "4")

    # Même outil, AUTRE société : c'est exactement ce qu'on veut encourager.
    autre = {"query": 'LinkedIn CEO Directeur Marketing "RULLIER BOIS"'}
    await mission_service.add_step(
        mid, phase="act", tool_name="web_search",
        tool_input=autre,
        tool_output="8 résultats", success=True, duration_ms=10,
    )
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "trouver 2 sociétés",
        "plan_json": out["plan_json"], "current_step_id": "5",
        "last_tool_name": "web_search", "last_tool_input": autre,
        "last_tool_output": "8 résultats",
    })

    assert out["last_eval_success"] is True, (
        "changer de cible est la bonne conduite — elle ne doit pas être punie"
    )


@pytest.mark.asyncio
async def test_l_ordre_des_arguments_ne_masque_pas_une_repetition(
    free_mission, monkeypatch,
) -> None:
    """Deux appels identiques au désordre des clés près restent identiques."""
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    uid, mid = free_mission
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: _llm_toujours_ok())

    plan = _plan()
    for cle_ordre in ({"query": "X", "count": 8}, {"count": 8, "query": "X"}):
        await mission_service.add_step(
            mid, phase="act", tool_name="web_search",
            tool_input=cle_ordre,
            tool_output="ok", success=True, duration_ms=10,
        )
    await mission_service.add_step(
        mid, phase="act", tool_name="web_search",
        tool_input={"query": "X", "count": 8},
        tool_output="ok", success=True, duration_ms=10,
    )

    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "trouver 2 sociétés",
        "plan_json": plan, "current_step_id": "5",
        "last_tool_name": "web_search",
        "last_tool_input": {"count": 8, "query": "X"},
        "last_tool_output": "ok",
    })

    assert out["last_eval_success"] is False, (
        "l'empreinte doit être stable au réordonnancement des clés"
    )
