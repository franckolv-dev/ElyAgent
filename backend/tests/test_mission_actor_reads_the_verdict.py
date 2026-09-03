# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_actor_reads_the_verdict.py
# @brief      Ce que l'evaluateur dit qu'il RESTE A FAIRE doit arriver dans
#             le prompt de l'acteur au tour suivant.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""L'acteur rejouait l'étape sans savoir ce qu'on lui reprochait (30/08/2026).

L'INCIDENT
----------
Mission « Prospection Print LinkedIn », étape `historique`, quatre tours
d'affilée :

    Le fichier n'existe pas (aucun trouvé), il reste à le créer vide comme
    demandé par l'étape.
    Le fichier n'existe pas : la deuxième moitié de l'étape (créer le fichier
    vide historique_Prospection_Print.md) n'a pas été exécutée.
    Le fichier historique_Prospection_Print.md n'existe pas encore : il reste
    à le créer vide comme le demande l'étape.
    Aucun fichier trouvé, mais la seconde moitié de l'étape (le créer vide)
    n'a pas été exécutée. — mais l'étape n'a toujours pas abouti après 4 appels

L'évaluateur avait raison à chaque fois, et de plus en plus précisément.
L'acteur, lui, rejouait `drive_list_files`. Même diagnostic parfait, même
action inchangée, jusqu'à l'abandon.

LA CAUSE
--------
`_ACT_SYSTEM` ne contient ni `last_eval_reason`, ni aucune trace du verdict
précédent. L'acteur voit le plan, l'étape, la date, et les sorties d'outils
des tours RÉUSSIS (`_load_recent_step_outputs` filtre sur `success == True`).
Un refus n'a donc aucun canal vers lui.

Le prompt de l'évaluateur promettait pourtant, depuis le lot « progress » :
« dis dans reason CE QU'IL RESTE À FAIRE, c'est ce que l'agent lira au tour
suivant. » Personne ne lisait rien.

LA RÈGLE
--------
Le verdict n'est ressorti que s'il porte sur L'ÉTAPE COURANTE : le
checkpoint conserve celui du tour précédent, qui peut concerner l'étape
d'avant — la reprocher ici enverrait l'acteur corriger ce qui est déjà fait.
"""
from __future__ import annotations

import types
import uuid

import pytest
import pytest_asyncio

_RESTE = "il reste à créer le fichier vide historique_Prospection_Print.md"


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
    uid = f"test_acteur_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Acteur", goal="tenir un historique",
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


def _plan() -> dict:
    return {
        "steps": [
            {"id": "historique",
             "description": "Cherche historique.md, et sinon crée-le vide."},
        ],
    }


async def _prompt_de_l_acteur(mn, mid: str, uid: str, **etat_precedent) -> str:
    """Fait tourner act_node et rend le prompt système reçu par l'acteur."""
    vu: dict = {}

    class _Acteur:
        async def ainvoke(self, messages, **_kw):
            vu["prompt"] = "\n".join(
                str(getattr(m, "content", m)) for m in (messages or ())
            )
            return types.SimpleNamespace(
                content="",
                tool_calls=[{"name": "drive_list_files", "args": {},
                             "id": "c1"}],
            )

    async def _llms(**_kw):
        return _Acteur(), [], []

    async def _dispatch(*_a, **_kw):
        return "Aucun fichier trouvé.", True

    originaux = (mn._get_actor_llms, mn.dispatch_tool)
    mn._get_actor_llms, mn.dispatch_tool = _llms, _dispatch
    try:
        await mn.act_node({
            "mission_id": mid, "user_id": uid, "goal": "tenir un historique",
            "plan_json": _plan(), "plan_text": "# Plan",
            **etat_precedent,
        })
    finally:
        mn._get_actor_llms, mn.dispatch_tool = originaux
    return vu.get("prompt", "")


@pytest.mark.asyncio
async def test_l_acteur_recoit_ce_qu_il_reste_a_faire(mission) -> None:
    """Sans ça, il rejoue le même outil jusqu'à l'abandon."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    prompt = await _prompt_de_l_acteur(
        mn, mid, uid,
        current_step_id="historique",
        last_eval_success=False,
        last_eval_reason=_RESTE,
    )
    assert _RESTE in prompt


@pytest.mark.asyncio
async def test_le_verdict_d_une_autre_etape_n_est_pas_ressorti(
    mission,
) -> None:
    """Le checkpoint garde le verdict du tour d'avant, pas de l'étape d'avant.

    Le reprocher ici enverrait l'acteur corriger ce qui est déjà fait.
    """
    import app.agent.missions.nodes as mn

    uid, mid = mission
    prompt = await _prompt_de_l_acteur(
        mn, mid, uid,
        current_step_id="une_autre_etape",
        last_eval_success=False,
        last_eval_reason=_RESTE,
    )
    assert _RESTE not in prompt


@pytest.mark.asyncio
async def test_un_verdict_favorable_n_est_pas_un_reproche(mission) -> None:
    import app.agent.missions.nodes as mn

    uid, mid = mission
    prompt = await _prompt_de_l_acteur(
        mn, mid, uid,
        current_step_id="historique",
        last_eval_success=True,
        last_eval_reason="parfait",
    )
    assert "parfait" not in prompt


@pytest.mark.asyncio
async def test_une_etape_neuve_n_a_rien_a_se_reprocher(mission) -> None:
    import app.agent.missions.nodes as mn

    uid, mid = mission
    prompt = await _prompt_de_l_acteur(mn, mid, uid)
    assert "TOUR PRÉCÉDENT" not in prompt


def test_la_borne_d_avancee_couvre_une_sequence_navigateur() -> None:
    """Ouvrir un onglet, charger, lire, écrire : quatre actes au minimum.

    La borne valait 4, si bien qu'une étape LinkedIn était abandonnée à
    l'acte où elle allait aboutir — « La page de recherche est chargée mais
    aucun profil n'a encore été lu » (30/08/2026).
    """
    import app.agent.missions.nodes as mn

    assert mn.MAX_STEP_PROGRESS_TICKS >= 6
