# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_persistence.py
# @brief      V0-2 — une validation en attente survit au redémarrage du backend.
# @license    MIT
# =============================================================================
"""Pins de la persistance HITL (audit Opus 5 §4.6).

Le symptôme : ``HITLManager._pending`` est un dict en mémoire. Un redémarrage
pendant une mission de nuit perd toutes les validations en attente — et la
décision que Franck prend sur son téléphone à 3 h du matin tombe dans le vide
(``resolve()`` rend ``False``, le routeur rend 404).

Ce que cette couche garantit — et ce qu'elle ne garantit PAS :

✅ La demande survit au redémarrage (la cloche de l'UI la montre encore).
✅ La décision prise APRÈS le redémarrage est **enregistrée**, jamais perdue.
✅ Un timeout est tracé comme tel, distinct d'un refus délibéré (cf. #150).
❌ La coroutine qui attendait est morte avec le processus : cette PR ne
   ressuscite pas la mission interrompue. C'est de la reprise d'exécution,
   pas de la persistance — hors périmètre V0.

Run with:  cd backend && python -m pytest tests/test_hitl_persistence.py -v
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.user import User


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


@pytest.fixture
def restarted_backend():
    """Simule un redémarrage : le singleton repart avec une mémoire vide, et
    il est RESTAURÉ ensuite — sinon la fuite contaminerait la suite."""
    from app.services import hitl_manager as hm
    original = hm._hitl_manager
    hm._hitl_manager = hm.HITLManager()
    try:
        yield hm._hitl_manager
    finally:
        hm._hitl_manager = original


async def _make_user() -> str:
    from app.database import async_session
    async with async_session() as db:
        u = User(
            id=str(uuid.uuid4()), username=f"u_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
        )
        db.add(u)
        await db.commit()
        return u.id


# ------------------------------------------------------- le test du lot

@pytest.mark.asyncio
async def test_decision_taken_after_a_restart_is_not_lost():
    """LE test : le backend redémarre pendant l'attente, Franck valide depuis
    Telegram, et sa décision est enregistrée au lieu de tomber dans le vide."""
    from app.services.hitl_manager import (
        HITLManager, get_recorded_decision, persist_request,
    )

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await persist_request(action_id, user_id, "Envoyer le mail à Gert")

    # ── redémarrage : un manager tout neuf, mémoire vide ──
    restarted = HITLManager()
    assert restarted._pending == {}

    assert await restarted.resolve(action_id, "allow") is True, (
        "la décision prise après un redémarrage est perdue"
    )
    assert await get_recorded_decision(action_id) == ("allow", None)


@pytest.mark.asyncio
async def test_pending_request_survives_a_restart():
    """La cloche de l'UI montre encore la demande après le redémarrage."""
    from app.services.hitl_manager import HITLManager, persist_request

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await persist_request(action_id, user_id, "Supprimer le dossier archive")

    restarted = HITLManager()
    items = await restarted.list_pending(user_id)

    assert [i["action_id"] for i in items] == [action_id]
    assert items[0]["description"] == "Supprimer le dossier archive"


@pytest.mark.asyncio
async def test_pending_of_another_user_is_never_exposed():
    """Cloisonnement : la cloche d'un utilisateur n'affiche pas les demandes
    d'un autre (3 utilisateurs en prod)."""
    from app.services.hitl_manager import HITLManager, persist_request

    mine, theirs = await _make_user(), await _make_user()
    await persist_request(uuid.uuid4().hex[:8], theirs, "Action d'un tiers")

    assert await HITLManager().list_pending(mine) == []


@pytest.mark.asyncio
async def test_resolved_request_disappears_from_the_pending_list():
    from app.services.hitl_manager import HITLManager, persist_request

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await persist_request(action_id, user_id, "Action tranchée")

    mgr = HITLManager()
    await mgr.resolve(action_id, "deny", "pas maintenant")

    assert await mgr.list_pending(user_id) == []


@pytest.mark.asyncio
async def test_a_decision_cannot_be_overwritten():
    """Pas de double validation : une action tranchée reste tranchée."""
    from app.services.hitl_manager import (
        HITLManager, get_recorded_decision, persist_request,
    )

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await persist_request(action_id, user_id, "Virement")

    mgr = HITLManager()
    assert await mgr.resolve(action_id, "deny") is True
    assert await mgr.resolve(action_id, "allow") is False, (
        "une action déjà refusée ne doit pas pouvoir être ré-autorisée"
    )
    assert (await get_recorded_decision(action_id))[0] == "deny"


@pytest.mark.asyncio
async def test_unknown_action_is_still_rejected():
    """Aucune acceptation fantôme : un action_id jamais créé reste inconnu."""
    from app.services.hitl_manager import HITLManager

    assert await HITLManager().resolve("deadbeef", "allow") is False


@pytest.mark.asyncio
async def test_expired_request_is_not_listed_after_a_restart():
    """Une demande périmée pendant l'arrêt n'est pas ressuscitée."""
    from app.database import async_session
    from app.models.hitl_request import HitlRequest
    from app.services.hitl_manager import HITLManager, persist_request

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await persist_request(action_id, user_id, "Demande périmée")

    async with async_session() as db:
        row = (await db.execute(
            select(HitlRequest).where(HitlRequest.action_id == action_id)
        )).scalar_one()
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        await db.commit()

    assert await HITLManager().list_pending(user_id) == []


# ------------------------------------------- le chemin nominal (process vivant)

@pytest.mark.asyncio
async def test_live_request_is_persisted_and_resolved_end_to_end():
    """Processus vivant : la demande est écrite en base dès sa création, et la
    décision y est reportée — sans changer le comportement historique."""
    from app.database import async_session
    from app.models.hitl_request import HitlRequest
    from app.services.hitl_manager import HITLManager

    user_id = await _make_user()
    mgr = HITLManager()

    waiter = asyncio.create_task(
        mgr.request_validation("Envoyer un mail", user_id, channel="web")
    )
    # laisser request_validation écrire sa ligne et se mettre en attente
    for _ in range(100):
        await asyncio.sleep(0.01)
        if mgr._pending:
            break
    assert mgr._pending, "la demande n'a jamais été enregistrée en mémoire"
    action_id = next(iter(mgr._pending))

    async with async_session() as db:
        row = (await db.execute(
            select(HitlRequest).where(HitlRequest.action_id == action_id)
        )).scalar_one_or_none()
    assert row is not None, "la demande n'est pas persistée à la création"
    assert row.status == "pending"

    assert await mgr.resolve(action_id, "allow", "ok") is True
    decision, reason = await asyncio.wait_for(waiter, timeout=5)
    assert (decision, reason) == ("allow", "ok")

    async with async_session() as db:
        row = (await db.execute(
            select(HitlRequest).where(HitlRequest.action_id == action_id)
        )).scalar_one()
    assert row.status == "allow"
    assert row.resolved_at is not None


# ------------------------------------------------- le chemin réellement cliqué

@pytest.mark.asyncio
async def test_web_ui_can_still_approve_after_a_restart(restarted_backend):
    """Le routeur lisait ``hitl._pending`` en direct : après un redémarrage il
    rendait 404 avant même d'appeler resolve(). Le bouton « Autoriser » de
    l'UI doit continuer de fonctionner."""
    from app.routers.validation import _resolve
    from app.services import hitl_manager as hm

    user_id = await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await hm.persist_request(action_id, user_id, "Envoyer le devis")

    user = type("U", (), {"id": user_id})()

    out = await _resolve(action_id, "allow", None, user)

    assert out == {"status": "ok", "decision": "allow"}
    assert await hm.get_recorded_decision(action_id) == ("allow", None)


@pytest.mark.asyncio
async def test_another_user_cannot_approve_after_a_restart(restarted_backend):
    """Le contrôle d'appartenance ne doit pas être perdu en route : il
    s'appuie désormais sur la base, mais il reste entier."""
    from fastapi import HTTPException

    from app.routers.validation import _resolve
    from app.services import hitl_manager as hm

    owner, intruder = await _make_user(), await _make_user()
    action_id = uuid.uuid4().hex[:8]
    await hm.persist_request(action_id, owner, "Virement sensible")

    user = type("U", (), {"id": intruder})()

    with pytest.raises(HTTPException) as exc:
        await _resolve(action_id, "allow", None, user)
    assert exc.value.status_code == 403
    assert await hm.get_recorded_decision(action_id) is None


@pytest.mark.asyncio
async def test_timeout_is_recorded_as_timeout_not_as_a_deliberate_refusal(monkeypatch):
    """#150 : un silence n'est pas un refus. La base doit garder la nuance."""
    from app.database import async_session
    from app.models.hitl_request import HitlRequest
    from app.services import hitl_manager as hm

    monkeypatch.setattr(hm, "_timeout_seconds", lambda: 0.05)
    user_id = await _make_user()
    mgr = hm.HITLManager()

    decision, reason = await mgr.request_validation("Action ignorée", user_id)

    assert (decision, reason) == ("deny", "timeout")
    async with async_session() as db:
        row = (await db.execute(
            select(HitlRequest).where(HitlRequest.user_id == user_id)
        )).scalar_one()
    assert row.status == "deny"
    assert row.reason == "timeout", "le timeout doit rester distinguable d'un refus"
