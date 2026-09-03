# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_legacy_memory_tools_deprecated.py
# @brief      Sprint 2.5 Jalon 7 — pin the deprecation contract of the
#             legacy memory tools.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Deprecation contract for the legacy memory tools.

Three tools are wrapped as legacy aliases of the unified `memory_recall`
API: ``memory_search``, ``memory_recent``, ``search_past_conversations_tool``.

Pinned :
  1. First call emits exactly one DEPRECATION line via the
     ``app.services.memory._deprecated`` logger.
  2. Subsequent calls in the same process are silent (no log spam).
  3. The tool still produces a valid response (smoke).
  4. ``memory_search`` actually delegates to ``MemoryRecallService.recall``
     (single source of truth for the SEMANTIC_USER recall path).
"""
from __future__ import annotations

import logging

import pytest

from app.services.memory import _deprecated as deprecated_mod


@pytest.fixture(autouse=True)
def _reset_deprecation_state():
    deprecated_mod._reset_for_tests()
    yield
    deprecated_mod._reset_for_tests()


# ── log_deprecation one-shot behaviour ────────────────────────────────


def test_log_deprecation_emits_warning_first_call(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    deprecated_mod.log_deprecation("memory_search", successor="memory_recall")
    deprecation_records = [
        r for r in caplog.records if "DEPRECATION" in r.getMessage()
    ]
    assert len(deprecation_records) == 1
    assert "memory_search" in deprecation_records[0].getMessage()
    assert "memory_recall" in deprecation_records[0].getMessage()


def test_log_deprecation_is_silent_on_subsequent_calls(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    deprecated_mod.log_deprecation("memory_search")
    caplog.clear()
    deprecated_mod.log_deprecation("memory_search")
    deprecated_mod.log_deprecation("memory_search")
    assert all("DEPRECATION" not in r.getMessage() for r in caplog.records)


def test_log_deprecation_warns_per_distinct_tool(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    deprecated_mod.log_deprecation("memory_search")
    deprecated_mod.log_deprecation("memory_recent")
    deprecated_mod.log_deprecation("search_past_conversations_tool")
    msgs = [r.getMessage() for r in caplog.records if "DEPRECATION" in r.getMessage()]
    assert len(msgs) == 3


# ── memory_search delegates to MemoryRecallService ────────────────────


@pytest.mark.asyncio
async def test_memory_search_delegates_to_memory_recall(monkeypatch, caplog) -> None:
    """memory_search must go through MemoryRecallService.recall with
    memory_type=SEMANTIC_USER. Pins that we don't have two parallel
    recall paths drifting apart."""
    captured: dict = {}

    from app.services.memory.types import MemoryHit, MemoryType

    async def fake_recall(*args, **kwargs):
        captured.update(kwargs)
        return [
            MemoryHit(
                type=MemoryType.SEMANTIC_USER,
                content="user works on ELY",
                metadata={"kind": "fact"},
            ),
        ]

    fake_service = type("S", (), {"recall": fake_recall})()
    from app.agent.tools import memgpt_tool
    monkeypatch.setattr(
        "app.services.memory.get_memory_recall_service",
        lambda: fake_service,
    )

    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    out = await memgpt_tool.memory_search.ainvoke({
        "query": "what does the user work on?",
        "user_id": "u1",
        "limit": 3,
    })

    # Delegation occurred with the right type + scope.
    assert captured["memory_type"] == MemoryType.SEMANTIC_USER
    assert captured["user_id"] == "u1"
    assert captured["limit"] == 3
    # Response includes the recalled fact.
    assert "ELY" in out
    # Deprecation warning fired.
    assert any(
        "DEPRECATION" in r.getMessage() and "memory_search" in r.getMessage()
        for r in caplog.records
    )


# ── search_past_conversations_tool logs deprecation but keeps working ─


@pytest.mark.asyncio
async def test_search_past_conversations_emits_deprecation(monkeypatch, caplog) -> None:
    """The Sprint 1 cross-conv tool stays functional in V1 (the legacy
    Sprint 1 path is more mature than EpisodicStore for now), but must
    advertise itself as deprecated."""
    from app.agent.tools import session_search_tool

    async def fake_search(*, user_id, query, limit):
        return [{
            "title": "Bench Doctolib",
            "date": "2026-05-14T10:00:00",
            "summary": "Discussion about scheduling.",
        }]

    monkeypatch.setattr(
        session_search_tool,
        "search_past_conversations",
        fake_search,
    )

    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    out = await session_search_tool.search_past_conversations_tool.ainvoke({
        "query": "doctolib",
        "user_id": "u1",
        "limit": 1,
    })

    assert "Doctolib" in out or "Bench" in out
    assert any(
        "DEPRECATION" in r.getMessage()
        and "search_past_conversations_tool" in r.getMessage()
        for r in caplog.records
    )


# ── memory_recent logs deprecation ────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_recent_emits_deprecation_then_validates_category(caplog) -> None:
    from app.agent.tools.memgpt_tool import memory_recent

    caplog.set_level(logging.WARNING, logger="app.services.memory._deprecated")
    out = await memory_recent.ainvoke({
        "category": "not-a-real-category",
        "user_id": "u1",
    })

    assert "Catégorie inconnue" in out
    assert any(
        "DEPRECATION" in r.getMessage() and "memory_recent" in r.getMessage()
        for r in caplog.records
    )


# ── ROUTING.md documents the deprecated list ──────────────────────────


def test_routing_md_lists_every_deprecated_tool() -> None:
    from pathlib import Path

    routing = (
        Path(__file__).resolve().parents[1]
        / "app/services/memory/ROUTING.md"
    ).read_text(encoding="utf-8")

    for legacy in (
        "memory_search",
        "memory_recent",
        "search_past_conversations_tool",
    ):
        assert f"`{legacy}`" in routing, (
            f"Deprecated tool {legacy!r} is missing from "
            f"app/services/memory/ROUTING.md (Tools deprecated section)."
        )
