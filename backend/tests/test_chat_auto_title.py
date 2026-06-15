# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_chat_auto_title.py
# @brief      Jalon 4 — titre de conversation généré par LLM (vs user_content[:50])
# @license    Elastic License 2.0
# =============================================================================
"""Tests for the LLM-generated conversation title (J4)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.conversation import Conversation, Message


# ── _clean_title (pure) ──────────────────────────────────────────────────────

def test_clean_title():
    from app.routers.chat import _clean_title
    assert _clean_title('"Réunion budget Q3"') == "Réunion budget Q3"
    assert _clean_title("Titre : Plan de prospection") == "Plan de prospection"
    assert _clean_title("Title: Email triage") == "Email triage"
    assert _clean_title("Résumé des emails.") == "Résumé des emails"
    assert _clean_title("Ligne1\nLigne2") == "Ligne1"
    assert _clean_title("a b c d e f g h i j k l") == "a b c d e f g h i j"
    assert _clean_title("") == ""
    assert _clean_title("  `**Veille concurrent**`  ") == "Veille concurrent"


# ── _maybe_generate_title (DB + mocked LLM) ──────────────────────────────────

class _FakeLLM:
    def __init__(self, content):
        self._c = content

    async def ainvoke(self, _msgs):
        return SimpleNamespace(content=self._c)


@pytest_asyncio.fixture
async def _conv():
    await init_db()
    from app.models.user import User
    uid = "t_" + uuid.uuid4().hex[:8]
    cid = uuid.uuid4().hex
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    async with async_session() as db:
        db.add(Conversation(id=cid, user_id=uid, title="bonjour je voudrais trier mes"))
        await db.flush()
        db.add(Message(conversation_id=cid, role="user", content="Aide-moi à trier mes mails"))
        db.add(Message(conversation_id=cid, role="assistant", content="Voici comment trier…"))
        await db.commit()
    yield uid, cid
    async with async_session() as db:
        await db.execute(delete(Message).where(Message.conversation_id == cid))
        await db.execute(delete(Conversation).where(Conversation.id == cid))
        await db.commit()


async def _title_of(cid):
    async with async_session() as db:
        return (await db.execute(
            select(Conversation.title).where(Conversation.id == cid)
        )).scalar_one()


@pytest.mark.asyncio
async def test_title_set_on_first_exchange(_conv, monkeypatch):
    uid, cid = _conv
    import app.services.llm_provider as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm_for_tier",
                        lambda tier: _FakeLLM('"Tri des emails entrants"'))
    from app.routers.chat import _maybe_generate_title
    await _maybe_generate_title(cid, uid, "Aide-moi à trier mes mails", "Voici…")
    assert await _title_of(cid) == "Tri des emails entrants"


@pytest.mark.asyncio
async def test_title_skips_after_first_exchange(_conv, monkeypatch):
    uid, cid = _conv
    # A second assistant reply → no longer the first exchange.
    async with async_session() as db:
        db.add(Message(conversation_id=cid, role="user", content="et ensuite ?"))
        db.add(Message(conversation_id=cid, role="assistant", content="ensuite…"))
        await db.commit()

    import app.services.llm_provider as llm_mod
    called = {"n": 0}

    def _fake_get(tier):
        called["n"] += 1
        return _FakeLLM("NE DOIT PAS APPARAÎTRE")

    monkeypatch.setattr(llm_mod, "get_llm_for_tier", _fake_get)
    from app.routers.chat import _maybe_generate_title
    await _maybe_generate_title(cid, uid, "x", "y")
    assert called["n"] == 0                                  # no LLM call
    assert await _title_of(cid) == "bonjour je voudrais trier mes"  # unchanged


@pytest.mark.asyncio
async def test_title_blank_llm_keeps_old(_conv, monkeypatch):
    uid, cid = _conv
    import app.services.llm_provider as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm_for_tier", lambda tier: _FakeLLM("   "))
    from app.routers.chat import _maybe_generate_title
    await _maybe_generate_title(cid, uid, "x", "y")
    assert await _title_of(cid) == "bonjour je voudrais trier mes"  # unchanged
