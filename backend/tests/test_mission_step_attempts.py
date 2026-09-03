# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_step_attempts.py
# @brief      Missions libres : une étape a droit à l'erreur UNE fois, puis
#             elle est abandonnée. Sans cette borne, `_next_pending_step`
#             rend éternellement le même step « failed » et la mission brûle
#             son budget dessus (incident 26/08/2026, mission Prospection :
#             drive_upload_local_file rejoué 3×, sheets_create_spreadsheet
#             2×, 103 041 tokens consommés sans jamais avancer).
# @license    MIT
# =============================================================================
"""Borne de tentatives par étape sur les missions LIBRES (hors spec)."""
from __future__ import annotations

import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def free_mission():
    """Mission SANS spec_yaml — le chemin legacy plan/act/eval du LLM."""
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_attempts_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="déposer le fichier sur Drive",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStep).where(MissionStep.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


def _verdict_llm(success: bool, reason: str):
    """Faux évaluateur : rend le JSON que `eval_node` sait parser."""
    class _FakeLLM:
        async def ainvoke(self, _payload, **_kw):
            return types.SimpleNamespace(content=(
                '{"success": %s, "reason": "%s", "all_done": false}'
                % ("true" if success else "false", reason)
            ))
    return _FakeLLM()


def _verdict_llm_all_done(reason: str):
    """Faux évaluateur qui conclut que la mission entière est terminée."""
    class _FakeLLM:
        async def ainvoke(self, _payload, **_kw):
            return types.SimpleNamespace(content=(
                '{"success": true, "reason": "%s", "all_done": true}' % reason
            ))
    return _FakeLLM()


def _plan_two_steps() -> dict:
    return {
        "steps": [
            {"id": "1", "description": "Dépose le fichier sur Drive",
             "tool_hint": "drive_upload_local_file"},
            {"id": "2", "description": "Préviens l'utilisateur",
             "tool_hint": "telegram_send_message"},
        ],
    }


async def _fail_once(mn, uid: str, mid: str, plan_json: dict) -> dict:
    """Joue un tick d'évaluation en échec sur le step « 1 »."""
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "déposer le fichier",
        "plan_json": plan_json, "current_step_id": "1",
        "last_tool_name": "drive_upload_local_file",
        "last_tool_output": "{'ok': true}",
    })
    return out["plan_json"]


@pytest.mark.asyncio
async def test_first_failure_keeps_the_step_retryable(
    free_mission, monkeypatch,
) -> None:
    """Droit à l'erreur : au 1er échec l'étape reste à rejouer.

    Un refus peut venir d'un service lent à démarrer — on retente une fois.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(False, "fichier absent du Drive"),
    )

    plan_json = await _fail_once(mn, uid, mid, _plan_two_steps())

    step = plan_json["steps"][0]
    assert step["attempts"] == 1
    assert step["status"] == "failed", "1er échec : l'étape reste à rejouer"
    assert mn._next_pending_step(plan_json)["id"] == "1", (
        "le prochain tick doit RE-tenter la même étape"
    )


@pytest.mark.asyncio
async def test_second_failure_abandons_the_step_and_moves_on(
    free_mission, monkeypatch,
) -> None:
    """Au 2e échec l'étape est abandonnée — la mission passe à la suivante.

    C'est la borne qui manquait : sans elle `_next_pending_step` rend
    éternellement la même étape « failed » jusqu'à épuisement du budget.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(False, "fichier absent du Drive"),
    )

    plan_json = await _fail_once(mn, uid, mid, _plan_two_steps())
    plan_json = await _fail_once(mn, uid, mid, plan_json)

    step = plan_json["steps"][0]
    assert step["attempts"] == 2
    assert step["status"] == "skipped", "2e échec : l'étape est abandonnée"
    assert "fichier absent du Drive" in (step.get("abandon_reason") or ""), (
        "la raison de l'abandon doit rester lisible dans le plan"
    )
    assert mn._next_pending_step(plan_json)["id"] == "2", (
        "la mission doit AVANCER, pas rejouer l'étape abandonnée"
    )


@pytest.mark.asyncio
async def test_success_after_a_failure_clears_the_counter(
    free_mission, monkeypatch,
) -> None:
    """Le rejeu qui réussit ferme l'étape — le compteur ne la condamne pas."""
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(False, "service lent à démarrer"),
    )
    plan_json = await _fail_once(mn, uid, mid, _plan_two_steps())

    monkeypatch.setattr(
        mn, "_get_evaluator_llm", lambda **_kw: _verdict_llm(True, "déposé"),
    )
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "déposer le fichier",
        "plan_json": plan_json, "current_step_id": "1",
        "last_tool_name": "drive_upload_local_file",
        "last_tool_output": "{'ok': true}",
    })

    step = out["plan_json"]["steps"][0]
    assert step["status"] == "done"
    assert mn._next_pending_step(out["plan_json"])["id"] == "2"


def test_free_and_spec_missions_share_the_same_right_to_err() -> None:
    """Les deux chemins doivent accorder le MÊME nombre de tentatives.

    Le chemin spec borne déjà via ``AUTO_SKIP_ATTEMPTS``. Deux constantes
    qui disent la même règle dérivent — ce pin les tient ensemble.
    """
    import app.agent.missions.nodes as mn
    from app.services.mission_spec_runtime import AUTO_SKIP_ATTEMPTS

    assert mn.MAX_STEP_ATTEMPTS == AUTO_SKIP_ATTEMPTS


@pytest.mark.asyncio
async def test_final_summary_names_the_abandoned_steps(free_mission) -> None:
    """Une mission qui a abandonné une étape ne se dit pas accomplie sans le dire.

    `_next_pending_step` saute `skipped` — sans ce garde-fou, une mission dont
    l'étape clé a été abandonnée se termine sur « Toutes les étapes du plan
    sont terminées », un succès de façade.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    plan_json = {
        "steps": [
            {"id": "1", "description": "Dépose le fichier sur Drive",
             "status": "skipped", "attempts": 2,
             "abandon_reason": "fichier absent du Drive"},
            {"id": "2", "description": "Préviens l'utilisateur", "status": "done"},
        ],
    }

    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "déposer le fichier",
        "plan_json": plan_json, "plan_text": "",
    })

    assert out["done"] is True
    summary = out["final_summary"]
    assert "abandonn" in summary.lower(), (
        "le résumé doit signaler l'abandon, pas annoncer un succès plein"
    )
    assert "Dépose le fichier sur Drive" in summary, (
        "le résumé doit nommer l'étape abandonnée"
    )
    assert "fichier absent du Drive" in summary, (
        "le résumé doit donner la raison de l'abandon"
    )


@pytest.mark.asyncio
async def test_all_done_ne_tait_pas_les_etapes_abandonnees(
    free_mission, monkeypatch,
) -> None:
    """Le verdict `all_done` de l'évaluateur ne blanchit pas un abandon.

    Vécu le 27/08 21h06 (mission « Prospection Print LinkedIn ») : l'étape
    de création du tableur avait été abandonnée après 2 échecs, l'export
    d'après a réussi — sur un tableur VIDE — et l'évaluateur a conclu
    `all_done`. Résumé livré : « Mission accomplie. » Le garde-fou posé
    dans `act_node` ne couvrait pas ce chemin-là.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm_all_done("export XLSX créé avec succès"),
    )

    plan_json = {
        "steps": [
            {"id": "1", "description": "Écris les contacts dans le tableur",
             "status": "skipped", "attempts": 2,
             "abandon_reason": "HTTP 400 : plage Sheet1!A1 invalide"},
            {"id": "2", "description": "Exporte le tableur sur le Drive"},
        ],
    }
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "déposer le fichier",
        "plan_json": plan_json, "current_step_id": "2",
        "last_tool_name": "drive_export_file",
        "last_tool_output": "✓ Export xlsx créé",
    })

    assert out["done"] is True
    summary = out["final_summary"]
    assert "abandonn" in summary.lower(), (
        "une mission qui a abandonné une étape ne s'annonce pas simplement "
        "« accomplie » — c'est ainsi qu'un fichier vide passe pour un livrable"
    )
    assert "Écris les contacts dans le tableur" in summary
    assert "plage Sheet1!A1 invalide" in summary, (
        "la raison de l'abandon doit rester lisible"
    )
    assert "Écris les contacts dans le tableur" in summary
    assert "plage Sheet1!A1 invalide" in summary


@pytest.mark.asyncio
async def test_le_resume_d_une_mission_structuree_avoue_aussi(
    free_mission, monkeypatch,
) -> None:
    """Le TROISIÈME chemin de terminaison doit dire la même vérité.

    Une mission a trois façons de finir : plus d'étape en attente
    (`act_node`), le verdict `all_done` de l'évaluateur, et la terminaison
    déterministe d'une spec. Vécu le 28/08 : la mission structurée
    « Prospection Calameo-LinkedIn » a rendu « tous les steps de la spec sont
    done/skipped » — exact, et parfaitement muet sur le fait que RIEN n'avait
    été produit.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm", lambda **_kw: _verdict_llm(True, "export fait"),
    )

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "tableur", "description": "Crée le Google Sheet",
             "status": "skipped", "abandon_reason": "HTTP 400 sur la plage"},
            {"id": "memoire", "description": "Mets à jour l'historique",
             "handlers": {}},
        ],
    }
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "prospecter",
        "plan_json": plan_json, "current_step_id": "memoire",
        "current_item_index": 0,
        "last_tool_name": "drive_update_file",
        "last_tool_output": "ok",
    })

    assert out.get("done") is True
    resume = out["final_summary"]
    assert "abandonn" in resume.lower(), (
        "« done/skipped » est exact et muet — le résumé doit nommer ce qui a "
        "été sauté, sinon un livrable absent passe pour un succès"
    )
    assert "Crée le Google Sheet" in resume
    assert "HTTP 400" in resume


@pytest.mark.asyncio
async def test_attempts_survive_across_ticks_in_the_real_graph(
    free_mission, monkeypatch,
) -> None:
    """Le compteur vit dans le checkpoint, pas dans un tick.

    Vérification d'INTÉGRATION : le heartbeat sort du graphe entre deux
    itérations. Un compteur qui ne survivrait pas au checkpoint laisserait
    le correctif vert en unitaire et inopérant en production — chaque tick
    repartirait de zéro et rejouerait l'étape indéfiniment.
    """
    from langgraph.checkpoint.memory import MemorySaver

    import app.agent.missions.nodes as mn
    from app.agent.missions.graph import build_mission_graph

    uid, mid = free_mission

    # L'acteur est neutralisé : ce test porte sur la persistance du
    # compteur, pas sur la sélection d'outil.
    async def _fake_act(state):
        return {
            "current_step_id": mn._next_pending_step(state["plan_json"])["id"],
            "last_tool_name": "drive_upload_local_file",
            "last_tool_output": "{'ok': true}",
        }

    monkeypatch.setattr(mn, "act_node", _fake_act)
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _verdict_llm(False, "fichier absent du Drive"),
    )
    # Le graphe capture les nodes à la construction → rebâtir après patch.
    import importlib

    import app.agent.missions.graph as mg
    importlib.reload(mg)
    graph = mg.build_mission_graph().compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": mid}}

    base = {
        "mission_id": mid, "user_id": uid, "goal": "déposer le fichier",
        "plan_version": 1, "plan_text": "", "plan_json": _plan_two_steps(),
    }
    tick1 = await graph.ainvoke(base, config=config)
    assert tick1["plan_json"]["steps"][0]["attempts"] == 1

    # 2e tick : le state repart du CHECKPOINT, pas de `base`.
    tick2 = await graph.ainvoke(
        {"mission_id": mid, "user_id": uid, "goal": "déposer le fichier"},
        config=config,
    )
    step = tick2["plan_json"]["steps"][0]
    assert step["attempts"] == 2, "le compteur doit survivre au tick"
    assert step["status"] == "skipped"
    assert mn._next_pending_step(tick2["plan_json"])["id"] == "2"

    importlib.reload(mg)  # rendre le module propre aux tests suivants
