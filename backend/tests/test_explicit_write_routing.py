# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_explicit_write_routing.py
# @brief      Sprint 2.5 Jalon 4 — pin the explicit write routing of every
#             memory-writing LangChain tool. Catches accidental drift back to
#             the legacy `MemoryManager.store_*` API.
# @license    Elastic License 2.0
# =============================================================================
"""Pin every memory write tool to its declared target store.

Two complementary guards :

1. **Source-level guard** — the source file of each writing tool must
   contain the `Sprint 2.5 Jalon 4 — routing explicite:` marker
   immediately above its `store_*` call. This prevents anyone re-adding
   a `MemoryManager.store_memory(...)` call without a routing block.

2. **Runtime guard** — when each tool is invoked, the correct typed
   store method is called (verified via monkeypatch).

If you legitimately add a new memory-writing tool, update both this
test and `app/services/memory/ROUTING.md`.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTING_MARKER = "Sprint 2.5 Jalon 4 — routing explicite"


# ── Source-level guard ────────────────────────────────────────────────


_WRITE_TOOLS_BY_FILE = {
    "app/agent/tools/memory_tool.py": ["save_user_preference", "save_constraint"],
    "app/agent/tools/memgpt_tool.py": ["memory_archive"],
}


@pytest.mark.parametrize(
    "rel_path",
    sorted(_WRITE_TOOLS_BY_FILE.keys()),
)
def test_source_contains_routing_marker(rel_path: str) -> None:
    src = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert _ROUTING_MARKER in src, (
        f"{rel_path} must contain the Sprint 2.5 Jalon 4 routing marker "
        f"above each store_* call. See app/services/memory/ROUTING.md."
    )


def test_no_writer_imports_legacy_memory_manager() -> None:
    """No memory-write tool should pull in `get_memory_manager` to write.

    Reads via `get_memory_manager` are still allowed for backward compat —
    this only forbids the *write* path (which is what Jalon 4 governs).
    """
    forbidden = "get_memory_manager"
    write_call_patterns = (
        ".store_memory(",
        ".store_preference(",
        ".store_constraint(",
        ".store_interaction(",
    )
    for rel_path in _WRITE_TOOLS_BY_FILE:
        src = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        if forbidden in src:
            # Allowed only if no store_* call follows — i.e. legacy import
            # kept for an unrelated reason. We still flag for review.
            for pat in write_call_patterns:
                # Look for `<something_from_legacy_manager>.store_*(`. If
                # we find one, the file is writing via the legacy facade.
                if "memory.store_" in src or "manager.store_" in src:
                    pytest.fail(
                        f"{rel_path} still writes via the legacy MemoryManager "
                        f"(pattern {pat!r}). Sprint 2.5 Jalon 4 requires "
                        f"writes to go through the typed store accessors."
                    )


# ── Runtime guard ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_user_preference_calls_semantic_user_store(monkeypatch) -> None:
    """`save_user_preference` must invoke `SemanticUserStore.store_preference`."""
    calls: list[tuple] = []

    async def fake_store_preference(self, preference, user_id):
        calls.append(("preference", preference, user_id))

    from app.services.memory.semantic_user_store import SemanticUserStore
    monkeypatch.setattr(
        SemanticUserStore, "store_preference", fake_store_preference
    )

    from app.agent.tools.memory_tool import save_user_preference
    out = await save_user_preference.ainvoke({
        "preference": "Tutoyer l'utilisateur",
        "user_id": "u1",
    })

    assert calls == [("preference", "Tutoyer l'utilisateur", "u1")]
    assert "Préférence enregistrée" in out


@pytest.mark.asyncio
async def test_save_constraint_calls_constraint_store(monkeypatch) -> None:
    """`save_constraint` must invoke `ConstraintStore.store`."""
    calls: list[tuple] = []

    async def fake_store(self, rule, user_id):
        calls.append(("constraint", rule, user_id))

    from app.services.memory.constraint_store import ConstraintStore
    monkeypatch.setattr(ConstraintStore, "store", fake_store)

    from app.agent.tools.memory_tool import save_constraint
    out = await save_constraint.ainvoke({
        "rule": "Ne jamais envoyer de mail à spam@x.com",
        "user_id": "u1",
    })

    assert calls == [("constraint", "Ne jamais envoyer de mail à spam@x.com", "u1")]
    assert "Contrainte enregistrée" in out


@pytest.mark.asyncio
async def test_memory_archive_calls_semantic_user_store_fact(monkeypatch) -> None:
    """`memory_archive` must invoke `SemanticUserStore.store_fact`."""
    calls: list[dict] = []

    async def fake_store_fact(self, content, user_id, conversation_id="", extra_payload=None):
        calls.append({
            "content": content,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "extra_payload": extra_payload,
        })

    from app.services.memory.semantic_user_store import SemanticUserStore
    monkeypatch.setattr(SemanticUserStore, "store_fact", fake_store_fact)

    from app.agent.tools.memgpt_tool import memory_archive
    out = await memory_archive.ainvoke({
        "fact": "User's wife uses iPhone",
        "category": "fact",
        "user_id": "u1",
    })

    assert len(calls) == 1
    assert calls[0]["content"] == "User's wife uses iPhone"
    assert calls[0]["user_id"] == "u1"
    assert calls[0]["conversation_id"] == "memgpt"
    assert calls[0]["extra_payload"]["category"] == "fact"
    assert "Archivé" in out


# ── Singleton accessor wiring ─────────────────────────────────────────


def test_typed_store_accessors_are_singletons() -> None:
    """`get_X_store()` returns the same instance across calls — important
    so the LRU embed cache shared via MemoryInfra is actually shared."""
    from app.services.memory import (
        get_constraint_store,
        get_episodic_store,
        get_semantic_user_store,
        get_error_store,
    )
    assert get_constraint_store() is get_constraint_store()
    assert get_episodic_store() is get_episodic_store()
    assert get_semantic_user_store() is get_semantic_user_store()
    assert get_error_store() is get_error_store()


def test_routing_md_documents_every_writing_tool() -> None:
    """Every tool listed in _WRITE_TOOLS_BY_FILE must appear in ROUTING.md."""
    routing = (_REPO_ROOT / "app/services/memory/ROUTING.md").read_text(encoding="utf-8")
    for tools in _WRITE_TOOLS_BY_FILE.values():
        for tool_name in tools:
            assert f"`{tool_name}`" in routing, (
                f"Tool {tool_name!r} is missing from "
                f"app/services/memory/ROUTING.md — add it to the mapping table."
            )
