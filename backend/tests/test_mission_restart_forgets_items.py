# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_restart_forgets_items.py
# @brief      Redemarrer une mission doit effacer l'etat des ITEMS, et un
#             foreach dont aucun item n'a abouti doit s'avouer abandonne.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Relancer une mission ne la rejouait pas (30/08/2026).

L'INCIDENT
----------
Mission « Prospection Print LinkedIn », relancée le 30/08 après le déploiement
du lot foreach. Dans les journaux, le tick de l'étape `contacts` :

    plan: existing v1, skipping (iter=4)
    tick done in 0.1s (iter=4, done=None)

Aucune action, aucune évaluation, aucun appel au modèle — et surtout pas une
ligne du journal verbeux ajouté la veille pour EXPLIQUER les foreach sautés.

La cause n'était pas dans le foreach. `POST /missions/{id}/restart` efface
`MissionStep`, `MissionPlan` et le checkpoint LangGraph, mais PAS
`MissionStepRun`. La ligne `contacts / item 0 / skipped` écrite le 29/08 a
survécu ; `expand_foreach` est idempotent et rend les runs existants sans un
mot ; `next_pending_run` n'a rien trouvé ; le step a été marqué `done`.

Une mission relancée héritait donc du verdict de la précédente. Les autres
étapes le montraient aussi : leur compteur `attempts` cumulait les deux
exécutions (3, puis 4) alors que le droit à l'erreur en autorise 2.

LE SECOND DÉFAUT
----------------
Même remis à zéro, ce chemin décidait en silence. `step_progress` compte
`skipped` et `failed` comme terminaux, donc un foreach dont l'unique item
avait été sauté se concluait « foreach terminé (1/1 items) » — un statut
`done` sur le plan, invisible pour `_abandon_notice`, et une mission qui
s'annonce accomplie sans avoir rien produit.
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
        Mission, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_restart_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="A relancer", goal="peu importe",
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
async def test_le_redemarrage_efface_l_etat_des_items(mission, monkeypatch) -> None:
    """Sans ça, une mission relancée hérite des verdicts de la précédente."""
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.mission import Mission, MissionStepRun
    from app.models.user import User
    from app.routers import missions as routeur

    uid, mid = mission
    async with async_session() as db:
        db.add(MissionStepRun(mission_id=mid, step_id="contacts", item_index=0,
                              status="skipped", attempts=2,
                              note="Aucun item identifiable"))
        await db.commit()

    async def _fake_own(mission_id, _user):
        async with async_session() as db:
            return await db.get(Mission, mission_id)

    monkeypatch.setattr(routeur, "_own_or_404", _fake_own)

    await routeur.restart(
        mid, body=None,
        current_user=User(id=uid, username="u", email="u@x", hashed_password="x"),
    )

    async with async_session() as db:
        restants = await db.scalar(
            select(func.count()).select_from(MissionStepRun)
            .where(MissionStepRun.mission_id == mid)
        )
    assert restants == 0, (
        "un item terminal survivant fait sauter son étape en 0,1 s au "
        "prochain démarrage, sans un mot dans les journaux"
    )


@pytest.mark.asyncio
async def test_keep_history_conserve_l_etat_des_items(mission, monkeypatch) -> None:
    """`keep_history=true` demande explicitement de tout garder."""
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.mission import Mission, MissionStepRun
    from app.models.user import User
    from app.routers import missions as routeur

    uid, mid = mission
    async with async_session() as db:
        db.add(MissionStepRun(mission_id=mid, step_id="contacts", item_index=0,
                              status="done"))
        await db.commit()

    async def _fake_own(mission_id, _user):
        async with async_session() as db:
            return await db.get(Mission, mission_id)

    monkeypatch.setattr(routeur, "_own_or_404", _fake_own)

    await routeur.restart(
        mid, body=routeur._RestartBody(keep_history=True),
        current_user=User(id=uid, username="u", email="u@x", hashed_password="x"),
    )

    async with async_session() as db:
        restants = await db.scalar(
            select(func.count()).select_from(MissionStepRun)
            .where(MissionStepRun.mission_id == mid)
        )
    assert restants == 1


def _plan_foreach() -> dict:
    return {
        "from_spec": True,
        "steps": [
            {"id": "contacts", "description": "Cherche les contacts de {{ item }}",
             "foreach": "{{ societes.output }}", "handlers": {}},
        ],
    }


@pytest.mark.asyncio
async def test_un_foreach_dont_aucun_item_n_a_abouti_s_avoue(mission) -> None:
    """« foreach terminé (1/1 items) » comptait un item SAUTÉ comme fait."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await msr.ensure_step_run(mid, "contacts", 0, "Groupe Barillet")
    await msr.set_step_run_status(mid, "contacts", 0, status="skipped",
                                  note="Aucun contact trouvé")

    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "x",
        "plan_json": _plan_foreach(), "plan_text": "# Plan",
    })

    etape = out["plan_json"]["steps"][0]
    assert etape["status"] == "skipped", (
        "aucun item n'a abouti : l'étape est abandonnée, pas terminée — "
        "`done` la rend invisible à l'aveu final"
    )
    assert etape.get("abandon_reason"), "et elle doit dire pourquoi"
    assert "abandonn" in mn._abandon_notice(out["plan_json"]).lower()


@pytest.mark.asyncio
async def test_un_foreach_avec_au_moins_un_item_reussi_est_termine(mission) -> None:
    """Le correctif ne condamne pas les foreach partiellement réussis."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await msr.ensure_step_run(mid, "contacts", 0, "Groupe Barillet")
    await msr.set_step_run_status(mid, "contacts", 0, status="done", output="ok")
    await msr.ensure_step_run(mid, "contacts", 1, "Rullier Bois")
    await msr.set_step_run_status(mid, "contacts", 1, status="skipped",
                                  note="Aucun contact trouvé")

    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "x",
        "plan_json": _plan_foreach(), "plan_text": "# Plan",
    })

    assert out["plan_json"]["steps"][0]["status"] == "done"
