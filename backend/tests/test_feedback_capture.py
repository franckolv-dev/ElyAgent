# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_feedback_capture.py
# @brief      C4-5 — les 👎 rejoignent le funnel d'apprentissage :
#             rating=-1 → FailureCase (famille user_feedback).
# @license    Elastic License 2.0
# =============================================================================
"""C4-5 (P5) — refermer la boucle de feedback.

Constat de la carte d'apprentissage (handoff §3) : les 👍/👎 sont écrits
en DB et JAMAIS lus par une boucle d'action (dashboards uniquement). Ce
lot fait des 👎 un signal de première classe : chaque rating=-1 crée un
FailureCase (nouvelle famille ``user_feedback``), que le cron
skill_autocreate ramasse naturellement (sélection processed_at IS NULL,
sans filtre de famille — vérifié skill_autocreate.py) : ≥ 3 cas d'un
même pattern → playbook candidate.

Pattern suivi : capture_* de failure_capture.py (best-effort, jamais
bloquant, dédup par empreinte tant que non-processed). Tests hermétiques
sur les handlers directs (pattern test_me_learning_skills).

Run with:  cd backend && python -m pytest tests/test_feedback_capture.py -v
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.failure_case import FailureCase
from app.models.feedback import Feedback
from app.routers.feedback import FeedbackIn, submit_feedback
from app.services.learning.failure_capture import (
    SIGNAL_USER_FEEDBACK,
    capture_from_user_feedback,
)


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"fbk-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"fbk_{uid}", email=f"{uid}@test.local",
                    hashed_password="x"))
        await db.commit()
    user = (await _get_user(uid))
    yield user
    async with async_session() as db:
        # FK-safe : enfants avant parent.
        await db.execute(delete(FailureCase).where(FailureCase.user_id == uid))
        await db.execute(delete(Feedback).where(Feedback.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _get_user(uid: str):
    from app.models.user import User
    async with async_session() as db:
        return (await db.execute(
            select(User).where(User.id == uid)
        )).scalar_one()


async def _failure_cases(uid: str) -> list[FailureCase]:
    async with async_session() as db:
        return list((await db.execute(
            select(FailureCase).where(
                FailureCase.user_id == uid,
                FailureCase.signal_table == SIGNAL_USER_FEEDBACK,
            )
        )).scalars().all())


# ────────────────────────────────────────────────────────────────────────
# La famille est une constante de première classe
# ────────────────────────────────────────────────────────────────────────


def test_family_constant_value():
    """La valeur est un contrat DB (FailureCase.signal_table) — la figer."""
    assert SIGNAL_USER_FEEDBACK == "user_feedback"


# ────────────────────────────────────────────────────────────────────────
# capture_from_user_feedback (unité, SQLite réel)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_creates_case_with_payload(_user):
    case_id = await capture_from_user_feedback(
        user_id=_user.id,
        user_message="range mes factures de mai dans Drive",
        conversation_id="conv-42",
        model_used="llm:test-model",
        feedback_id="fb-uuid-1",
    )
    assert case_id is not None
    cases = await _failure_cases(_user.id)
    assert len(cases) == 1
    fc = cases[0]
    assert fc.conversation_id == "conv-42"
    assert fc.processed_at is None
    payload = json.loads(fc.replay_payload)
    assert payload["signal_kind"] == "user_feedback_negative"
    assert "factures de mai" in payload["user_message"]
    assert payload["model_used"] == "llm:test-model"
    assert payload["feedback_id"] == "fb-uuid-1"


@pytest.mark.asyncio
async def test_capture_dedups_same_message_while_unprocessed(_user):
    """Deux 👎 sur la même demande → UNE row tant que non traitée (le
    cron a besoin de patterns, pas de doublons)."""
    a = await capture_from_user_feedback(
        user_id=_user.id, user_message="même demande ratée",
    )
    b = await capture_from_user_feedback(
        user_id=_user.id, user_message="même demande ratée",
    )
    assert a == b
    assert len(await _failure_cases(_user.id)) == 1


@pytest.mark.asyncio
async def test_capture_requires_user_and_message(_user):
    assert await capture_from_user_feedback(user_id="", user_message="x") is None
    assert await capture_from_user_feedback(user_id=_user.id, user_message="") is None
    assert await _failure_cases(_user.id) == []


# ────────────────────────────────────────────────────────────────────────
# Câblage endpoint (handler direct — pattern hermétique maison)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_thumbs_down_creates_failure_case(_user):
    out = await submit_feedback(
        FeedbackIn(
            conversation_id="conv-1",
            user_message="tu as vidé le mauvais dossier",
            rating=-1,
            model_used="llm:test",
            routing_score=50,
        ),
        current_user=_user,
    )
    assert out["status"] == "ok"
    cases = await _failure_cases(_user.id)
    assert len(cases) == 1
    payload = json.loads(cases[0].replay_payload)
    assert payload["feedback_id"] == out["id"]


@pytest.mark.asyncio
async def test_thumbs_up_creates_no_failure_case(_user):
    out = await submit_feedback(
        FeedbackIn(
            conversation_id="conv-2",
            user_message="parfait, merci",
            rating=1,
            model_used="llm:test",
            routing_score=50,
        ),
        current_user=_user,
    )
    assert out["status"] == "ok"
    assert await _failure_cases(_user.id) == []


@pytest.mark.asyncio
async def test_capture_failure_never_blocks_feedback(_user, monkeypatch):
    """La capture est best-effort : si elle explose, le feedback est
    quand même enregistré (le signal apprentissage ne doit jamais
    dégrader la surface utilisateur)."""
    import app.routers.feedback as fb_router

    async def _boom(**_kw):
        raise RuntimeError("capture down")

    monkeypatch.setattr(
        "app.services.learning.failure_capture.capture_from_user_feedback",
        _boom,
    )
    out = await submit_feedback(
        FeedbackIn(
            conversation_id="conv-3",
            user_message="encore raté",
            rating=-1,
            model_used="llm:test",
            routing_score=50,
        ),
        current_user=_user,
    )
    assert out["status"] == "ok"
    async with async_session() as db:
        fb = (await db.execute(
            select(Feedback).where(Feedback.id == out["id"])
        )).scalar_one()
    assert fb.rating == -1
