# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_find_tool.py
# @brief      find_tool — semantic tool discovery + sticky per-conversation
#             binding (the "tool invisible" safety net).
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.agent import discovered_tools as dt
from app.database import async_session, init_db
from app.skills.builtin import find_tool_skill as fts


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"ft-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"ft_{uid}", email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    yield uid
    from app.models.failure_case import FailureCase
    from app.models.learned_skill import LearnedSkill
    from app.services.background_tasks import drain

    # Le flux « gap consigné » spawne du travail de fond (pré-check +
    # génération d'outil). Sans attendre sa fin, il ré-insère une ligne
    # enfant ENTRE le DELETE des enfants et le DELETE du user → violation de
    # clé étrangère au teardown (reproduit sous SQLite `:memory:`).
    await drain()

    async with async_session() as db:
        await db.execute(delete(FailureCase).where(FailureCase.user_id == uid))
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


# ── per-conversation discovered-tools registry ───────────────────────────────


def test_discovered_registry_add_get_discard():
    conv = f"c-{uuid.uuid4().hex}"
    assert dt.get_discovered(conv) == set()
    dt.add_discovered(conv, ["sheets_read_spreadsheet", "sheets_append_rows"])
    dt.add_discovered(conv, ["sheets_append_rows"])  # idempotent
    assert dt.get_discovered(conv) == {"sheets_read_spreadsheet", "sheets_append_rows"}
    dt.discard_discovered(conv)
    assert dt.get_discovered(conv) == set()


def test_discovered_registry_ignores_empty():
    dt.add_discovered("", ["x"])           # no conv → ignored
    dt.add_discovered("c1", [])            # no names → ignored
    assert dt.get_discovered("c1") == set()


# ── find_tool is registered AND in the default profile (the binding pin) ─────


def test_find_tool_registered_and_in_default_profile():
    from app.agent.toolset_profiles import resolve_profile_tools
    from app.skills.registry import get_skill_registry

    all_tools = get_skill_registry().all_tools
    assert "find_tool" in {t.name for t in all_tools}, "find_tool must be registered"
    bound = resolve_profile_tools("default", all_tools)
    assert "find_tool" in {t.name for t in bound}, "find_tool must be in the default profile"


# ── find_tool logic (embeddings mocked → deterministic) ──────────────────────


def _mock_catalog(monkeypatch):
    """Replace the real catalog with 3 orthogonal vectors so cosine is exact."""
    async def _noop():
        return

    monkeypatch.setattr(fts, "_ensure_catalog", _noop)
    monkeypatch.setattr(fts, "_tool_text_norm", {"alpha": "alpha", "beta": "beta", "gamma": "gamma"})
    monkeypatch.setattr(fts, "_tool_vectors", {
        "alpha": [1.0, 0.0, 0.0],
        "beta": [0.0, 1.0, 0.0],
        "gamma": [0.0, 0.0, 1.0],
    })
    monkeypatch.setattr(fts, "_tool_first_sentence", {"alpha": "a", "beta": "b", "gamma": "c"})

    class _FakeInfra:
        async def embed(self, text):  # noqa: ARG002 — query aligns with "alpha"
            return [1.0, 0.05, 0.0]

    monkeypatch.setattr("app.services.memory.get_memory_infra", lambda: _FakeInfra())


@pytest.mark.asyncio
async def test_find_tool_empty_capability():
    out = await fts.find_tool.ainvoke({"capability": "  "})
    assert "Précise" in out


@pytest.mark.asyncio
async def test_find_tool_returns_ranked_and_records_discovery(monkeypatch):
    _mock_catalog(monkeypatch)
    from app.agent.tool_context import CURRENT_CONVERSATION_ID

    conv = f"c-{uuid.uuid4().hex}"
    CURRENT_CONVERSATION_ID.set(conv)

    out = await fts.find_tool.ainvoke({"capability": "do alpha things", "top_k": 2})

    # alpha ranks first (query aligned), beta second; gamma excluded by top_k=2.
    assert "alpha" in out
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("•")]
    assert lines[0].strip().startswith("• alpha")
    # The top-2 are recorded for the conversation so agent_node binds them next turn.
    assert dt.get_discovered(conv) == {"alpha", "beta"}
    dt.discard_discovered(conv)


@pytest.mark.asyncio
async def test_find_tool_top_k_capped(monkeypatch):
    _mock_catalog(monkeypatch)
    out = await fts.find_tool.ainvoke({"capability": "x", "top_k": 99})
    # only 3 tools exist in the mock catalog → at most 3 bullets, never crashes
    bullets = [ln for ln in out.splitlines() if ln.strip().startswith("•")]
    assert 1 <= len(bullets) <= 3


# ── real semantic smoke (guarded — skips if FastEmbed unavailable) ───────────


@pytest.mark.asyncio
async def test_find_tool_real_catalog_surfaces_sheets():
    """End-to-end on the REAL full catalog: asking to read/append a Google
    Sheet must surface a sheets_* tool. This is the exact failure case (Ely
    said 'I have no tool' when sheets_read_spreadsheet existed). Works without
    FastEmbed — the lexical layer carries it ('sheet' ⊂ 'spreadsheet'/'sheets')."""
    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    from app.skills.builtin import register_all

    register_all()              # populate the full builtin catalog
    fts._catalog_sig = None     # force a catalog rebuild

    conv = f"c-{uuid.uuid4().hex}"
    CURRENT_CONVERSATION_ID.set(conv)
    out = await fts.find_tool.ainvoke(
        {"capability": "lire le contenu d'un Google Sheet existant et y ajouter des lignes",
         "top_k": 8}
    )
    discovered = dt.get_discovered(conv)
    dt.discard_discovered(conv)
    assert any(name.startswith("sheets_") for name in discovered), (
        f"expected a sheets_* tool surfaced, got: {sorted(discovered)}"
    )
    assert "sheets_" in out


# ── Phase 2 — genuine gap is recorded (tool_absent_acknowledged) ─────────────


@pytest.mark.asyncio
async def test_record_tool_absent_persists_and_dedups(_user):
    from app.models.failure_case import FailureCase
    from app.services.learning.failure_capture import SIGNAL_TOOL_ABSENT, record_tool_absent

    assert await record_tool_absent(user_id="", capability="x") is None        # no user
    assert await record_tool_absent(user_id=_user, capability="  ") is None     # empty cap

    id1 = await record_tool_absent(user_id=_user, capability="poster un message sur Slack")
    assert id1 is not None
    id2 = await record_tool_absent(user_id=_user, capability="poster un message sur Slack")
    assert id2 == id1  # deduped while unprocessed — no duplicate row

    async with async_session() as db:
        rows = (await db.execute(select(FailureCase).where(
            FailureCase.user_id == _user,
            FailureCase.signal_table == SIGNAL_TOOL_ABSENT,
        ))).scalars().all()
    assert len(rows) == 1
    assert "Slack" in (rows[0].expected_outcome or "")


@pytest.mark.asyncio
async def test_find_tool_no_match_records_gap(_user, monkeypatch):
    _mock_catalog(monkeypatch)

    # Override the query embed to be orthogonal → no semantic match either.
    class _ZeroInfra:
        async def embed(self, text):  # noqa: ARG002
            return [0.0, 0.0, 0.0]

    monkeypatch.setattr("app.services.memory.get_memory_infra", lambda: _ZeroInfra())

    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID

    CURRENT_CONVERSATION_ID.set(f"c-{uuid.uuid4().hex}")
    LEARNED_TOOL_USER_ID.set(_user)

    # Query with no lexical overlap with alpha/beta/gamma + no semantic → no match.
    out = await fts.find_tool.ainvoke({"capability": "zzz qqq wxy", "top_k": 3})
    assert "consign" in out.lower() or "réellement absente" in out

    from app.models.failure_case import FailureCase
    from app.services.learning.failure_capture import SIGNAL_TOOL_ABSENT

    async with async_session() as db:
        rows = (await db.execute(select(FailureCase).where(
            FailureCase.user_id == _user,
            FailureCase.signal_table == SIGNAL_TOOL_ABSENT,
        ))).scalars().all()
    assert any("zzz" in (r.expected_outcome or "") for r in rows)
