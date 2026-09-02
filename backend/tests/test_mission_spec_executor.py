# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_spec_executor.py
# @brief      Sprint 4c J2 — exécuteur de missions structurées : plan
#             déterministe, expansion foreach, protocole EDGE_CASE,
#             handlers, terminaison déterministe, jamais de replan.
# @license    Elastic License 2.0
# =============================================================================
"""Sprint 4c J2 — pins de l'exécuteur spec."""
from __future__ import annotations

import textwrap
import types
import uuid

import pytest
import pytest_asyncio

_SPEC = textwrap.dedent("""
    version: 1
    steps:
      - id: collect
        do: "Collecte les entreprises du Sheet."
      - id: enrich
        foreach: "{{ collect.output }}"
        do: "Trouve le dirigeant de {{ item }}."
        on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
        on_not_found: skip_with_note("{{ item }} introuvable")
        on_error: resume_next
""").strip()


@pytest_asyncio.fixture
async def spec_mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStepRun
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()  # 0003 sur la base de test locale (legacy)
    uid = f"test_4c2_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="prospecter", spec_yaml=_SPEC,
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
# Plan déterministe
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_node_short_circuits_llm_for_spec(spec_mission, monkeypatch) -> None:
    """Le plan EST la spec : le planner LLM ne doit JAMAIS être appelé."""
    import app.agent.missions.nodes as mn

    uid, mid = spec_mission

    def _no_llm():
        raise AssertionError("le planner LLM a été appelé pour une mission spec")

    monkeypatch.setattr(mn, "_get_planner_llm", _no_llm)

    out = await mn.plan_node({
        "mission_id": mid, "user_id": uid, "goal": "prospecter",
    })

    assert out["plan_version"] == 1
    assert out["plan_json"]["from_spec"] is True
    ids = [s["id"] for s in out["plan_json"]["steps"]]
    assert ids == ["collect", "enrich"]
    enrich = out["plan_json"]["steps"][1]
    assert enrich["foreach"] == "{{ collect.output }}"
    assert enrich["handlers"]["ambiguous"]["action"] == "ask_user"


# ─────────────────────────────────────────────────────────────────────────
# Expansion foreach + progression
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_foreach_creates_runs_and_is_idempotent(
    spec_mission, monkeypatch,
) -> None:
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission

    class _FakeLLM:
        async def ainvoke(self, _msgs):
            return types.SimpleNamespace(content='["Acme Corp", "Gamma SARL"]')

    monkeypatch.setattr(
        msr, "get_llm_for_tier", lambda _t: _FakeLLM(), raising=False,
    )
    import app.services.llm_provider as lp
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda _t: _FakeLLM())

    step = {"id": "enrich", "description": "Trouve {{ item }}", "foreach": "{{ collect.output }}"}
    runs = await msr.expand_foreach(mid, uid, step, "Acme Corp\nGamma SARL")

    assert [r.item_value for r in runs] == ["Acme Corp", "Gamma SARL"]
    assert all(r.status == "pending" for r in runs)

    # Idempotent : un 2e appel (reprise de tick) ne duplique rien
    runs2 = await msr.expand_foreach(mid, uid, step, "peu importe")
    assert len(runs2) == 2

    nxt = await msr.next_pending_run(mid, "enrich")
    assert nxt is not None and nxt.item_index == 0


@pytest.mark.asyncio
async def test_render_item_and_progress(spec_mission) -> None:
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    assert msr.render_item("Trouve {{ item }} et {{item}}", "Acme") == "Trouve Acme et Acme"

    await msr.ensure_step_run(mid, "enrich", 0, "Acme")
    await msr.ensure_step_run(mid, "enrich", 1, "Gamma")
    await msr.set_step_run_status(mid, "enrich", 0, status="done", output="ok")
    await msr.set_step_run_status(mid, "enrich", 1, status="waiting_user", note="lequel ?")

    runs = await msr.list_step_runs(mid, "enrich")
    done, waiting, total = msr.step_progress(runs)
    assert (done, waiting, total) == (1, 1, 2)


# ─────────────────────────────────────────────────────────────────────────
# Protocole EDGE_CASE + handlers
# ─────────────────────────────────────────────────────────────────────────


def test_edge_protocol_prompt_and_parse() -> None:
    from app.services.mission_spec_runtime import (
        EDGE_MARKER,
        edge_protocol_prompt,
        parse_edge_case,
    )

    block = edge_protocol_prompt({
        "ambiguous": {"action": "ask_user", "message": "lequel ?"},
        "not_found": {"action": "skip_with_note", "message": "introuvable"},
    })
    assert "ambiguous" in block and "ask_user" in block
    assert EDGE_MARKER in block
    assert "NE FAIS AUCUN appel d'outil" in block

    assert parse_edge_case("EDGE_CASE: not_found | rien sur LinkedIn") == (
        "not_found", "rien sur LinkedIn",
    )
    assert parse_edge_case("blabla EDGE_CASE: Ambiguous") == ("ambiguous", "")
    assert parse_edge_case("réponse normale sans marqueur") is None


@pytest.mark.asyncio
async def test_eval_applies_ask_user_handler(spec_mission) -> None:
    """ask_user → l'item est parqué en waiting_user avec la question
    templée ({{ item }} substitué) — le ping + la reprise = J3."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "enrich", 0, "Gamma SARL")

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "collect", "description": "x", "status": "done", "handlers": {}},
            {"id": "enrich", "description": "Trouve {{ item }}",
             "foreach": "{{ collect.output }}",
             "handlers": {"ambiguous": {"action": "ask_user",
                                        "message": "Plusieurs résultats pour {{ item }} — lequel ?"}}},
        ],
    }
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "plan_json": plan_json,
        "current_step_id": "enrich", "current_item_index": 0,
        "last_edge_case": {"name": "ambiguous", "detail": "3 résultats"},
    })

    assert out["last_edge_case"] is None
    assert out["consecutive_failures"] == 0
    assert "failed" not in out

    runs = await msr.list_step_runs(mid, "enrich")
    assert runs[0].status == "waiting_user"
    assert "Gamma SARL" in runs[0].note, "le message doit être templé avec l'item"


@pytest.mark.asyncio
async def test_eval_applies_skip_handler_and_undeclared_degrades(spec_mission) -> None:
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "enrich", 0, "Delta")
    await msr.ensure_step_run(mid, "enrich", 1, "Omega")

    # L'item 0 a réellement cherché. Depuis le 31/08/2026, `not_found` est
    # refusé tant qu'aucun outil n'a tourné sur l'item : deux sociétés
    # avaient été consignées « aucun contact trouvé » sans être regardées.
    # Ce test-ci porte sur l'APPLICATION du handler, pas sur ce garde-fou.
    from app.services import mission_service as _ms
    await _ms.add_step(
        mid, phase="act", tool_name="web_search", tool_input={},
        tool_output="rien", thought="Étape « [Item 1 : Delta] cherche »",
        success=True, duration_ms=1,
    )

    plan_json = {
        "from_spec": True,
        "steps": [{
            "id": "enrich", "description": "x", "foreach": "libre",
            "handlers": {"not_found": {"action": "skip_with_note",
                                       "message": "{{ item }} introuvable"}},
        }],
    }
    # Cas déclaré → skip avec note templée
    await mn.eval_node({
        "mission_id": mid, "user_id": uid, "plan_json": plan_json,
        "current_step_id": "enrich", "current_item_index": 0,
        "last_edge_case": {"name": "not_found", "detail": ""},
    })
    # Cas NON déclaré → dégrade en resume_next (skip journalisé)
    await mn.eval_node({
        "mission_id": mid, "user_id": uid, "plan_json": plan_json,
        "current_step_id": "enrich", "current_item_index": 1,
        "last_edge_case": {"name": "site_en_maintenance", "detail": "503"},
    })

    runs = await msr.list_step_runs(mid, "enrich")
    assert runs[0].status == "skipped" and "Delta introuvable" in runs[0].note
    assert runs[1].status == "skipped" and "503" in runs[1].note


@pytest.mark.asyncio
async def test_eval_fail_handler_fails_mission(spec_mission) -> None:
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "collect", 0, None)

    plan_json = {
        "from_spec": True,
        "steps": [{"id": "collect", "description": "x",
                   "handlers": {"sheet_absent": {"action": "fail",
                                                 "message": "Sheet introuvable"}}}],
    }
    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "plan_json": plan_json,
        "current_step_id": "collect", "current_item_index": 0,
        "last_edge_case": {"name": "sheet_absent", "detail": ""},
    })
    assert out["failed"] is True
    assert "Sheet introuvable" in out["failure_reason"]


# ─────────────────────────────────────────────────────────────────────────
# act_node : foreach terminé / items en attente
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_act_marks_foreach_step_done_when_all_items_terminal(
    spec_mission,
) -> None:
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "enrich", 0, "Acme")
    await msr.set_step_run_status(mid, "enrich", 0, status="done", output="ok")

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "collect", "description": "x", "status": "done", "handlers": {}},
            {"id": "enrich", "description": "Trouve {{ item }}",
             "foreach": "{{ collect.output }}", "handlers": {}},
        ],
    }
    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "g",
        "plan_json": plan_json, "plan_text": "t",
    })
    enrich = next(s for s in out["plan_json"]["steps"] if s["id"] == "enrich")
    assert enrich["status"] == "done"
    assert "foreach terminé" in out["last_eval_reason"]


@pytest.mark.asyncio
async def test_act_noop_when_items_waiting_user(spec_mission) -> None:
    """Des items ⏸ : la mission n'avance pas sur ce step et NE le marque
    pas done — la reprise viendra de la réponse utilisateur (J3)."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "enrich", 0, "Gamma")
    await msr.set_step_run_status(mid, "enrich", 0, status="waiting_user", note="lequel ?")

    plan_json = {
        "from_spec": True,
        "steps": [
            {"id": "collect", "description": "x", "status": "done", "handlers": {}},
            {"id": "enrich", "description": "Trouve {{ item }}",
             "foreach": "{{ collect.output }}", "handlers": {}},
        ],
    }
    out = await mn.act_node({
        "mission_id": mid, "user_id": uid, "goal": "g",
        "plan_json": plan_json, "plan_text": "t",
    })
    assert "attente" in out["last_eval_reason"]
    assert "plan_json" not in out, "le step ne doit PAS être marqué done"


# ─────────────────────────────────────────────────────────────────────────
# Terminaison déterministe + migration 0003 + endpoint
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_0003_creates_table_on_legacy_db(tmp_path, monkeypatch) -> None:
    import sqlite3

    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, goal TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )
    assert await ar.ensure_migrations() == "stamped+upgraded"

    check = sqlite3.connect(db_path)
    tables = {r[0] for r in check.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    check.close()
    assert "mission_step_runs" in tables


@pytest.mark.asyncio
async def test_structure_endpoint_scoped_to_owner(spec_mission) -> None:
    """L'outline montre TOUS les steps de la spec (même pas encore
    touchés) + les runs existants — un seul round-trip pour le viewer."""
    from fastapi import HTTPException

    from app.routers.missions import mission_structure
    from app.services import mission_spec_runtime as msr

    uid, mid = spec_mission
    await msr.ensure_step_run(mid, "enrich", 0, "Acme")

    out = await mission_structure(
        mid, current_user=types.SimpleNamespace(id=uid),
    )
    assert [s.id for s in out.steps] == ["collect", "enrich"]
    assert out.steps[1].handler_cases == ["ambiguous", "error", "not_found"]
    assert len(out.runs) == 1 and out.runs[0].step_id == "enrich"

    with pytest.raises(HTTPException) as exc_info:
        await mission_structure(
            mid, current_user=types.SimpleNamespace(id="autre_user"),
        )
    assert exc_info.value.status_code == 404
