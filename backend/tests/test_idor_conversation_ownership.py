# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_idor_conversation_ownership.py
# @brief      Revue multi-utilisateurs 2026-06-10, constats A-1 + A-2 —
#             un user B authentifié qui rejoue le conversation_id d'un
#             user A doit être rejeté sur les deux chemins :
#             WS /chat (close 4003) et POST /api/me/state/recompute (404).
# @license    MIT
# =============================================================================
"""IDOR regression tests — conversation ownership enforcement.

Constat A-1 : le handler WebSocket ``/chat`` acceptait n'importe quel
``conversation_id`` client (``msg.get("conversation_id") or
conversation_id``) sans vérifier qu'il appartient à l'utilisateur
authentifié → tout utilisateur connecté pouvait écrire dans (et faire
lire à l'agent) la conversation d'un autre en rejouant son UUID.

Constat A-2 : ``POST /api/me/state/recompute`` passait le query param
``conversation_id`` tel quel à ``compute_user_state``, dont
``_load_recent_messages`` lit les messages SANS filtre user →
exfiltration du contenu d'une conversation étrangère via le user-state.

Les deux fixes renvoient la même réponse pour « introuvable » et
« appartient à quelqu'un d'autre » (pas d'oracle d'existence), en
miroir de ``conversations._get_owned_conversation`` qui renvoie 404.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# Fixtures / helpers — user A + user B + une conversation privée de A
# ─────────────────────────────────────────────────────────────────────────


def _fake_user(uid: str):
    """Stand-in minimal pour `User` quand le handler n'utilise que `.id`
    (même pattern que tests/test_user_state_endpoint.py)."""
    class _U:
        id = uid
    return _U()


async def _setup_two_users_one_conv() -> tuple[str, str, str]:
    """Crée user A, user B, et une conversation de A contenant un
    message — le contenu sert de témoin : rien ne doit s'y ajouter ni en
    sortir quand B rejoue l'UUID."""
    from app.database import async_session, init_db
    from app.models.conversation import Conversation, Message
    from app.models.user import User

    await init_db()
    uid_a = f"test_idor_a_{uuid.uuid4().hex[:8]}"
    uid_b = f"test_idor_b_{uuid.uuid4().hex[:8]}"
    # Users d'abord (commit séparé) — SQLite vérifie les FK immédiatement
    # et l'ordre d'insertion intra-flush n'est pas garanti sans relationship.
    async with async_session() as db:
        for uid in (uid_a, uid_b):
            db.add(User(
                id=uid,
                username=f"u_{uid[-8:]}",
                email=f"{uid}@bench.local",
                hashed_password="x",
            ))
        await db.commit()
    async with async_session() as db:
        conv = Conversation(user_id=uid_a, title="conv privée de A")
        db.add(conv)
        await db.flush()
        conv_id = str(conv.id)
        db.add(Message(
            conversation_id=conv_id, role="user", content="secret de A",
        ))
        await db.commit()
    return uid_a, uid_b, conv_id


async def _teardown_users(uid_a: str, uid_b: str) -> None:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.conversation import Conversation, Message
    from app.models.user import User
    from app.models.user_state import UserState

    async with async_session() as db:
        for uid in (uid_a, uid_b):
            for conv in (await db.execute(
                select(Conversation).where(Conversation.user_id == uid)
            )).scalars():
                for m in (await db.execute(
                    select(Message).where(Message.conversation_id == str(conv.id))
                )).scalars():
                    await db.delete(m)
                await db.delete(conv)
            for st in (await db.execute(
                select(UserState).where(UserState.user_id == uid)
            )).scalars():
                await db.delete(st)
            u = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
        await db.commit()


async def _count_messages(conv_id: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.conversation import Message

    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conv_id
            )
        )).scalar_one()


@pytest_asyncio.fixture
async def two_users_one_conv():
    uid_a, uid_b, conv_id = await _setup_two_users_one_conv()
    yield uid_a, uid_b, conv_id
    await _teardown_users(uid_a, uid_b)


# ─────────────────────────────────────────────────────────────────────────
# A-1 — WS /chat : helper d'ownership
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assert_owns_conversation_helper(two_users_one_conv) -> None:
    from app.database import async_session
    from app.routers.chat import _assert_owns_conversation

    uid_a, uid_b, conv_a = two_users_one_conv
    async with async_session() as db:
        assert await _assert_owns_conversation(db, conv_a, uid_a) is True
        assert await _assert_owns_conversation(db, conv_a, uid_b) is False
        # Inexistant == étranger : même verdict, pas d'oracle d'existence
        assert await _assert_owns_conversation(db, "no-such-conv", uid_a) is False


# ─────────────────────────────────────────────────────────────────────────
# A-1 — WS /chat : round-trip réel, user B rejoue la conversation de A
# ─────────────────────────────────────────────────────────────────────────


def test_ws_chat_closes_4003_on_foreign_conversation_id() -> None:
    """User B (authentifié, token valide) envoie un message portant le
    conversation_id de user A. Le serveur doit fermer la socket avec le
    code 4003 AVANT de persister quoi que ce soit ou de lancer l'agent —
    on ne doit jamais recevoir l'événement ``start``."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.auth.jwt import create_access_token
    from app.routers import chat as chat_router

    uid_a, uid_b, conv_a = asyncio.run(_setup_two_users_one_conv())
    try:
        app = FastAPI()
        app.include_router(chat_router.router)
        client = TestClient(app)
        token_b = create_access_token({"sub": uid_b})

        with client.websocket_connect("/chat") as ws:
            ws.send_text(json.dumps({"token": token_b}))
            ws.send_text(json.dumps({
                "content": "résume cette conversation",
                "conversation_id": conv_a,
            }))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
        assert exc_info.value.code == 4003

        # Le message de B n'a PAS été écrit dans la conversation de A —
        # seul le message témoin posé par le setup doit s'y trouver.
        assert asyncio.run(_count_messages(conv_a)) == 1
    finally:
        asyncio.run(_teardown_users(uid_a, uid_b))


# ─────────────────────────────────────────────────────────────────────────
# A-2 — POST /api/me/state/recompute : conversation étrangère → 404
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_rejects_foreign_conversation_with_404(
    monkeypatch, two_users_one_conv,
) -> None:
    from fastapi import HTTPException

    from app.routers.user_state import recompute_user_state

    uid_a, uid_b, conv_a = two_users_one_conv

    # Si l'ownership check laissait passer, on veut le savoir : le
    # compute ne doit JAMAIS être atteint avec une conv étrangère.
    async def trip(*_a, **_kw):
        raise AssertionError(
            "compute_user_state ne doit PAS être appelé sur une "
            "conversation appartenant à un autre utilisateur"
        )
    monkeypatch.setattr("app.routers.user_state.compute_user_state", trip)

    with pytest.raises(HTTPException) as exc_info:
        await recompute_user_state(
            conversation_id=conv_a,
            current_user=_fake_user(uid_b),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_recompute_rejects_nonexistent_conversation_with_404(
    two_users_one_conv,
) -> None:
    """Un id inexistant reçoit le même 404 qu'un id étranger — la
    réponse ne doit pas révéler si une conversation existe."""
    from fastapi import HTTPException

    from app.routers.user_state import recompute_user_state

    _uid_a, uid_b, _conv_a = two_users_one_conv
    with pytest.raises(HTTPException) as exc_info:
        await recompute_user_state(
            conversation_id=f"no-such-{uuid.uuid4().hex[:8]}",
            current_user=_fake_user(uid_b),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_recompute_accepts_own_conversation(
    monkeypatch, two_users_one_conv,
) -> None:
    """Contrôle positif — le propriétaire passe toujours : l'ownership
    check ne doit pas casser le chemin légitime."""
    from app.routers.user_state import recompute_user_state

    uid_a, _uid_b, conv_a = two_users_one_conv
    seen: list[str | None] = []

    async def fake_compute(user_id, conversation_id=None, **_kw):
        seen.append(conversation_id)
        from app.services.learning.user_state import get_user_state
        return await get_user_state(user_id)

    monkeypatch.setattr("app.routers.user_state.compute_user_state", fake_compute)

    resp = await recompute_user_state(
        conversation_id=conv_a,
        current_user=_fake_user(uid_a),
    )
    assert resp.status_code == 200
    assert seen == [conv_a]
