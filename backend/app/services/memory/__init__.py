# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/__init__.py
# @brief      Typed memory subpackage — public re-exports.
# @license    MIT
# @version    1.3.0
# =============================================================================
"""Typed memory subpackage — Sprint 2.5.

Five stores, all sharing a single `MemoryInfra` (Qdrant client + fastembed
encoder + LRU embed cache). Each store owns one or two Qdrant collections
and/or one SQL table, exposing typed `store(...)` / `get_relevant(...)`.

The legacy `MemoryManager` (in `app/services/memory_manager.py`) is now a
thin facade delegating to these stores — 49 call sites continue to work
unchanged. Direct use of these stores is preferred in new code.
"""
from functools import lru_cache

from app.services.memory._infra import MemoryInfra, get_memory_infra
from app.services.memory.constraint_store import ConstraintStore
from app.services.memory.episodic_store import EpisodicStore
from app.services.memory.semantic_user_store import SemanticUserStore
from app.services.memory.error_store import ErrorStore
from app.services.memory.recall_service import (
    MemoryRecallService,
    get_memory_recall_service,
)
from app.services.memory.types import MemoryHit, MemoryType


# ── Singleton accessors per typed store (Sprint 2.5 Jalon 4) ──────────
# Use these in writing tools instead of `get_memory_manager()` — they
# make the target memory type explicit at the call site, which is what
# the Sprint 2.5 design note §5 ("routing explicite à l'écriture") asks.

@lru_cache(maxsize=1)
def get_constraint_store() -> ConstraintStore:
    return ConstraintStore(get_memory_infra())


@lru_cache(maxsize=1)
def get_episodic_store() -> EpisodicStore:
    return EpisodicStore(get_memory_infra())


@lru_cache(maxsize=1)
def get_semantic_user_store() -> SemanticUserStore:
    return SemanticUserStore(get_memory_infra())


@lru_cache(maxsize=1)
def get_error_store() -> ErrorStore:
    return ErrorStore()


__all__ = [
    "MemoryInfra",
    "get_memory_infra",
    "ConstraintStore",
    "EpisodicStore",
    "SemanticUserStore",
    "ErrorStore",
    "MemoryRecallService",
    "get_memory_recall_service",
    "MemoryHit",
    "MemoryType",
    "get_constraint_store",
    "get_episodic_store",
    "get_semantic_user_store",
    "get_error_store",
]
