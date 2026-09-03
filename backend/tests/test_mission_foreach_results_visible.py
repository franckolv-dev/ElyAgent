# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_foreach_results_visible.py
# @brief      Une etape qui raisonne sur le resultat d'un foreach doit voir
#             QUEL item a abouti et lequel non.
# @license    MIT
# =============================================================================
"""L'historique a retenu la société qui a échoué (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print ». Trois sociétés itérées :

    Océalia            done     « Les 5 profils ont été ajoutés au Sheet »
    Négoce Drouillet   skipped  « pas encore ajoutés au Google Sheet »
    Groupe Dubreuil    skipped  « il faut maintenant attendre le chargement »

L'étape suivante demande :

    Ajoute au fichier historique_Prospection_Print.md les sociétés pour
    lesquelles AU MOINS UN CONTACT a été enregistré aujourd'hui.

Le fichier livré contient **Négoce Drouillet** — la société dont pas une
ligne n'a été écrite. Océalia, la seule à avoir abouti, n'y figure pas.

LA CAUSE
--------
`mission_step_runs` sait tout : un item par société, son `item_value`, son
statut, sa note, sa sortie. Rien ne remonte à l'acteur. Il ne voit que
`_load_recent_step_outputs`, c'est-à-dire les dernières sorties d'outils
RÉUSSIES — donc, en fin de foreach, les lectures LinkedIn des sociétés qui
ont échoué, puisque ce sont les plus récentes. Il a recopié le nom qui
traînait dans son contexte.

Ce n'était pas une hallucination : c'était la seule information qu'on lui
avait donnée.

LA RÈGLE
--------
Les étapes itérées déjà traitées exposent leur bilan par item — nom, statut,
et ce qui s'est passé. Une étape qui raisonne sur « celles qui ont abouti »
peut alors le faire.
"""
from __future__ import annotations

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
    uid = f"test_bilan_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Bilan", goal="prospecter",
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


async def _trois_societes(mid: str) -> None:
    from app.services import mission_spec_runtime as msr

    await msr.ensure_step_run(mid, "contacts", 0, "Océalia")
    await msr.set_step_run_status(
        mid, "contacts", 0, status="done",
        note="Les 5 profils ont été ajoutés au Sheet",
        output="5 ligne(s) ajoutée(s)",
    )
    await msr.ensure_step_run(mid, "contacts", 1, "Négoce Drouillet")
    await msr.set_step_run_status(
        mid, "contacts", 1, status="skipped",
        note="profils identifiés mais pas ajoutés au Google Sheet",
    )
    await msr.ensure_step_run(mid, "contacts", 2, "Groupe Dubreuil")
    await msr.set_step_run_status(
        mid, "contacts", 2, status="skipped", note="onglet à peine ouvert",
    )


def _plan() -> dict:
    return {
        "from_spec": True,
        "steps": [
            {"id": "contacts", "description": "Pour {{ item }}, relève",
             "foreach": "{{ societes.output }}", "status": "done"},
            {"id": "memoire",
             "description": "Ajoute à l'historique les sociétés pour "
                            "lesquelles au moins un contact a été enregistré"},
        ],
    }


@pytest.mark.asyncio
async def test_le_bilan_par_item_nomme_qui_a_abouti(mission) -> None:
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trois_societes(mid)

    bilan = await mn._foreach_outcomes(mid, _plan(), "memoire")

    assert "Océalia" in bilan
    assert "Négoce Drouillet" in bilan, (
        "les échecs aussi doivent figurer : c'est ce qui permet de NE PAS "
        "les retenir"
    )
    # Et le statut doit être lisible, pas seulement le nom.
    ligne_ocealia = next(l for l in bilan.splitlines() if "Océalia" in l)
    ligne_drouillet = next(
        l for l in bilan.splitlines() if "Négoce Drouillet" in l
    )
    assert "A ABOUTI" in ligne_ocealia
    assert "A ABOUTI" not in ligne_drouillet
    assert "pas abouti" in ligne_drouillet


@pytest.mark.asyncio
async def test_l_etape_iteree_elle_meme_ne_recoit_pas_son_propre_bilan(
    mission,
) -> None:
    """Pendant qu'elle tourne, l'étape n'a pas à relire ses items faits.

    Ce serait du bruit à chaque tour, et ça invite à recopier une société
    déjà traitée.
    """
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trois_societes(mid)

    assert await mn._foreach_outcomes(mid, _plan(), "contacts") == ""


@pytest.mark.asyncio
async def test_un_plan_sans_foreach_ne_produit_rien(mission) -> None:
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    plan = {"from_spec": True, "steps": [{"id": "a", "description": "x"}]}
    assert await mn._foreach_outcomes(mid, plan, "a") == ""


@pytest.mark.asyncio
async def test_le_bilan_arrive_dans_le_prompt_de_l_acteur(mission) -> None:
    """Un bilan que personne ne lit ne vaut pas mieux que pas de bilan.

    C'est l'erreur commise la veille avec `last_eval_reason` : le message
    était écrit, aucun lecteur ne le recevait.
    """
    import types

    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trois_societes(mid)
    vu: dict = {}

    class _Acteur:
        async def ainvoke(self, messages, **_kw):
            vu["prompt"] = "\n".join(
                str(getattr(m, "content", m)) for m in (messages or ())
            )
            return types.SimpleNamespace(
                content="",
                tool_calls=[{"name": "drive_update_file", "args": {}, "id": "c"}],
            )

    async def _llms(**_kw):
        return _Acteur(), [], []

    async def _dispatch(*_a, **_kw):
        return "ok", True

    originaux = (mn._get_actor_llms, mn.dispatch_tool)
    mn._get_actor_llms, mn.dispatch_tool = _llms, _dispatch
    try:
        await mn.act_node({
            "mission_id": mid, "user_id": _uid, "goal": "prospecter",
            "plan_json": _plan(), "plan_text": "# Plan",
        })
    finally:
        mn._get_actor_llms, mn.dispatch_tool = originaux

    assert "Océalia" in vu.get("prompt", "")
