# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/prompt_version.py
# @brief      Sprint 3.7 Jalon 3 — `prompt_version` hash helper.
#             Lets every learning signal (HITL refusal, hallucination,
#             error, fallback, feedback, mission step) carry the
#             sha256[:8] of the system prompt active at the time, so
#             rates can be correlated retroactively with the exact
#             prompt variant.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""prompt_version hash — Sprint 3.7 §3.

Rationale (design note §3) :
  When the rates of HITL refusals, hallucinations, errors etc. shift
  in production, we need to know whether the system prompt was the
  cause. Each row in the learning signals tables carries a short hash
  of the exact prompt text that was active when the signal fired. The
  hash is computed once (LRU-cached) per unique prompt string.

API :

  prompt_hash(text: str) -> str
      Stable 8-hex-char sha256 prefix. Pure function, LRU-cached.

  current_system_prompt_version() -> str
      Convenience : hashes the live ``_SYSTEM_PROMPT_BASE`` constant
      from ``app.agent.nodes``. Imported lazily to avoid circular deps.

Future-proofing (Jalon 5) :
  When A/B testing lands, ``select_variant()`` will return the picked
  variant's text ; that text gets hashed by ``prompt_hash`` and the
  hash is what we persist. Two variants → two distinct hashes →
  cohort-level analysis becomes trivial.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache


@lru_cache(maxsize=32)
def prompt_hash(text: str) -> str:
    """Return ``sha256(text)[:8]`` (8 hex chars). Pure function.

    The LRU cache (maxsize=32) is bounded to cover the modest number
    of distinct prompts ELY has at any given moment : 1 base + the few
    per-tier variants + future A/B variants. It is not meant to grow.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:8]


def current_system_prompt_version() -> str:
    """Hash of the live ``_SYSTEM_PROMPT_BASE`` (in ``app.agent.nodes``).

    Imported lazily because ``app.agent.nodes`` is a heavy module that
    pulls in LangGraph, the supervisor, etc. ; we don't want
    ``app.services.learning`` to drag all that in at import time.
    """
    from app.agent.nodes import _SYSTEM_PROMPT_BASE  # noqa: PLC0415
    return prompt_hash(_SYSTEM_PROMPT_BASE)


def _clear_cache_for_tests() -> None:
    """Test-only : wipe the LRU cache so an updated prompt re-hashes."""
    prompt_hash.cache_clear()
