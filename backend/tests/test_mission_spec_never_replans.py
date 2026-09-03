# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_spec_never_replans.py
# @brief      Une mission STRUCTUREE ne replanifie jamais — la spec est le
#             contrat. Les garde-fous ajoutés les 28-29/08 incrémentaient
#             `consecutive_failures` sans distinguer le chemin spec, donc
#             pouvaient déclencher un replan qu'elle ne doit pas connaître.
# @license    MIT
# =============================================================================
"""Le contrat « jamais de replan sur une spec » (régression du 29/08/2026).

Trouvé par le scénario de bench « mission structurée de bout en bout » : la
mission est partie en `replan_node`, qui y a planté sur un
``UnboundLocalError``.

Deux défauts distincts, tous deux pinnés ici :

1. **Ma régression.** Le garde-fou d'action répétée et celui d'outil de
   découverte s'exécutent AVANT la branche `_is_spec` d'``eval_node`` et
   font `consecutive_failures + 1`. Trois refus, et `decide_after_eval`
   envoie une mission structurée en replan — que `mission_spec_runtime`
   annonce pourtant comme impossible (« jamais de replan : la spec est le
   contrat »).

2. **Un bug préexistant.** ``replan_node`` assigne `new_plan` DANS un
   ``try`` et le lit en dehors : toute réponse non-JSON du planificateur
   lève ``UnboundLocalError`` au lieu de dégrader. Le heartbeat traduit ça
   en « graph crashed » et tue la mission.
"""
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_noreplan_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Spec", goal="peu importe",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


def _plan_spec() -> dict:
    return {
        "from_spec": True,
        "steps": [
            {"id": "cible", "description": "Fais quelque chose", "handlers": {}},
        ],
    }


@pytest.mark.asyncio
async def test_le_refus_d_outil_de_decouverte_ne_compte_pas_sur_une_spec(
    mission,
) -> None:
    """`find_tool` refusé : l'étape est reprise, la spec ne replanifie pas."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    out = await mn.eval_node({
        "mission_id": mid, "user_id": _uid, "goal": "x",
        "plan_json": _plan_spec(), "current_step_id": "cible",
        "current_item_index": 0,
        "consecutive_failures": 2,
        "last_tool_name": "find_tool",
        "last_tool_input": {"capability": "y"},
        "last_tool_output": "Outils disponibles : …",
    })

    assert out["last_eval_success"] is False
    assert out["consecutive_failures"] == 0, (
        "sur une spec le compteur reste à zéro — c'est lui qui déclenche "
        "le replan que la spec ne doit jamais connaître"
    )


@pytest.mark.asyncio
async def test_le_refus_d_action_repetee_ne_compte_pas_sur_une_spec(
    mission,
) -> None:
    """Même règle pour le garde-fou d'action identique."""
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    _uid, mid = mission
    requete = {"query": "toujours la même"}
    for _ in range(3):
        await mission_service.add_step(
            mid, phase="act", tool_name="web_search", tool_input=requete,
            tool_output="8 résultats", success=True, duration_ms=10,
        )

    out = await mn.eval_node({
        "mission_id": mid, "user_id": _uid, "goal": "x",
        "plan_json": _plan_spec(), "current_step_id": "cible",
        "current_item_index": 0,
        "consecutive_failures": 2,
        "last_tool_name": "web_search",
        "last_tool_input": requete,
        "last_tool_output": "8 résultats",
    })

    assert out["last_eval_success"] is False
    assert out["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_une_mission_libre_continue_de_compter(mission) -> None:
    """Le correctif ne désarme pas le replan des missions LIBRES.

    Elles, elles ont besoin du compteur : c'est leur seul moyen de changer
    de stratégie quand une approche ne passe pas.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    plan_libre = {"steps": [{"id": "1", "description": "Fais"}]}

    out = await mn.eval_node({
        "mission_id": mid, "user_id": _uid, "goal": "x",
        "plan_json": plan_libre, "current_step_id": "1",
        "consecutive_failures": 2,
        "last_tool_name": "find_tool",
        "last_tool_input": {"capability": "y"},
        "last_tool_output": "Outils disponibles : …",
    })

    assert out["consecutive_failures"] == 3, (
        "une mission libre doit toujours pouvoir replanifier"
    )


@pytest.mark.asyncio
async def test_un_replan_non_json_degrade_au_lieu_de_planter(
    mission, monkeypatch,
) -> None:
    """`replan_node` lisait `new_plan` hors du `try` qui l'assigne.

    Toute réponse non-JSON du planificateur levait `UnboundLocalError`, que
    le heartbeat traduit en « graph crashed » — la mission meurt au lieu de
    conserver son plan précédent.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission

    class _LLMBavard:
        async def ainvoke(self, _payload, **_kw):
            return types.SimpleNamespace(
                content="Bien sûr ! Voici mon nouveau plan : d'abord…"
            )

    monkeypatch.setattr(mn, "_get_planner_llm", lambda *a, **k: _LLMBavard())

    out = await mn.replan_node({
        "mission_id": mid, "user_id": _uid, "goal": "x",
        "plan_json": {"steps": [{"id": "1", "description": "Étape connue"}]},
        "plan_text": "# Plan v1", "plan_version": 1,
        "last_tool_name": "web_search", "last_tool_output": "…",
        "last_eval_reason": "échec",
    })

    assert out.get("plan_json"), "le replan doit rendre un plan exploitable"
    assert out["plan_json"]["steps"], (
        "faute de nouveau plan, on conserve les étapes précédentes plutôt "
        "que de tuer la mission"
    )
