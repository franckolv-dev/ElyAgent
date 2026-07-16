# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_incidents_api.py
# @brief      Boucle d'auto-diagnostic J4 — endpoints admin « Incidents &
#             propositions » (list + resolve). Handlers appelés directement
#             (pattern hermétique, cf. test_me_learning_skills).
# @license    Elastic License 2.0
# =============================================================================
"""Tests J4 — endpoints /admin/learning/incidents.

Run with:  cd backend && python -m pytest tests/test_incidents_api.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


def _fake_admin(uid: str = "admin"):
    class _U:
        id = uid
    return _U()


async def _seed_user() -> str:
    from app.database import async_session
    from app.models.user import User
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[:8]}", email=f"{uid[:8]}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _seed_incident(uid: str, *, outcome: str = "dubious",
                         category: str = "binding", signals=None,
                         status: str = "open", occurrences: int = 1,
                         last_seen=None) -> tuple[int, int]:
    """Crée un execution_outcome + son execution_diagnosis. Renvoie (outcome_id, diag_id)."""
    import json
    from app.database import async_session
    from app.models.execution_diagnosis import ExecutionDiagnosis
    from app.models.execution_outcome import ExecutionOutcome
    async with async_session() as db:
        oc = ExecutionOutcome(
            user_id=uid, source="scheduled", outcome=outcome,
            declared_status="success", channel="web", tier_llm="C",
            signals=json.dumps(signals) if signals else None,
        )
        db.add(oc)
        await db.commit()
        oc_id = oc.id
        diag = ExecutionDiagnosis(
            execution_outcome_id=oc_id, user_id=uid, source="scheduled",
            category=category, hypothesis="Trou de binding probable.",
            confidence="medium", status=status, critic_model="rule-based",
            occurrences=occurrences, last_seen_at=last_seen,
        )
        db.add(diag)
        await db.commit()
        return oc_id, diag.id


@pytest.mark.asyncio
async def test_list_incidents_joins_outcome_context() -> None:
    from app.database import async_session
    from app.routers.learning_skills import list_incidents
    uid = await _seed_user()
    await _seed_incident(uid, outcome="dubious", category="binding",
                         signals=["claimed_no_tool"])
    async with async_session() as db:
        rows = await list_incidents(status="open", user_id=uid, limit=100,
                                    _admin=_fake_admin(), db=db)
    assert len(rows) == 1
    inc = rows[0]
    assert inc.category == "binding"
    assert inc.outcome == "dubious"
    assert inc.tier_llm == "C"
    assert inc.channel == "web"
    assert inc.signals == ["claimed_no_tool"]
    assert inc.status == "open"


@pytest.mark.asyncio
async def test_resolve_incident_sets_status_and_excludes_from_open() -> None:
    from app.database import async_session
    from app.routers.learning_skills import (
        IncidentResolveRequest,
        list_incidents,
        resolve_incident,
    )
    uid = await _seed_user()
    _oc, did = await _seed_incident(uid)

    async with async_session() as db:
        out = await resolve_incident(
            did, IncidentResolveRequest(status="validated", resolution="cause juste"),
            _admin=_fake_admin(), db=db,
        )
    assert out.status == "validated"
    assert out.processed_at is not None
    assert out.resolution == "cause juste"

    # n'apparaît plus dans "open", mais bien dans "all"
    async with async_session() as db:
        open_rows = await list_incidents(status="open", user_id=uid, limit=100,
                                         _admin=_fake_admin(), db=db)
    async with async_session() as db:
        all_rows = await list_incidents(status="all", user_id=uid, limit=100,
                                        _admin=_fake_admin(), db=db)
    assert open_rows == []
    assert len(all_rows) == 1
    assert all_rows[0].status == "validated"


@pytest.mark.asyncio
async def test_resolve_incident_rejects_bad_status() -> None:
    from app.database import async_session
    from app.routers.learning_skills import IncidentResolveRequest, resolve_incident
    uid = await _seed_user()
    _oc, did = await _seed_incident(uid)
    async with async_session() as db:
        with pytest.raises(HTTPException) as ei:
            await resolve_incident(did, IncidentResolveRequest(status="open"),
                                   _admin=_fake_admin(), db=db)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_incident_404_on_missing() -> None:
    from app.database import async_session
    from app.routers.learning_skills import IncidentResolveRequest, resolve_incident
    async with async_session() as db:
        with pytest.raises(HTTPException) as ei:
            await resolve_incident(999999, IncidentResolveRequest(status="validated"),
                                   _admin=_fake_admin(), db=db)
    assert ei.value.status_code == 404


def test_incidents_router_registered() -> None:
    """Garde-fou : les routes incidents sont bien montées."""
    from app.routers.learning_skills import router
    paths = {r.path for r in router.routes}
    assert "/admin/learning/incidents" in paths
    assert "/admin/learning/incidents/{incident_id}/resolve" in paths


# ── Dédup des récurrences (occurrences / last_seen_at / merged) ────────────


@pytest.mark.asyncio
async def test_list_incidents_exposes_occurrences_and_last_seen() -> None:
    from datetime import datetime, timezone

    from app.database import async_session
    from app.routers.learning_skills import list_incidents
    uid = await _seed_user()
    seen = datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc)
    await _seed_incident(uid, occurrences=7, last_seen=seen)
    async with async_session() as db:
        rows = await list_incidents(status="open", user_id=uid, limit=100,
                                    _admin=_fake_admin(), db=db)
    assert len(rows) == 1
    assert rows[0].occurrences == 7
    assert rows[0].last_seen_at is not None
    assert rows[0].last_seen_at.startswith("2026-07-16")


@pytest.mark.asyncio
async def test_list_incidents_open_hides_merged() -> None:
    from app.database import async_session
    from app.routers.learning_skills import list_incidents
    uid = await _seed_user()
    await _seed_incident(uid, status="open")
    await _seed_incident(uid, status="merged")
    async with async_session() as db:
        open_rows = await list_incidents(status="open", user_id=uid, limit=100,
                                         _admin=_fake_admin(), db=db)
    async with async_session() as db:
        all_rows = await list_incidents(status="all", user_id=uid, limit=100,
                                        _admin=_fake_admin(), db=db)
    assert [r.status for r in open_rows] == ["open"]
    assert sorted(r.status for r in all_rows) == ["merged", "open"]


@pytest.mark.asyncio
async def test_resolve_incident_rejects_merged_status() -> None:
    """merged est posé par la garde de dédup, jamais par l'humain."""
    from app.database import async_session
    from app.routers.learning_skills import IncidentResolveRequest, resolve_incident
    uid = await _seed_user()
    _oc, did = await _seed_incident(uid)
    async with async_session() as db:
        with pytest.raises(HTTPException) as ei:
            await resolve_incident(did, IncidentResolveRequest(status="merged"),
                                   _admin=_fake_admin(), db=db)
    assert ei.value.status_code == 400
