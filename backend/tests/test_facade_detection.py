# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_facade_detection.py
# @brief      Boucle d'auto-diagnostic J2 — heuristiques « succès de façade »
#             (maillon 1) + câblage enrichi (scheduler, missions, fallback).
# @license    Elastic License 2.0
# =============================================================================
"""Tests J2 — détection de succès de façade.

  1. Logique pure (is_write_tool, detect_write_intent, detect_claimed_no_tool,
     asked_to_schedule, tools_called_from_messages, compute_facade_signals).
  2. Orchestration (record_scheduled_outcome avec corrélation fallback).
  3. Câblage bout-en-bout (scheduler success → dubious, mission → dubious).

Run with:  cd backend && python -m pytest tests/test_facade_detection.py -v
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _seed_user() -> str:
    from app.database import async_session
    from app.models.user import User
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[:8]}", email=f"{uid[:8]}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _drain_bg() -> None:
    import app.services.background_tasks as bg
    for _ in range(10):
        tasks = [t for t in list(bg._BG_TASKS) if not t.done()]
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


async def _outcomes(user_id: str) -> list:
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    async with async_session() as db:
        return list((await db.execute(
            select(ExecutionOutcome).where(ExecutionOutcome.user_id == user_id)
        )).scalars().all())


# ── 1. Logique pure ───────────────────────────────────────────────────────


def test_is_write_tool_explicit_and_patterns() -> None:
    from app.services.learning.facade_detection import is_write_tool
    # explicites
    assert is_write_tool("gmail_send_email")
    assert is_write_tool("sheets_append_row")
    assert is_write_tool("desktop_write_file")
    # repli par motif de nom
    assert is_write_tool("custom_create_thing")
    assert is_write_tool("foo_upload_bar")
    # lectures → pas d'écriture
    assert not is_write_tool("gmail_list_emails")
    assert not is_write_tool("drive_get_file")
    assert not is_write_tool("calendar_get_settings")  # "settings" ne matche pas "set_"
    assert not is_write_tool("system_list_scheduled_tasks")
    assert not is_write_tool("")
    assert not is_write_tool(None)


def test_detect_write_intent_strong_verbs_only() -> None:
    from app.services.learning.facade_detection import detect_write_intent
    assert detect_write_intent("alimente le fichier CSV avec les prospects")
    assert detect_write_intent("crée un document de synthèse")
    assert detect_write_intent("mets à jour le tableau")
    assert detect_write_intent("supprime mes vieux mails")
    # « envoie-moi » = livraison canal, PAS une écriture → conservateur
    assert not detect_write_intent("envoie-moi le résumé du jour")
    assert not detect_write_intent("résume mes mails du matin")
    assert not detect_write_intent("")


def test_detect_claimed_no_tool() -> None:
    from app.services.learning.facade_detection import detect_claimed_no_tool
    assert detect_claimed_no_tool("Désolé, je n'ai pas d'outil pour envoyer des mails.")
    assert detect_claimed_no_tool("Aucun outil disponible pour cette action.")
    assert detect_claimed_no_tool("I don't have a tool for that.")
    assert not detect_claimed_no_tool("Voici le résumé de tes mails.")
    assert not detect_claimed_no_tool("")


def test_asked_to_schedule() -> None:
    from app.services.learning.facade_detection import asked_to_schedule
    assert asked_to_schedule("planifie un rappel chaque matin")
    assert asked_to_schedule("rappelle-moi tous les lundis")
    assert not asked_to_schedule("résume mes mails maintenant")


def test_tools_called_from_messages() -> None:
    from app.services.learning.facade_detection import tools_called_from_messages
    msgs = [
        HumanMessage(content="fais X"),
        AIMessage(content="", tool_calls=[
            {"name": "gmail_send_email", "args": {}, "id": "1"},
        ]),
        ToolMessage(content="ok", name="gmail_send_email", tool_call_id="1"),
        AIMessage(content="C'est fait."),
    ]
    names = tools_called_from_messages(msgs)
    assert "gmail_send_email" in names
    assert tools_called_from_messages(None) == []


def test_compute_facade_signals_no_write_effect() -> None:
    from app.services.learning.facade_detection import compute_facade_signals
    sig = compute_facade_signals(
        goal="alimente le CSV des prospects",
        final_text="C'est fait, le CSV est à jour.",
        tools_called=["drive_list_files"],  # lecture seule
    )
    assert sig == ["no_write_effect"]


def test_compute_facade_signals_write_tool_present_is_clean() -> None:
    from app.services.learning.facade_detection import compute_facade_signals
    sig = compute_facade_signals(
        goal="alimente le CSV des prospects",
        final_text="Fait.",
        tools_called=["sheets_append_row"],
    )
    assert sig == []


def test_compute_facade_signals_fallback_and_claimed_no_tool() -> None:
    from app.services.learning.facade_detection import compute_facade_signals
    sig = compute_facade_signals(
        goal="résume mes mails",  # pas d'intention d'écriture
        final_text="Je n'ai pas d'outil pour lire les mails.",
        tools_called=[],
        fallback_occurred=True,
    )
    assert "fallback" in sig
    assert "claimed_no_tool" in sig
    assert "no_write_effect" not in sig  # pas d'intention d'écriture


def test_compute_facade_signals_suspicious_delegation() -> None:
    from app.services.learning.facade_detection import compute_facade_signals
    # crée une tâche planifiée alors que le goal ne le demandait pas
    sig = compute_facade_signals(
        goal="résume mes mails du jour",
        final_text="J'ai programmé une tâche.",
        tools_called=["system_create_scheduled_task"],
    )
    assert "suspicious_delegation" in sig
    # si le goal DEMANDE une planification → pas suspect
    sig2 = compute_facade_signals(
        goal="planifie un résumé chaque matin",
        final_text="Tâche créée.",
        tools_called=["system_create_scheduled_task"],
    )
    assert "suspicious_delegation" not in sig2


# ── 2. Orchestration : corrélation fallback ───────────────────────────────


async def _seed_provider_switch(uid: str, conv_id: str) -> None:
    from app.database import async_session
    from app.models.provider_switch import ProviderSwitch
    async with async_session() as db:
        db.add(ProviderSwitch(
            user_id=uid, conversation_id=conv_id, tier_llm="C",
            from_provider="openai-codex", to_provider="deepseek-v4-pro",
            reason="timeout", position_in_chain=1,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_record_scheduled_outcome_fallback_makes_dubious() -> None:
    from app.services.learning.outcome_recording import record_scheduled_outcome
    uid = await _seed_user()
    conv = f"conv-{uuid.uuid4()}"
    await _seed_provider_switch(uid, conv)  # un fallback a eu lieu
    await record_scheduled_outcome(
        user_id=uid, task_id="t1", conversation_id=conv, channel="web",
        declared_status="success", goal="dis bonjour", final_text="Bonjour !",
        tools_called=[],
    )
    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].outcome == "dubious"
    assert "fallback" in (rows[0].signals or "")


@pytest.mark.asyncio
async def test_record_scheduled_outcome_clean_stays_succeeded() -> None:
    from app.services.learning.outcome_recording import record_scheduled_outcome
    uid = await _seed_user()
    await record_scheduled_outcome(
        user_id=uid, task_id="t2", conversation_id=f"conv-{uuid.uuid4()}",
        channel="web", declared_status="success",
        goal="résume mes mails", final_text="Voici ton résumé.", tools_called=[],
    )
    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].outcome == "succeeded"
    assert rows[0].signals is None


# ── 3. Câblage bout-en-bout ───────────────────────────────────────────────


class _FakeAgent:
    def __init__(self, message: str):
        self._message = message

    async def ainvoke(self, state, config=None):
        # aucune tool_call → aucun outil d'écriture appelé
        return {"messages": [HumanMessage(content="x"), AIMessage(content=self._message)]}


@pytest.mark.asyncio
async def test_execute_task_write_goal_no_tool_is_dubious(monkeypatch) -> None:
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    monkeypatch.setattr(graph_mod, "build_simple_agent_graph",
                        lambda: _FakeAgent("C'est fait, le CSV est alimenté."))

    async def _noop_deliver(task, content):
        return None
    monkeypatch.setattr(sched, "_deliver_result", _noop_deliver)

    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    uid = await _seed_user()
    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(ScheduledTask(id=tid, user_id=uid, name="Prospection",
                             prompt="alimente le fichier CSV avec les prospects",
                             cron_expression="0 9 * * *", channel="web"))
        await db.commit()

    await sched._execute_task(tid)
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].source == "scheduled"
    assert rows[0].outcome == "dubious"
    assert "no_write_effect" in (rows[0].signals or "")


@pytest.mark.asyncio
async def test_complete_mission_write_goal_no_steps_is_dubious() -> None:
    from app.database import async_session
    from app.models.mission import Mission
    from app.services import mission_service
    uid = await _seed_user()
    mid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(Mission(id=mid, user_id=uid, title="Synthèse",
                       goal="crée un document de synthèse des prospects",
                       status="running"))
        await db.commit()

    await mission_service.complete_mission(mid, "Mission accomplie.")
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].source == "mission"
    assert rows[0].declared_status == "completed"
    assert rows[0].outcome == "dubious"
    assert "no_write_effect" in (rows[0].signals or "")


# ── C1b (audit 16/07 §6.9) — calibration « jour vide » ──────────────────────
#
# 46,5 % des exécutions planifiées déclarées réussies étaient marquées
# douteuses, TOUTES via no_write_effect : les tâches à écriture
# CONDITIONNELLE (« nettoie le spam », « traite les factures ») lèvent le
# signal les jours où il n'y a légitimement rien à muter. La suppression
# exige une preuve POSITIVE : des outils ont réellement tourné ET le texte
# final déclare explicitement un résultat vide.


def test_detect_empty_outcome() -> None:
    from app.services.learning.facade_detection import detect_empty_outcome

    assert detect_empty_outcome("Aucun spam trouvé aujourd'hui.")
    assert detect_empty_outcome("Rien à traiter ce matin.")
    assert detect_empty_outcome("Pas de nouvelle facture dans la période.")
    assert detect_empty_outcome("0 email correspondant à la recherche.")
    assert detect_empty_outcome("No new invoices found for this period.")
    # Les CLAIMS de mutation ne matchent JAMAIS ici (pas d'analyse de
    # négation : le marqueur vide est porté par le texte lui-même).
    assert not detect_empty_outcome("12 emails supprimés, nettoyage terminé.")
    assert not detect_empty_outcome("J'ai mis 8 spams à la corbeille.")
    assert not detect_empty_outcome("10 emails archivés.")
    assert not detect_empty_outcome("")
    assert not detect_empty_outcome(None)


def test_no_write_effect_suppressed_on_verified_empty_day() -> None:
    """Jour sans spam : lecture exécutée + résultat vide déclaré = succès."""
    from app.services.learning.facade_detection import compute_facade_signals

    signals = compute_facade_signals(
        goal="Supprime tout ce qui ressemble à du spam",
        final_text="Aucun spam trouvé aujourd'hui — rien à supprimer.",
        tools_called=["gmail_search_for_cleanup"],
    )
    assert "no_write_effect" not in signals


def test_no_write_effect_kept_when_no_tool_ran_at_all() -> None:
    """« Aucun spam » sans même avoir cherché = suspicion intacte."""
    from app.services.learning.facade_detection import compute_facade_signals

    signals = compute_facade_signals(
        goal="Supprime tout ce qui ressemble à du spam",
        final_text="Aucun spam trouvé aujourd'hui.",
        tools_called=[],
    )
    assert "no_write_effect" in signals


def test_no_write_effect_kept_on_unproven_claim() -> None:
    """« J'ai supprimé 12 spams » sans outil d'écriture = la façade d'origine."""
    from app.services.learning.facade_detection import compute_facade_signals

    signals = compute_facade_signals(
        goal="Supprime tout ce qui ressemble à du spam",
        final_text="J'ai supprimé 12 spams, boîte propre.",
        tools_called=["gmail_search_for_cleanup"],
    )
    assert "no_write_effect" in signals
