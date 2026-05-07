# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/tests/test_system_prompt_cache.py
# @brief      Unit tests for system_prompt_cache + frozen_memory (Hermes Chantier 2)
# =============================================================================
"""Unit tests for the Chantier 2 caching modules.

Covers :
- ``system_prompt_cache.get_or_build`` — builder called once, cache hits
  return the same string, invalidate forces rebuild
- ``frozen_memory.get_or_build`` — async builder called once, snapshot
  stays frozen even if the underlying source changes
- Bounded eviction LRU when > maxsize entries
- Empty ``conversation_id`` bypasses the cache
"""
from __future__ import annotations

import pytest

from app.services import frozen_memory as fm
from app.services import system_prompt_cache as spc


@pytest.fixture(autouse=True)
def _clean_state():
    spc._reset_for_tests()
    fm._reset_for_tests()
    yield
    spc._reset_for_tests()
    fm._reset_for_tests()


# ──────────────────────────────────────────────────────────────────────────────
# system_prompt_cache
# ──────────────────────────────────────────────────────────────────────────────


def test_builder_called_once_on_repeated_get():
    calls = {"count": 0}

    def _builder() -> str:
        calls["count"] += 1
        return f"prompt {calls['count']}"

    out1 = spc.get_or_build("conv-1", _builder)
    out2 = spc.get_or_build("conv-1", _builder)
    out3 = spc.get_or_build("conv-1", _builder)
    assert out1 == "prompt 1"
    assert out2 == "prompt 1"
    assert out3 == "prompt 1"
    assert calls["count"] == 1, "builder must be called only once"


def test_different_conversations_get_independent_caches():
    seq = iter(["A1", "B1"])
    out_a = spc.get_or_build("conv-A", lambda: next(seq))
    out_b = spc.get_or_build("conv-B", lambda: next(seq))
    assert out_a == "A1"
    assert out_b == "B1"
    # Re-fetching each returns the original — no cross-pollution
    assert spc.get_or_build("conv-A", lambda: "SHOULD_NOT_BE_CALLED") == "A1"
    assert spc.get_or_build("conv-B", lambda: "SHOULD_NOT_BE_CALLED") == "B1"


def test_invalidate_forces_rebuild():
    seq = iter(["v1", "v2"])
    assert spc.get_or_build("conv-1", lambda: next(seq)) == "v1"
    spc.invalidate("conv-1")
    assert spc.get_or_build("conv-1", lambda: next(seq)) == "v2"


def test_invalidate_unknown_conversation_is_noop():
    spc.invalidate("never-existed")  # must not raise
    assert spc.cache_size() == 0


def test_discard_removes_entry():
    spc.get_or_build("conv-1", lambda: "x")
    assert spc.cache_size() == 1
    spc.discard("conv-1")
    assert spc.cache_size() == 0


def test_empty_conversation_id_bypasses_cache():
    """Empty conv_id always rebuilds, never stores."""
    calls = {"count": 0}

    def _builder() -> str:
        calls["count"] += 1
        return f"r{calls['count']}"

    assert spc.get_or_build("", _builder) == "r1"
    assert spc.get_or_build("", _builder) == "r2"
    assert spc.cache_size() == 0


def test_cache_stats_reports_hits():
    spc.get_or_build("conv-1", lambda: "abc")
    spc.get_or_build("conv-1", lambda: "X")
    spc.get_or_build("conv-1", lambda: "X")
    stats = spc.cache_stats("conv-1")
    assert stats is not None
    assert stats["build_count"] == 3
    assert stats["prompt_chars"] == 3


def test_cache_stats_returns_none_for_missing():
    assert spc.cache_stats("ghost") is None


def test_non_string_builder_output_is_not_cached():
    """Defensive: a builder returning None / dict / list does not poison the cache."""
    seq = iter([None, "real prompt"])
    out1 = spc.get_or_build("conv-1", lambda: next(seq))
    assert out1 == ""  # None coerced to empty string
    # Cache was not polluted — second call invokes builder again
    out2 = spc.get_or_build("conv-1", lambda: next(seq))
    assert out2 == "real prompt"


def test_lru_eviction_when_over_maxsize(monkeypatch):
    """Beyond the maxsize cap, the oldest entry is evicted FIFO."""
    monkeypatch.setattr(spc, "_MAX_ENTRIES", 3)
    spc._reset_for_tests()
    spc._cache._maxsize = 3  # type: ignore[attr-defined]
    for i in range(5):
        spc.get_or_build(f"conv-{i}", lambda i=i: f"p{i}")
    # Only the 3 most recent survive
    assert spc.cache_size() == 3
    assert spc.cache_stats("conv-0") is None
    assert spc.cache_stats("conv-1") is None
    assert spc.cache_stats("conv-4") is not None


# ──────────────────────────────────────────────────────────────────────────────
# frozen_memory
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_frozen_memory_builder_called_once():
    calls = {"count": 0}

    async def _builder() -> str:
        calls["count"] += 1
        return f"snapshot {calls['count']}"

    out1 = await fm.get_or_build("conv-1", "user-1", _builder)
    out2 = await fm.get_or_build("conv-1", "user-1", _builder)
    out3 = await fm.get_or_build("conv-1", "user-1", _builder)
    assert out1 == "snapshot 1"
    assert out2 == "snapshot 1"
    assert out3 == "snapshot 1"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_frozen_memory_snapshot_stable_across_changing_source():
    """The snapshot must stay frozen even if the underlying memory mutates."""
    state = {"facts": ["A"]}

    async def _builder() -> str:
        # Re-reads the mutable state at build time — but should only be called once.
        return ", ".join(state["facts"])

    out1 = await fm.get_or_build("conv-1", "user-1", _builder)
    assert out1 == "A"
    # Simulate a mid-session memory_archive that adds a fact
    state["facts"].append("B")
    out2 = await fm.get_or_build("conv-1", "user-1", _builder)
    assert out2 == "A", "snapshot must NOT reflect mid-session mutations"


@pytest.mark.asyncio
async def test_frozen_memory_invalidate_forces_rebuild():
    state = {"facts": ["A"]}

    async def _builder() -> str:
        return ", ".join(state["facts"])

    assert await fm.get_or_build("conv-1", "u", _builder) == "A"
    state["facts"].append("B")
    fm.invalidate("conv-1")
    assert await fm.get_or_build("conv-1", "u", _builder) == "A, B"


@pytest.mark.asyncio
async def test_frozen_memory_independent_per_conversation():
    seq = iter(["snap-A", "snap-B"])

    async def _builder() -> str:
        return next(seq)

    a = await fm.get_or_build("conv-A", "u", _builder)
    b = await fm.get_or_build("conv-B", "u", _builder)
    assert a == "snap-A"
    assert b == "snap-B"


@pytest.mark.asyncio
async def test_frozen_memory_empty_conv_id_bypasses_cache():
    calls = {"count": 0}

    async def _builder() -> str:
        calls["count"] += 1
        return f"snap{calls['count']}"

    assert await fm.get_or_build("", "u", _builder) == "snap1"
    assert await fm.get_or_build("", "u", _builder) == "snap2"
    assert fm.snapshot_size() == 0


@pytest.mark.asyncio
async def test_frozen_memory_discard():
    async def _b() -> str:
        return "x"

    await fm.get_or_build("conv-1", "u", _b)
    assert fm.snapshot_size() == 1
    fm.discard("conv-1")
    assert fm.snapshot_size() == 0
