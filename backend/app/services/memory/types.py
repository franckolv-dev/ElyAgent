# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/types.py
# @brief      Public types for the typed memory subpackage —
#             `MemoryType` enum + `MemoryHit` dataclass.
# @license    Elastic License 2.0
# @version    1.3.0
# =============================================================================
"""Public types — Sprint 2.5 §3, §9.

`MemoryRecallService.recall(...)` always returns `list[MemoryHit]`.
A `MemoryHit` is the type-safe envelope that hides the underlying
store's payload shape from callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MemoryType(str, Enum):
    """The 5 typed memories + an `AUTO` fan-out option.

    Inherits from `str` so the value is JSON-serialisable as-is, which
    matters for the LangChain tool that exposes this enum to the LLM.
    """

    EPISODIC = "episodic"
    SEMANTIC_USER = "semantic_user"
    PROCEDURAL = "procedural"
    ERROR = "error"
    CONSTRAINT = "constraint"
    AUTO = "auto"

    @classmethod
    def parse(cls, value: str | "MemoryType") -> "MemoryType":
        """Lenient parser — accepts MemoryType, lowercase or uppercase string."""
        if isinstance(value, cls):
            return value
        s = str(value).strip().lower()
        for member in cls:
            if member.value == s:
                return member
        raise ValueError(
            f"Unknown MemoryType {value!r}. "
            f"Valid: {[m.value for m in cls]}"
        )


@dataclass(slots=True)
class MemoryHit:
    """One result from `MemoryRecallService.recall(...)`.

    `content` is the human-readable string the caller should display or
    feed back to the LLM. `metadata` is type-specific extras (e.g. for
    EPISODIC: `conversation_id`, `assistant_message`; for PROCEDURAL:
    `tool_calls`, `success_count`).
    """

    type: MemoryType
    content: str
    score: float = 1.0
    metadata: dict = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict:
        """JSON-serialisable view — used by the LangChain tool layer."""
        return {
            "type": self.type.value,
            "content": self.content,
            "score": round(self.score, 4),
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
