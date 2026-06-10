# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_ask_user.py
# @brief      Sprint 4c J3 — hook ask_user : notification multicanal,
#             endpoint de réponse, reprise immédiate avec injection.
# @license    Elastic License 2.0
# =============================================================================
"""Sprint 4c J3 — pins du cycle question → réponse → reprise.

LE cœur de la valeur du sprint (backlog) : « mission qui hésite → ping →
user répond → reprise ». Le mode chat fait à la main, automatisé.
"""
from __future__ import annotations

import json
import textwrap
import types
import uuid

import pytest
import pytest_asyncio

_SPEC = textwrap.dedent("""
    version: 1
    steps:
      - id: enrich
        foreach: "les entreprises du fichier"
        do: "Trouve le dirigeant de {{ item }}."
        on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
""").strip()


@pytest_asyncio.fixture
async def waiting_mission():
    """Mission spec avec un item parqué en waiting_user."""
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStepRun
    from app.models.user import User
    from app.services import mission_service
    from app.services import mission_spec_runtime as msr
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()  # 0004 sur la base de test locale
    uid = f"test_4c3_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="prospecter", spec_yaml=_SPEC,
    )
    await msr.ensure_step_run(m.id, "enrich", 0, "Gamma SARL")
    await msr.set_step_run_status(
        m.id, "enrich", 0, status="waiting_user",
        note="Plusieurs résultats pour Gamma SARL — lequel ?",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStepRun).where(MissionStepRun.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Notification multicanal
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_user_handler_notifies_all_user_sockets(
    waiting_mission, monkeypatch,
) -> None:
    """eval_node applique ask_user → event mission_question poussé en
    fan-out (toutes les sockets du user, B-6) avec la question TEMPLÉE."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr
    from app.services import ws_registry

    uid, mid = waiting_mission
    await msr.ensure_step_run(mid, "enrich", 1, "Acme Corp")

    sent: list[tuple[str, str]] = []

    async def fake_send_all(user_id, text):
        sent.append((user_id, text))
        return 1

    monkeypatch.setattr(ws_registry, "send_text_all", fake_send_all)

    plan_json = {
        "from_spec": True,
        "steps": [{
            "id": "enrich", "description": "Trouve {{ item }}",
            "foreach": "libre",
            "handlers": {"ambiguous": {"action": "ask_user",
                                       "message": "Plusieurs résultats pour {{ item }} — lequel ?"}},
        }],
    }
    await mn.eval_node({
        "mission_id": mid, "user_id": uid, "plan_json": plan_json,
        "current_step_id": "enrich", "current_item_index": 1,
        "last_edge_case": {"name": "ambiguous", "detail": "3 résultats"},
    })

    assert len(sent) == 1
    target_user, raw = sent[0]
    payload = json.loads(raw)
    assert target_user == uid
    assert payload["type"] == "mission_question"
    assert payload["mission_id"] == mid
    assert payload["step_id"] == "enrich" and payload["item_index"] == 1
    assert "Acme Corp" in payload["question"], "la question doit être templée"
    assert payload["item_value"] == "Acme Corp"


# ─────────────────────────────────────────────────────────────────────────
# Endpoint de réponse → reprise
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_answer_resumes_item_and_mission(waiting_mission) -> None:
    from app.routers.missions import StepRunAnswerIn, answer_step_run
    from app.services import mission_service
    from app.services import mission_spec_runtime as msr

    uid, mid = waiting_mission

    out = await answer_step_run(
        mid, "enrich", 0,
        StepRunAnswerIn(answer="Celle de Bordeaux, SIREN 123456789"),
        current_user=types.SimpleNamespace(id=uid),
    )

    assert out.status == "pending", "l'item doit être relancé"
    assert out.answer == "Celle de Bordeaux, SIREN 123456789"
    assert out.attempts == 0, "la réponse mérite des tentatives fraîches"
    assert out.note is not None, "la question reste (contexte d'audit + injection)"

    # La mission est redevenue due immédiatement (reprise sans attendre)
    m = await mission_service.get_mission(mid)
    assert m.next_tick_at is not None

    runs = await msr.list_step_runs(mid, "enrich")
    assert runs[0].status == "pending"


@pytest.mark.asyncio
async def test_answer_rejects_non_waiting_and_foreign(waiting_mission) -> None:
    from fastapi import HTTPException

    from app.routers.missions import StepRunAnswerIn, answer_step_run
    from app.services import mission_spec_runtime as msr

    uid, mid = waiting_mission

    # Un autre utilisateur → 404 (pas d'oracle)
    with pytest.raises(HTTPException) as exc_info:
        await answer_step_run(
            mid, "enrich", 0, StepRunAnswerIn(answer="x"),
            current_user=types.SimpleNamespace(id="intrus"),
        )
    assert exc_info.value.status_code == 404

    # Item déjà traité → 409
    await msr.set_step_run_status(mid, "enrich", 0, status="done", output="ok")
    with pytest.raises(HTTPException) as exc_info:
        await answer_step_run(
            mid, "enrich", 0, StepRunAnswerIn(answer="trop tard"),
            current_user=types.SimpleNamespace(id=uid),
        )
    assert exc_info.value.status_code == 409


# ─────────────────────────────────────────────────────────────────────────
# Injection de la réponse au prompt acteur
# ─────────────────────────────────────────────────────────────────────────


def test_answer_context_block() -> None:
    from app.services.mission_spec_runtime import answer_context

    run = types.SimpleNamespace(
        note="Plusieurs résultats pour Gamma SARL — lequel ?",
        answer="Celle de Bordeaux",
    )
    block = answer_context(run)
    assert "RÉPONSE DE L'UTILISATEUR" in block
    assert "Celle de Bordeaux" in block
    assert "Gamma SARL" in block, "la question d'origine donne le contexte"
    assert "ne repose pas" in block

    assert answer_context(types.SimpleNamespace(note="q", answer=None)) == ""


@pytest.mark.asyncio
async def test_act_injects_answer_into_actor_prompt(
    waiting_mission, monkeypatch,
) -> None:
    """Cycle complet : réponse soumise → l'item repart pending → au tick
    suivant, le prompt de l'acteur contient la réponse de l'utilisateur."""
    import app.agent.missions.nodes as mn
    from app.routers.missions import StepRunAnswerIn, answer_step_run
    from app.services import mission_spec_runtime as msr

    uid, mid = waiting_mission
    await answer_step_run(
        mid, "enrich", 0, StepRunAnswerIn(answer="Celle de Bordeaux"),
        current_user=types.SimpleNamespace(id=uid),
    )

    captured: dict = {}

    class _FakeActorLLM:
        async def ainvoke(self, messages):
            captured["system"] = messages[0].content
            # Signale un edge pour court-circuiter le dispatch d'outil
            return types.SimpleNamespace(
                content="EDGE_CASE: ambiguous | toujours pas sûr",
                tool_calls=[], usage_metadata=None, response_metadata={},
            )

    async def fake_actors(**_kw):
        return _FakeActorLLM(), [], []

    monkeypatch.setattr(mn, "_get_actor_llms", fake_actors)

    async def fake_notify(*_a, **_kw):  # pas de vrai ping en test
        return None

    monkeypatch.setattr(msr, "notify_ask_user", fake_notify)

    plan_json = {
        "from_spec": True,
        "steps": [{
            "id": "enrich", "description": "Trouve le dirigeant de {{ item }}",
            "foreach": "libre",
            "handlers": {"ambiguous": {"action": "ask_user", "message": "lequel ?"}},
        }],
    }
    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "prospecter",
        "plan_json": plan_json, "plan_text": "t",
    })

    assert "RÉPONSE DE L'UTILISATEUR" in captured["system"]
    assert "Celle de Bordeaux" in captured["system"]
    assert "Gamma SARL" in captured["system"], "{{ item }} doit être substitué"
    # L'acteur a re-signalé un cas → le cycle edge continue proprement
    assert out["last_edge_case"]["name"] == "ambiguous"


# ─────────────────────────────────────────────────────────────────────────
# Migration 0004
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_0004_adds_answer_column(tmp_path, monkeypatch) -> None:
    import sqlite3

    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE mission_step_runs (id TEXT PRIMARY KEY, mission_id TEXT, "
        "step_id TEXT, item_index INTEGER, status TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )
    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    cols = {r[1] for r in check.execute("PRAGMA table_info(mission_step_runs)")}
    check.close()
    assert "answer" in cols
