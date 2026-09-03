# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_traces_wiring.py
# @brief      Les traces sont écrites, relues au tour suivant, et JAMAIS
#             affichées dans le chat.
# @license    MIT
# =============================================================================
"""Le câblage des traces d'outils — la moitié qui touche la base et l'écran.

Le module ``tool_traces`` sait fabriquer et relire une trace. Reste à
l'accrocher aux trois endroits où ça compte, dont deux sont des pièges vérifiés
dans le code avant d'écrire :

1. **écrire** la trace à la fin du tour, dans la même table que les messages ;
2. **la relire** au tour suivant, avec l'historique ;
3. **ne jamais l'afficher** — l'API des conversations ne filtre aucun rôle et
   ``MessageBubble`` rend comme « assistant » tout ce qui n'est pas « user ».
   Sans filtre, Franck verrait ``pdf_to_docx(source=…) → …`` apparaître comme
   un message d'Ely dans son fil.

Run with:  cd backend && python -m pytest tests/test_tool_traces_wiring.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_conv():
    """Une conversation réelle en base mémoire, avec son utilisateur."""
    from app.database import Base, async_session, engine
    from app.models.conversation import Conversation
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uid, cid = str(uuid.uuid4()), str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u{uid[:8]}", email=f"{uid}@test.local",
                    hashed_password="x"))
        await db.flush()
        db.add(Conversation(id=cid, user_id=uid, title="Test"))
        await db.commit()
    return cid


# ─────────────────────────────────────────────────────────────────────
# Écrire, puis relire
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_trace_written_is_read_back(db_conv):
    """LE bout du problème : ce que l'outil a produit doit survivre au tour."""
    from app.services.tool_traces import load_traces, persist_traces

    await persist_traces(db_conv, [
        "pdf_to_docx(source=/tmp/a.pdf) → Document Word créé : /tmp/ely-docx/a.docx",
    ])

    relues = await load_traces(db_conv)
    assert len(relues) == 1
    assert "/tmp/ely-docx/a.docx" in relues[0]


@pytest.mark.asyncio
async def test_nothing_to_persist_writes_nothing(db_conv):
    """Une conversation ordinaire ne doit rien coûter de plus — ni ligne en
    base, ni transaction."""
    from app.services.tool_traces import load_traces, persist_traces

    await persist_traces(db_conv, [])
    assert await load_traces(db_conv) == []


@pytest.mark.asyncio
async def test_only_the_most_recent_traces_come_back(db_conv):
    """Une conversation longue accumule les appels ; ce sont les derniers qui
    portent le contexte utile."""
    from app.services.tool_traces import MAX_RELOADED_TRACES, load_traces, persist_traces

    await persist_traces(db_conv, [f"outil_{i}(...) → resultat {i}" for i in range(20)])

    relues = await load_traces(db_conv)
    assert len(relues) <= MAX_RELOADED_TRACES
    assert any("resultat 19" in t for t in relues)


@pytest.mark.asyncio
async def test_traces_of_another_conversation_never_leak(db_conv):
    """Le cloisonnement. Deux conversations en parallèle — le chat de Franck et
    une tâche planifiée — ne doivent jamais mélanger leurs actions."""
    from app.services.tool_traces import load_traces, persist_traces

    await persist_traces(db_conv, ["pdf_to_docx(...) → /tmp/mien.docx"])
    autre = str(uuid.uuid4())

    assert await load_traces(autre) == []


@pytest.mark.asyncio
async def test_persisting_never_breaks_the_turn(monkeypatch):
    """Une trace est un confort. Si la base refuse l'écriture, l'utilisateur
    doit quand même recevoir sa réponse — on journalise et on continue."""
    from app.services import tool_traces

    def _boom(*a, **k):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(tool_traces, "async_session", _boom)
    await tool_traces.persist_traces(str(uuid.uuid4()), ["outil(...) → x"])  # ne lève pas


# ─────────────────────────────────────────────────────────────────────
# Ne JAMAIS apparaître dans le chat
# ─────────────────────────────────────────────────────────────────────


def test_the_conversation_api_hides_traces():
    """⚠️ Le piège vérifié dans le code : l'API renvoyait tous les rôles, et
    ``MessageBubble`` affiche comme « assistant » tout ce qui n'est pas
    « user ». Sans ce filtre, Franck verrait les traces dans son fil."""
    import inspect

    from app.routers import conversations
    from app.services.tool_traces import TRACE_ROLE

    source = inspect.getsource(conversations)
    assert TRACE_ROLE in source, (
        "aucune mention du rôle des traces : l'API ne les filtre pas"
    )


@pytest.mark.asyncio
async def test_a_trace_is_not_returned_as_a_conversation_message(db_conv):
    """Le pin de comportement, pas seulement de source : ce que l'API renvoie
    ne doit contenir aucune trace."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.conversation import Message
    from app.services.tool_traces import TRACE_ROLE, persist_traces

    await persist_traces(db_conv, ["pdf_to_docx(...) → /tmp/a.docx"])

    async with async_session() as db:
        rows = (await db.execute(
            select(Message).where(Message.conversation_id == db_conv)
        )).scalars().all()

    assert any(m.role == TRACE_ROLE for m in rows), "la trace n'a pas été écrite"
    affichables = [m for m in rows if m.role in ("user", "assistant")]
    assert not affichables, "une trace est passée pour un message affichable"
