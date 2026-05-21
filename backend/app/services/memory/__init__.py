# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/__init__.py
# @brief      Typed memory subpackage — public re-exports.
# @license    PolyForm Strict License 1.0.0
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
from app.services.memory._infra import MemoryInfra, get_memory_infra
from app.services.memory.constraint_store import ConstraintStore
from app.services.memory.episodic_store import EpisodicStore
from app.services.memory.semantic_user_store import SemanticUserStore
from app.services.memory.procedural_store import ProceduralStore
from app.services.memory.error_store import ErrorStore

__all__ = [
    "MemoryInfra",
    "get_memory_infra",
    "ConstraintStore",
    "EpisodicStore",
    "SemanticUserStore",
    "ProceduralStore",
    "ErrorStore",
]
