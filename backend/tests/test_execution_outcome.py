# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_execution_outcome.py
# @brief      Boucle d'auto-diagnostic J1 — signal execution_outcome +
#             câblage (scheduler, missions) + régression visible.
# @license    Elastic License 2.0
# =============================================================================
"""Tests J1 — boucle d'auto-diagnostic.

Quatre couches :
  1. classify_outcome (verdict pur, sans DB).
  2. record_execution_outcome (forme de la ligne + contrat never-raise).
  3. Câblage : _execute_task (scheduler) et complete/fail_mission posent
     un verdict.
  4. regression_report : taux réel par groupe + alerte de chute.

Run with:  cd backend && python -m pytest tests/test_execution_outcome.py -v
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
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
    """Awaits les tâches fire-and-forget (spawn) jusqu'à épuisement."""
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


# ── 1. classify_outcome ───────────────────────────────────────────────────


def test_classify_outcome_declared_success_no_signals() -> None:
    from app.services.learning.signals import classify_outcome
    assert classify_outcome("success", []) == "succeeded"
    assert classify_outcome("completed", None) == "succeeded"


def test_classify_outcome_failed_declared_wins_over_signals() -> None:
    from app.services.learning.signals import classify_outcome
    for s in ("error", "failed", "aborted", "ERROR"):
        assert classify_outcome(s, ["whatever"]) == "failed"


def test_classify_outcome_signals_demote_to_dubious() -> None:
    from app.services.learning.signals import classify_outcome
    assert classify_outcome("success", ["no_write_effect"]) == "dubious"
    assert classify_outcome("completed", ["fallback", "empty_promise"]) == "dubious"


# ── 2. record_execution_outcome ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_execution_outcome_persists_row() -> None:
    from app.services.learning.signals import record_execution_outcome
    uid = await _seed_user()
    rid = await record_execution_outcome(
        user_id=uid, source="scheduled", source_id="task-1",
        channel="telegram", declared_status="success",
    )
    assert rid is not None
    rows = await _outcomes(uid)
    assert len(rows) == 1
    r = rows[0]
    assert r.source == "scheduled"
    assert r.source_id == "task-1"
    assert r.channel == "telegram"
    assert r.declared_status == "success"
    assert r.outcome == "succeeded"
    assert r.signals is None  # J1 : pas de signaux faibles encore


@pytest.mark.asyncio
async def test_record_execution_outcome_with_signals_is_dubious() -> None:
    from app.services.learning.signals import record_execution_outcome
    uid = await _seed_user()
    await record_execution_outcome(
        user_id=uid, source="mission", source_id="m-1",
        declared_status="completed", signals=["no_write_effect", "fallback"],
    )
    r = (await _outcomes(uid))[0]
    assert r.outcome == "dubious"
    assert "no_write_effect" in (r.signals or "")


@pytest.mark.asyncio
async def test_record_execution_outcome_never_raises_on_bad_input() -> None:
    from app.services.learning.signals import record_execution_outcome
    # user_id manquant → None, pas d'exception (contrat best-effort)
    assert await record_execution_outcome(user_id="", source="scheduled") is None
    assert await record_execution_outcome(user_id="x", source="") is None


# ── 3. Câblage scheduler ──────────────────────────────────────────────────


class _FakeAgent:
    def __init__(self, *, raises: bool = False):
        self._raises = raises

    async def ainvoke(self, state, config=None):
        if self._raises:
            raise RuntimeError("boom")
        return {"messages": [AIMessage(content="rapport produit")]}


async def _seed_task(uid: str, channel: str = "web") -> str:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(ScheduledTask(id=tid, user_id=uid, name="T", prompt="fais X",
                             cron_expression="0 9 * * *", channel=channel))
        await db.commit()
    return tid


@pytest.mark.asyncio
async def test_execute_task_records_succeeded(monkeypatch) -> None:
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _FakeAgent())

    async def _noop_deliver(task, content):
        return None
    monkeypatch.setattr(sched, "_deliver_result", _noop_deliver)

    uid = await _seed_user()
    tid = await _seed_task(uid, channel="telegram")
    await sched._execute_task(tid)
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].source == "scheduled"
    assert rows[0].source_id == tid
    assert rows[0].channel == "telegram"
    assert rows[0].outcome == "succeeded"


@pytest.mark.asyncio
async def test_execute_task_records_failed_on_crash(monkeypatch) -> None:
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _FakeAgent(raises=True))

    uid = await _seed_user()
    tid = await _seed_task(uid)
    await sched._execute_task(tid)
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].outcome == "failed"
    assert rows[0].declared_status == "error"


# ── 3b. Câblage missions ──────────────────────────────────────────────────


async def _seed_mission(uid: str, status: str = "running") -> str:
    from app.database import async_session
    from app.models.mission import Mission
    mid = str(uuid.uuid4())
    async with async_session() as db:
        # Goal en LECTURE SEULE volontairement : ce test J1 vérifie « complété
        # → succeeded ». Un goal d'écriture déclencherait le signal J2
        # « no_write_effect » (0 outil d'écriture) et basculerait en dubious —
        # comportement testé séparément dans test_facade_detection.py.
        db.add(Mission(id=mid, user_id=uid, title="M",
                       goal="résume l'actualité du jour", status=status))
        await db.commit()
    return mid


@pytest.mark.asyncio
async def test_complete_mission_records_succeeded() -> None:
    from app.services import mission_service
    uid = await _seed_user()
    mid = await _seed_mission(uid, status="running")
    await mission_service.complete_mission(mid, "fini")
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].source == "mission"
    assert rows[0].source_id == mid
    assert rows[0].declared_status == "completed"
    assert rows[0].outcome == "succeeded"


@pytest.mark.asyncio
async def test_fail_mission_records_failed() -> None:
    from app.services import mission_service
    uid = await _seed_user()
    mid = await _seed_mission(uid, status="running")
    await mission_service.fail_mission(mid, "budget exhausted")
    await _drain_bg()

    rows = await _outcomes(uid)
    assert len(rows) == 1
    assert rows[0].source == "mission"
    assert rows[0].outcome == "failed"
    assert rows[0].declared_status == "failed"


# ── 4. regression_report ──────────────────────────────────────────────────


async def _seed_outcome(uid: str, *, outcome: str, when: datetime,
                        source: str = "scheduled", channel: str = "web") -> None:
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    async with async_session() as db:
        db.add(ExecutionOutcome(
            user_id=uid, source=source, channel=channel,
            outcome=outcome, declared_status="-", created_at=when,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_regression_report_flags_success_drop() -> None:
    from app.services.learning.regression import regression_report
    uid = await _seed_user()
    now = datetime.now(timezone.utc)
    # Référence (il y a ~7 jours) : tout réussit.
    for _ in range(6):
        await _seed_outcome(uid, outcome="succeeded", when=now - timedelta(days=7))
    # Récent (il y a ~1 jour) : tout échoue → régression franche.
    for _ in range(6):
        await _seed_outcome(uid, outcome="failed", when=now - timedelta(days=1))

    report = await regression_report(
        user_id=uid, window="30d", recent="3d", baseline="14d",
        min_samples=3, drop_threshold=0.3,
    )
    assert report["totals"]["total"] == 12
    assert len(report["alerts"]) == 1
    alert = report["alerts"][0]
    assert alert["kind"] == "success_drop"
    assert alert["group"] == "source=scheduled · channel=web"
    assert alert["baseline_real_success_rate"] == 1.0
    assert alert["recent_real_success_rate"] == 0.0
    assert alert["severity"] == "high"


@pytest.mark.asyncio
async def test_regression_report_no_alert_when_stable() -> None:
    from app.services.learning.regression import regression_report
    uid = await _seed_user()
    now = datetime.now(timezone.utc)
    for _ in range(6):
        await _seed_outcome(uid, outcome="succeeded", when=now - timedelta(days=7))
    for _ in range(6):
        await _seed_outcome(uid, outcome="succeeded", when=now - timedelta(days=1))

    report = await regression_report(
        user_id=uid, window="30d", recent="3d", baseline="14d",
        min_samples=3, drop_threshold=0.3,
    )
    assert report["alerts"] == []
    assert report["totals"]["real_success_rate"] == 1.0


@pytest.mark.asyncio
async def test_regression_report_respects_min_samples() -> None:
    from app.services.learning.regression import regression_report
    uid = await _seed_user()
    now = datetime.now(timezone.utc)
    # Sous le seuil d'échantillon → pas d'alerte malgré la chute.
    await _seed_outcome(uid, outcome="succeeded", when=now - timedelta(days=7))
    await _seed_outcome(uid, outcome="failed", when=now - timedelta(days=1))

    report = await regression_report(
        user_id=uid, window="30d", recent="3d", baseline="14d",
        min_samples=3, drop_threshold=0.3,
    )
    assert report["alerts"] == []
