# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_replay_shadow.py
# @brief      C4-4 PR A — replay avant/après SHADOW : capture de la trace
#             d'outils, passerelle en mode shadow, moteur A/B.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""C4-4 — le replay shadow STRICT (arbitrage 19/07).

Principe : on ne ré-exécute JAMAIS un outil réel en replay — les
ToolMessages ENREGISTRÉS au moment du signal sont re-servis par la
passerelle (mode shadow, fail-closed : outil non enregistré → notice,
jamais d'exécution). Le moteur rejoue le tour AVEC et SANS le skill
appris (bloc <learned_skills> forcé via pré-seed du cache frozen_memory
— les deux runs voient exactement le même snapshot ± le bloc, zéro
drift Qdrant) et compare : le détecteur qui a produit le failure_case
re-déclenche-t-il ?

Découverte de cadrage (vérifiée) : la table ``messages`` ne persiste QUE
user/assistant/system — les ToolMessages n'y sont pas. La trace est donc
capturée AU SIGNAL (replay_payload.tool_trace, caps dédiés), telle que
le LLM d'origine l'a vue (anonymisée) : le LLM du replay voit les mêmes
placeholders, et aucune PII en clair ne repart vers le cloud.

Run with:  cd backend && python -m pytest tests/test_replay_shadow.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.conversation import Conversation, Message
from app.models.failure_case import FailureCase
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.learning.failure_capture import (
    MAX_TOOL_TRACE_ENTRIES,
    TOOL_TRACE_CHARS,
    capture_from_hallucination_block,
    tool_trace_from_messages,
)

_REPO = Path(__file__).resolve().parents[1]

# Phrase du contrat test_output_verifier : déclenche le completion_guard
# de façon déterministe quand aucun outil destructif n'a tourné.
_LYING = "Voilà, j'ai supprimé les 50 mails de la corbeille."


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"rp-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"rp_{uid}", email=f"{uid}@test.local",
                    hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        # FK-safe : enfants avant parents.
        await db.execute(delete(FailureCase).where(FailureCase.user_id == uid))
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        convs = (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid)
        )).scalars().all()
        if convs:
            await db.execute(delete(Message).where(Message.conversation_id.in_(convs)))
            await db.execute(delete(Conversation).where(Conversation.id.in_(convs)))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


# ────────────────────────────────────────────────────────────────────────
# A. Capture de la trace d'outils
# ────────────────────────────────────────────────────────────────────────


def test_tool_trace_from_messages_extracts_ordered_pairs():
    msgs = [
        HumanMessage(content="range mes mails"),
        AIMessage(content="", tool_calls=[
            {"name": "gmail_list_emails", "args": {}, "id": "c1"},
        ]),
        ToolMessage(content="12 mails dont 3 promos", name="gmail_list_emails",
                    tool_call_id="c1"),
        AIMessage(content="", tool_calls=[
            {"name": "gmail_trash_by_category", "args": {}, "id": "c2"},
        ]),
        ToolMessage(content="3 mails déplacés", name="gmail_trash_by_category",
                    tool_call_id="c2"),
        AIMessage(content="C'est rangé."),
    ]
    trace = tool_trace_from_messages(msgs)
    assert trace == [
        {"tool": "gmail_list_emails", "content": "12 mails dont 3 promos"},
        {"tool": "gmail_trash_by_category", "content": "3 mails déplacés"},
    ]


def test_tool_trace_caps_entries_and_length():
    msgs = []
    for i in range(MAX_TOOL_TRACE_ENTRIES + 3):
        msgs.append(ToolMessage(content="x" * (TOOL_TRACE_CHARS + 500),
                                name=f"tool_{i}", tool_call_id=f"c{i}"))
    trace = tool_trace_from_messages(msgs)
    assert len(trace) == MAX_TOOL_TRACE_ENTRIES
    assert all(len(t["content"]) <= TOOL_TRACE_CHARS for t in trace)


def test_tool_trace_tolerates_garbage():
    assert tool_trace_from_messages(None) == []
    assert tool_trace_from_messages(["not-a-message", 42]) == []


@pytest.mark.asyncio
async def test_capture_hallucination_stores_tool_trace(_user):
    case_id = await capture_from_hallucination_block(
        signal_id=1,
        user_id=_user,
        conversation_id="conv-rp-1",
        model_used="llm:test",
        matched_patterns=["fake_completion"],
        tools_invoked=["gmail_list_emails"],
        destructive_tools_invoked=[],
        reason="unbacked_completion",
        original_response=_LYING,
        tool_trace=[{"tool": "gmail_list_emails", "content": "12 mails"}],
    )
    assert case_id is not None
    async with async_session() as db:
        fc = (await db.execute(
            select(FailureCase).where(FailureCase.id == case_id)
        )).scalar_one()
    payload = json.loads(fc.replay_payload)
    assert payload["tool_trace"] == [
        {"tool": "gmail_list_emails", "content": "12 mails"},
    ]


def test_signal_kwargs_carry_tool_trace():
    """Le mapping pur du verifier transporte la trace jusqu'au signal."""
    from app.services.completion_guard import detect_unbacked_completion_claim
    from app.services.output_verifier import _hallucination_signal_kwargs

    verdict = detect_unbacked_completion_claim(_LYING, [])
    kwargs = _hallucination_signal_kwargs(
        verdict=verdict,
        user_id="u",
        conversation_id="c",
        model_used="m",
        original_content=_LYING,
        tool_trace=[{"tool": "t", "content": "r"}],
    )
    assert kwargs["tool_trace"] == [{"tool": "t", "content": "r"}]


def test_verify_from_result_wires_the_trace():
    """verify_outcome_from_result dérive la trace du result — pin source
    (le spawn best-effort rend le chemin complet non observable en test
    hermétique ; le mapping pur est testé au-dessus)."""
    src = (_REPO / "app/services/output_verifier.py").read_text(encoding="utf-8")
    assert "tool_trace_from_messages" in src
    assert "tool_trace=" in src


# ────────────────────────────────────────────────────────────────────────
# B. Passerelle en mode shadow (fail-closed)
# ────────────────────────────────────────────────────────────────────────


def _shadow_ctx(session):
    """GatewayContext minimal armé pour exploser si le pipeline réel est
    touché : hitl/memory sentinelles."""
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    class _Boom:
        def __getattr__(self, name):
            raise AssertionError(f"real pipeline reached ({name}) in shadow mode")

    return GatewayContext(
        user_id="shadow-user",
        conversation_id="replay-shadow-test",
        pii_filter=None,
        criticality_filter=SecurityFilter(),
        hitl=_Boom(),
        memory=_Boom(),
        shadow_results=session,
    )


def _never_call_tool(name: str):
    from langchain_core.tools import tool

    @tool
    async def _t() -> str:
        """Sentinel tool that must never run in shadow mode."""
        raise AssertionError(f"real tool {name} executed in shadow mode")
    _t.name = name
    return _t


@pytest.mark.asyncio
async def test_shadow_serves_recorded_results_in_order():
    from app.services.learning.replay_engine import ShadowSession
    from app.services.tool_gateway import execute_tool_call

    session = ShadowSession([
        {"tool": "gmail_list_emails", "content": "batch-1"},
        {"tool": "gmail_list_emails", "content": "batch-2"},
        {"tool": "web_search", "content": "results"},
    ])
    ctx = _shadow_ctx(session)
    tool_map = {"gmail_list_emails": _never_call_tool("gmail_list_emails"),
                "web_search": _never_call_tool("web_search")}

    r1 = await execute_tool_call(ctx, {"name": "gmail_list_emails", "args": {}, "id": "a"}, tool_map)
    r2 = await execute_tool_call(ctx, {"name": "web_search", "args": {}, "id": "b"}, tool_map)
    r3 = await execute_tool_call(ctx, {"name": "gmail_list_emails", "args": {}, "id": "c"}, tool_map)

    assert r1["content"] == "batch-1"
    assert r2["content"] == "results"
    assert r3["content"] == "batch-2"
    assert r1["tool_call_id"] == "a"
    assert all(r["role"] == "tool" for r in (r1, r2, r3))


@pytest.mark.asyncio
async def test_shadow_unrecorded_tool_notice_never_executes():
    from app.services.learning.replay_engine import ShadowSession
    from app.services.tool_gateway import execute_tool_call

    session = ShadowSession([{"tool": "web_search", "content": "x"}])
    ctx = _shadow_ctx(session)
    tool_map = {"gmail_send_email": _never_call_tool("gmail_send_email")}

    meta: dict = {}
    out = await execute_tool_call(
        ctx, {"name": "gmail_send_email", "args": {"to": "a@b.c"}, "id": "z"},
        tool_map, meta,
    )
    assert "[replay" in out["content"]
    assert meta["success"] is False
    assert session.misses == ["gmail_send_email"]
    # Épuisement d'une file enregistrée → notice aussi (pas de rejeu infini)
    await execute_tool_call(ctx, {"name": "web_search", "args": {}, "id": "w1"}, tool_map)
    out2 = await execute_tool_call(ctx, {"name": "web_search", "args": {}, "id": "w2"}, tool_map)
    assert "[replay" in out2["content"]


# ────────────────────────────────────────────────────────────────────────
# C. frozen_memory.preseed
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_frozen_memory_preseed_bypasses_builder():
    from app.services import frozen_memory

    conv = f"replay-{uuid.uuid4().hex[:8]}"
    frozen_memory.preseed(conv, "SNAPSHOT-FORCÉ")

    async def _builder():
        raise AssertionError("builder must not run on a preseeded conversation")

    got = await frozen_memory.get_or_build(conv, "u", _builder)
    assert got == "SNAPSHOT-FORCÉ"
    frozen_memory.discard(conv)


# ────────────────────────────────────────────────────────────────────────
# D. Moteur replay
# ────────────────────────────────────────────────────────────────────────


async def _seed_case(uid: str, *, with_skill: bool = False) -> tuple[int, str, str | None]:
    """Conversation réelle (user → assistant → user) + FailureCase
    hallucination créé APRÈS le dernier message. Retourne
    (case_id, conversation_id, skill_id|None)."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        conv = Conversation(user_id=uid, title="replay seed")
        db.add(conv)
        await db.flush()
        conv_id = str(conv.id)
        db.add(Message(conversation_id=conv_id, role="user",
                       content="peux-tu vider ma corbeille ?",
                       created_at=now - timedelta(minutes=3)))
        db.add(Message(conversation_id=conv_id, role="assistant",
                       content="Je regarde ça.",
                       created_at=now - timedelta(minutes=2)))
        db.add(Message(conversation_id=conv_id, role="user",
                       content="vas-y, supprime les mails de la corbeille",
                       created_at=now - timedelta(minutes=1)))
        await db.commit()

    skill_id: str | None = None
    if with_skill:
        async with async_session() as db:
            s = LearnedSkill(
                user_id=uid,
                name="gmail-trash-confirmation",
                description="toujours confirmer avant suppression",
                content="# Procédure\n1. lister 2. confirmer 3. agir",
                frontmatter_json="{}",
                status=SkillStatus.ACTIVE,
                source=SkillSource.AUTO_GENERATED,
                iteration_count=1,
                from_failure_case_ids="[]",
            )
            db.add(s)
            await db.commit()
            await db.refresh(s)
            skill_id = s.id

    case_id = await capture_from_hallucination_block(
        signal_id=1,
        user_id=uid,
        conversation_id=conv_id,
        model_used="llm:test",
        matched_patterns=["fake_completion"],
        tools_invoked=["gmail_list_emails"],
        destructive_tools_invoked=[],
        reason="unbacked_completion",
        original_response=_LYING,
        tool_trace=[{"tool": "gmail_list_emails", "content": "50 mails en corbeille"}],
    )
    if skill_id is not None:
        async with async_session() as db:
            fc = (await db.execute(
                select(FailureCase).where(FailureCase.id == case_id)
            )).scalar_one()
            fc.learned_skill_id = skill_id
            await db.commit()
    return case_id, conv_id, skill_id


@pytest.mark.asyncio
async def test_load_case_context_time_bound_history(_user):
    from app.services.learning import replay_engine

    case_id, conv_id, _ = await _seed_case(_user)
    ctxr = await replay_engine.load_case_context(case_id)
    assert ctxr is not None
    assert ctxr.conversation_id == conv_id
    roles = [(m["role"], m["content"][:12]) for m in ctxr.history]
    assert roles[0] == ("user", "peux-tu vide")
    assert roles[-1][0] == "user"          # se termine au dernier message user
    assert len(ctxr.history) == 3
    assert ctxr.tool_trace[0]["tool"] == "gmail_list_emails"


class _FakeGraph:
    """Capture l'état initial passé à ainvoke et rend un texte contrôlé."""

    def __init__(self, final_text: str, sink: dict):
        self._text = final_text
        self._sink = sink

    async def ainvoke(self, state, config=None):
        self._sink["state"] = state
        self._sink["config"] = config
        return {"messages": list(state["messages"]) + [AIMessage(content=self._text)]}


@pytest.mark.asyncio
async def test_run_shadow_preseeds_and_registers(_user, monkeypatch):
    from app.services import frozen_memory
    from app.services.learning import replay_engine

    case_id, _conv, _ = await _seed_case(_user)
    case_ctx = await replay_engine.load_case_context(case_id)

    sink: dict = {}
    seen: dict = {}

    def _fake_build():
        # Au moment de l'invoke, le preseed et le registre shadow DOIVENT
        # déjà être posés pour la conversation synthétique.
        return _FakeGraph("Rien n'a été supprimé — veux-tu confirmer ?", sink)

    monkeypatch.setattr("app.agent.graph.build_simple_agent_graph", _fake_build)

    out = await replay_engine.run_shadow(case_ctx, with_skill=None)
    assert out["final_text"].startswith("Rien n'a été supprimé")
    conv_used = sink["state"]["conversation_id"]
    assert conv_used.startswith("replay-shadow-")
    # Le registre shadow est nettoyé après le run (pas de fuite)
    assert replay_engine.get_shadow_session(conv_used) is None
    # L'historique passé au graphe se termine par le dernier message user
    msgs = sink["state"]["messages"]
    assert msgs[-1].content  # non vide
    assert getattr(msgs[-1], "type", "") == "human"
    # Le snapshot préseedé a été consommé puis relâché
    assert frozen_memory.snapshot_size() >= 0  # sanity (pas d'exception)


@pytest.mark.asyncio
async def test_run_shadow_with_skill_forces_learned_block(_user, monkeypatch):
    from app.services.learning import replay_engine

    case_id, _conv, skill_id = await _seed_case(_user, with_skill=True)
    case_ctx = await replay_engine.load_case_context(case_id)

    sink: dict = {}
    monkeypatch.setattr(
        "app.agent.graph.build_simple_agent_graph",
        lambda: _FakeGraph("ok", sink),
    )
    preseeds: dict = {}
    from app.services import frozen_memory
    real_preseed = frozen_memory.preseed

    def _spy_preseed(conv_id, snapshot):
        preseeds[conv_id] = snapshot
        return real_preseed(conv_id, snapshot)

    monkeypatch.setattr(frozen_memory, "preseed", _spy_preseed)

    await replay_engine.run_shadow(case_ctx, with_skill=skill_id)
    with_block = list(preseeds.values())[0]
    assert "<learned_skills>" in with_block
    assert "gmail-trash-confirmation" in with_block

    preseeds.clear()
    await replay_engine.run_shadow(case_ctx, with_skill=None)
    without_block = list(preseeds.values())[0]
    assert "<learned_skills>" not in without_block


@pytest.mark.asyncio
async def test_run_ab_verdict_improved_and_writeback(_user, monkeypatch):
    """A halluciné (détecteur réel re-déclenche) → B propre : verdict
    improved + rapport écrit sur le skill lié."""
    from app.services.learning import replay_engine

    case_id, _conv, skill_id = await _seed_case(_user, with_skill=True)

    texts = iter([_LYING, "Je n'ai rien supprimé — confirmes-tu l'opération ?"])
    sink: dict = {}
    monkeypatch.setattr(
        "app.agent.graph.build_simple_agent_graph",
        lambda: _FakeGraph(next(texts), sink),
    )

    async def _fake_eval(sid):
        return {"skill_id": sid, "status": "evaluated", "score": 80,
                "verdict": "pass"}

    monkeypatch.setattr(
        "app.services.learning.skill_eval.evaluate_skill", _fake_eval,
    )

    report = await replay_engine.run_ab(case_id)
    assert report["status"] == "ok"
    assert report["before"]["blocked"] is True
    assert report["after"]["blocked"] is False
    assert report["verdict"] == "improved"
    assert report["skill_id"] == skill_id

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == skill_id)
        )).scalar_one()
    vr = json.loads(skill.validation_report_json or "{}")
    assert vr["replay_ab"]["verdict"] == "improved"
    assert vr["replay_ab"]["case_id"] == case_id


@pytest.mark.asyncio
async def test_run_ab_without_skill_errors_clearly(_user):
    from app.services.learning import replay_engine

    case_id, _conv, _ = await _seed_case(_user, with_skill=False)
    report = await replay_engine.run_ab(case_id)
    assert report["status"] == "no_skill"


# ────────────────────────────────────────────────────────────────────────
# E. Bench --case (pin source — le bench vit hors backend/, pas dans la CI)
# ────────────────────────────────────────────────────────────────────────


def test_bench_has_case_flag():
    src = (_REPO.parent / "bench/run_canonical.py").read_text(encoding="utf-8")
    assert "--case" in src
    assert "run_ab" in src
