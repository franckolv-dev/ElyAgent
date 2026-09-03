# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_not_found_needs_a_search.py
# @brief      Declarer une absence sans avoir cherche n'est pas un constat.
# @license    MIT
# =============================================================================
"""« Aucun contact trouvé » pour une société jamais regardée (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print », trois sociétés :

    it22  Cas particulier signalé : not_found  → Rullier Bois     (6 actions)
    it24  Cas particulier signalé : not_found  → Négoce Drouillet (0 action)
    it26  Cas particulier signalé : not_found  → Novapierre       (0 action)

Pas un onglet ouvert, pas une recherche, pas une lecture pour les deux
dernières. Le handler `on_not_found: skip_with_note(...)` de la spec a fait
son travail — il a consigné « Aucun contact trouvé pour Négoce Drouillet »
comme un fait établi, dans un fichier que l'utilisateur relira demain pour
ne pas re-prospecter cette société.

LA RÈGLE
--------
`not_found` est un CONSTAT : il suppose qu'on a cherché. Tant qu'aucun outil
n'a tourné sur cet item, le signaler est une supposition, et l'étape est
rendue à l'acteur avec la raison. Même classe de garde-fou que « un outil de
découverte n'accomplit rien » : on refuse sans appeler le modèle.

Les autres cas ne sont PAS concernés. `ask_user` et `error` peuvent
légitimement survenir avant toute action — une consigne ambiguë se signale
avant d'agir, pas après.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import (
        Mission, MissionDailyCounter, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_nf_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Not found", goal="prospecter",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionDailyCounter, MissionStepRun, MissionStep,
                       MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


def _plan() -> dict:
    return {
        "from_spec": True,
        "steps": [{
            "id": "contacts",
            "description": "Pour {{ item }}, relève les contacts LinkedIn",
            "foreach": "{{ societes.output }}",
            "handlers": {"not_found": {"action": "skip_with_note",
                                       "message": "Aucun contact pour {{ item }}"}},
        }],
    }


def _etat(mid: str, uid: str, idx: int, cas: str = "not_found") -> dict:
    return {
        "mission_id": mid, "user_id": uid, "goal": "prospecter",
        "plan_json": _plan(), "current_step_id": "contacts",
        "current_item_index": idx,
        "last_edge_case": {"name": cas, "detail": "rien trouvé"},
    }


async def _item(mid: str, idx: int, valeur: str):
    from app.services import mission_spec_runtime as msr
    await msr.ensure_step_run(mid, "contacts", idx, valeur)


async def _une_recherche(mid: str, idx: int, valeur: str) -> None:
    from app.services import mission_service
    await mission_service.add_step(
        mid, phase="act", tool_name="browser_tab_read_text",
        tool_input={}, tool_output="Aucun résultat",
        thought=f"Étape « [Item {idx + 1} : {valeur}] Ouvre LinkedIn »",
        success=True, duration_ms=1,
    )


@pytest.mark.asyncio
async def test_not_found_sans_aucune_action_est_refuse(mission) -> None:
    """C'est ce qui a consigné deux sociétés jamais regardées."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _item(mid, 1, "Négoce Drouillet")

    out = await mn.eval_node(_etat(mid, uid, 1))

    run = next(r for r in await msr.list_step_runs(mid, "contacts")
               if r.item_index == 1)
    assert run.status != "skipped", (
        "sauter une société sans l'avoir cherchée l'inscrit dans "
        "l'historique comme déjà prospectée"
    )
    assert out.get("last_eval_success") is False
    assert out.get("last_edge_case") is None, "le signal est consommé"


@pytest.mark.asyncio
async def test_not_found_apres_une_recherche_est_honore(mission) -> None:
    """Quand elle a vraiment cherché, le handler de la spec s'applique."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _item(mid, 0, "Rullier Bois")
    await _une_recherche(mid, 0, "Rullier Bois")

    await mn.eval_node(_etat(mid, uid, 0))

    run = next(r for r in await msr.list_step_runs(mid, "contacts")
               if r.item_index == 0)
    assert run.status == "skipped"


@pytest.mark.asyncio
async def test_la_recherche_d_une_autre_societe_ne_compte_pas(
    mission,
) -> None:
    """Le défaut exact : l'item 1 a cherché, l'item 2 en profitait."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _item(mid, 0, "Rullier Bois")
    await _item(mid, 1, "Négoce Drouillet")
    await _une_recherche(mid, 0, "Rullier Bois")

    await mn.eval_node(_etat(mid, uid, 1))

    run = next(r for r in await msr.list_step_runs(mid, "contacts")
               if r.item_index == 1)
    assert run.status != "skipped"


@pytest.mark.asyncio
async def test_les_autres_cas_restent_signalables_sans_action(
    mission,
) -> None:
    """Une consigne ambiguë se signale AVANT d'agir, pas après."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await _item(mid, 0, "Rullier Bois")

    out = await mn.eval_node(_etat(mid, uid, 0, cas="error"))

    assert out.get("last_eval_reason", "").startswith("cas error"), (
        "seul `not_found` exige d'avoir cherché"
    )
    runs = await msr.list_step_runs(mid, "contacts")
    assert runs[0].status in {"skipped", "failed", "waiting_user"}
