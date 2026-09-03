# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_eval_judges_the_step.py
# @brief      L'evaluateur juge l'ACCOMPLISSEMENT de l'etape, pas la
#             compatibilite entre le verbe de l'etape et le type de l'outil.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Une étape peut demander plusieurs actes (30/08/2026).

L'INCIDENT
----------
Mission « Prospection Print LinkedIn », étape 1 :

    Cherche sur mon Google Drive le fichier historique_Prospection_Print.md
    et lis-le [...]. S'il n'existe pas, crée-le vide.

Ely a appelé `drive_list_files`, n'a rien trouvé, et l'évaluateur a validé :

    L'outil de recherche a fonctionné techniquement et a correctement
    rapporté l'absence du fichier.

Le fichier n'a jamais été créé. Quatre étapes plus loin, `memoire` doit
écrire dedans, n'a pas son identifiant, liste le Drive pour le retrouver —
et se fait refuser comme « lecture sur une étape mutative ». L'historique
est resté vide deux jours de suite.

LES DEUX MOITIÉS DU DÉFAUT
--------------------------
1. `success` jugeait la COMPATIBILITÉ entre le verbe de l'étape et le type
   de l'outil, pas l'accomplissement. Le prompt l'écrivait noir sur blanc :
   « Les étapes de lecture et de synthèse sont toujours validées tant que le
   tool a réussi techniquement. » Une étape « cherche, et sinon crée » est
   classée « lecture » sur son premier verbe, donc validée sur son premier
   acte.

2. Le verdict était binaire. Rendre `success` exigeant sans rien d'autre
   aurait transformé chaque étape composée en abandon : depuis le droit à
   l'erreur, une étape dispose de 2 tentatives, et `memoire` en demande
   exactement 2 (trouver l'identifiant, puis écrire). Zéro marge. Il manque
   l'état intermédiaire : l'appel a fait AVANCER l'étape sans l'achever.
   Avancer n'est pas échouer — ça ne doit pas consommer le droit à l'erreur.

Le piétinement reste borné : `MAX_STEP_PROGRESS_TICKS` appels sans achever,
et l'étape retombe dans le traitement d'échec ordinaire.
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
    from app.models.mission import (
        Mission, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_eval_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Eval", goal="peu importe",
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


def _verdict_llm(**champs):
    """Un évaluateur qui rend le verdict demandé."""

    class _LLM:
        async def ainvoke(self, _messages, **_kw):
            return types.SimpleNamespace(content=json.dumps(champs))

    return _LLM()


def _plan(spec: bool, *, attempts: int = 0) -> dict:
    etape = {
        "id": "historique",
        "description": (
            "Cherche sur mon Drive le fichier historique.md et lis-le. "
            "S'il n'existe pas, crée-le vide."
        ),
        "attempts": attempts,
    }
    if spec:
        etape["handlers"] = {}
    return {"from_spec": spec, "steps": [etape]}


def _etat(mid: str, uid: str, plan: dict) -> dict:
    return {
        "mission_id": mid, "user_id": uid, "goal": "tenir un historique",
        "plan_json": plan, "current_step_id": "historique",
        "current_item_index": 0,
        "last_tool_name": "drive_list_files",
        "last_tool_input": {"query": "historique.md"},
        "last_tool_output": "Aucun fichier trouvé.",
    }


# ── 1. Le contrat écrit dans le prompt ──────────────────────────────────


def test_le_prompt_ne_valide_plus_une_lecture_par_principe() -> None:
    """C'est cette phrase qui a validé l'étape 1 sans créer le fichier."""
    import app.agent.missions.nodes as mn

    assert "toujours validées tant que le tool a réussi techniquement" \
        not in mn._EVAL_SYSTEM


def test_le_prompt_demande_l_accomplissement_et_offre_progress() -> None:
    """`success` porte sur le résultat de l'étape ; `progress` sur l'avancée."""
    import app.agent.missions.nodes as mn

    assert '"progress"' in mn._EVAL_SYSTEM
    # Le cas réel doit figurer parmi les exemples : une étape conditionnelle
    # dont la branche mutative n'a pas été exécutée.
    assert "sinon" in mn._EVAL_SYSTEM.lower()


# ── 2. Avancer ne consomme pas le droit à l'erreur ──────────────────────


@pytest.mark.asyncio
async def test_une_etape_qui_avance_garde_son_droit_a_l_erreur(
    mission, monkeypatch,
) -> None:
    """`memoire` demande 2 actes et ne dispose que de 2 tentatives."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(
            success=False, progress=True,
            reason="le fichier est absent, il reste à le créer",
        ),
    )

    out = await mn.eval_node(_etat(mid, uid, _plan(spec=False)))

    etape = out["plan_json"]["steps"][0]
    assert etape.get("attempts", 0) == 0, (
        "avancer n'est pas échouer — sinon une étape composée est abandonnée "
        "avant d'avoir pu finir"
    )
    assert etape.get("status") != "skipped"
    assert out["last_eval_success"] is False, (
        "l'étape n'est pas accomplie pour autant : elle doit être rejouée"
    )
    assert out["consecutive_failures"] == 0, "avancer ne déclenche pas de replan"


@pytest.mark.asyncio
async def test_l_item_d_une_spec_qui_avance_repasse_pending(
    mission, monkeypatch,
) -> None:
    """La tentative comptée à l'entrée du tick est rendue."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    await msr.ensure_step_run(mid, "historique", 0, None)
    await msr.set_step_run_status(mid, "historique", 0, status="running",
                                  bump_attempts=True)
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(
            success=False, progress=True, reason="reste à créer le fichier",
        ),
    )

    await mn.eval_node(_etat(mid, uid, _plan(spec=True)))

    run = (await msr.list_step_runs(mid, "historique"))[0]
    assert run.status == "pending", "sans ça l'item n'est jamais repris"
    assert run.attempts == 0, (
        "act_node compte la tentative à l'entrée du tick ; un tick qui a fait "
        "avancer l'étape doit la rendre, sinon AUTO_SKIP_ATTEMPTS la saute"
    )


# ── 3. Mais le piétinement reste borné ──────────────────────────────────


@pytest.mark.asyncio
async def test_une_etape_qui_pietine_finit_par_echouer(
    mission, monkeypatch,
) -> None:
    """Sans borne, « ça avance » serait une boucle infinie polie."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(
            success=False, progress=True, reason="ça avance, dit-il",
        ),
    )

    plan = _plan(spec=False)
    for _ in range(mn.MAX_STEP_PROGRESS_TICKS + 1):
        out = await mn.eval_node(_etat(mid, uid, plan))
        plan = out["plan_json"]

    assert plan["steps"][0].get("attempts", 0) >= 1, (
        "au-delà de la borne, « ça avance » redevient un échec ordinaire"
    )


# ── 4. Garde-fous ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_echec_franc_consomme_toujours_le_droit_a_l_erreur(
    mission, monkeypatch,
) -> None:
    import app.agent.missions.nodes as mn

    uid, mid = mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(
            success=False, progress=False, reason="l'outil a renvoyé une erreur",
        ),
    )

    out = await mn.eval_node(_etat(mid, uid, _plan(spec=False)))
    assert out["plan_json"]["steps"][0]["attempts"] == 1


@pytest.mark.asyncio
async def test_un_verdict_sans_progress_se_comporte_comme_avant(
    mission, monkeypatch,
) -> None:
    """Un modèle qui ignore le champ ne doit rien casser."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(success=False, reason="raté"),
    )

    out = await mn.eval_node(_etat(mid, uid, _plan(spec=False)))
    assert out["plan_json"]["steps"][0]["attempts"] == 1


@pytest.mark.asyncio
async def test_une_etape_accomplie_reste_accomplie(
    mission, monkeypatch,
) -> None:
    import app.agent.missions.nodes as mn

    uid, mid = mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(
            success=True, progress=False, reason="fichier créé", all_done=False,
        ),
    )

    out = await mn.eval_node(_etat(mid, uid, _plan(spec=False)))
    assert out["plan_json"]["steps"][0]["status"] == "done"
