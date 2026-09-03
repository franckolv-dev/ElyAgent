# =============================================================================
# @project    Ely — Exactly Like You
# @file       backend/app/services/system_prompt_cache.py
# @brief      Per-conversation system prompt cache (Hermes Chantier 2)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Per-conversation system prompt cache — Hermes Chantier 2.

Why
---
The Anthropic and DashScope (Qwen) APIs apply a **prompt cache prefix**
optimisation : when N successive requests start with byte-identical
tokens, the provider re-uses the previously computed attention KV cache
and skips re-encoding that prefix. The savings are massive — Anthropic
documents up to **−90 % latency and −90 % cost** on the cached portion.

Before this module, ELY rebuilt the entire system prompt at every turn
(memory query, preferences, constraints, past_interactions, current
date string), resulting in a **0 % prompt cache hit rate** for the
provider's billing and latency. Even the immutable parts (~7 000 chars
of identity + rules) were never reused across turns of the same session.

What gets cached vs. what stays dynamic
---------------------------------------
A turn's system prompt is now built in **two segments** :

1. **CACHEABLE** (frozen at first use, identical for every subsequent
   turn of the conversation) :
   - The static identity + rules block (`_SYSTEM_PROMPT_BASE`)
   - Conditional injections that depend on the LLM family (only added
     once at first build)
   - Memory snapshot (Qdrant + SQL — see ``frozen_memory.py``)
   - User profile + preferences + constraints (read once)
   - past_interactions (read once)

2. **DYNAMIC** (concatenated AFTER the cacheable segment, may differ
   between turns) :
   - Date / time string
   - "📧 Adresses email déjà fournies" block (scanned from recent messages)
   - Language directive sandwich

The provider's cache prefix walks the request from the start and matches
as many tokens as possible. Because the cacheable segment is byte-stable,
the prefix matches all of it before reaching the dynamic part — which
is exactly the maximum cache hit we can achieve without API-level
``cache_control`` markers.

Sticky for the conversation
---------------------------
The cache is keyed by ``conversation_id``. Once built, it lives until :
- The conversation ends (WS disconnect) → ``discard``
- The user changes profile (``/profile <name>``) → ``invalidate``
- A future Chantier explicitly invalidates (e.g. context compression)

A new conversation starts with a fresh cache, so newly-archived facts
(``memory_archive`` mid-session) appear in the next session's cacheable
segment.
"""
from __future__ import annotations

import logging
import time
from app.services.bounded_cache import BoundedLRUDict
from typing import Callable, Final, Optional

logger = logging.getLogger(__name__)


# ── Bounded LRU registry ──────────────────────────────────────────────────────

_MAX_ENTRIES: Final[int] = 1000




# conversation_id → {"prompt": str, "built_at": float, "build_count": int}
# B-7 — LRU + TTL 24 h (était FIFO).
_cache: BoundedLRUDict = BoundedLRUDict(maxsize=_MAX_ENTRIES, ttl_seconds=24 * 3600)


# ── Public API ────────────────────────────────────────────────────────────────


def get_or_build(
    conversation_id: str,
    builder: Callable[[], str],
) -> str:
    """Return the cacheable system prompt for a conversation.

    On the first call for ``conversation_id``, ``builder`` is awaited
    synchronously to produce the prompt string ; the result is stored
    and returned. On every subsequent call, the cached string is
    returned without calling ``builder`` again.

    The caller is responsible for concatenating the dynamic segments
    (date, emails block, language directives) AFTER this returned
    cacheable string.

    Parameters
    ----------
    conversation_id
        Unique identifier of the user's conversation. An empty string
        is allowed but bypasses the cache (always rebuilds, never stores).
    builder
        Zero-arg function that returns the cacheable system prompt
        string. It will be called at most once per ``conversation_id``
        until the cache is invalidated.
    """
    if not conversation_id:
        # No conversation context (rare: API caller without conv_id) —
        # build fresh every time, do not pollute the cache.
        return builder()

    entry = _cache.get(conversation_id)
    if entry is not None:
        # Cache HIT — track the count for telemetry/diagnostics.
        entry["build_count"] += 1
        logger.debug(
            "system_prompt_cache: HIT conv=%s (n=%d)",
            conversation_id, entry["build_count"],
        )
        return entry["prompt"]

    # Cache MISS — build, store, return.
    prompt = builder()
    if not isinstance(prompt, str):
        # Defensive: a misbehaving builder. Don't pollute the cache.
        logger.warning(
            "system_prompt_cache: builder returned non-str (%s) — bypassing cache",
            type(prompt).__name__,
        )
        return str(prompt) if prompt is not None else ""
    _cache[conversation_id] = {
        "prompt": prompt,
        "built_at": time.time(),
        "build_count": 1,
    }
    logger.info(
        "system_prompt_cache: BUILD conv=%s (%d chars)",
        conversation_id, len(prompt),
    )
    return prompt


def invalidate(conversation_id: str) -> None:
    """Drop the cache for ``conversation_id`` so the next ``get_or_build``
    re-runs the builder. Idempotent — calling on a missing entry is a no-op.

    Called when something changes the cacheable content :
    - ``/profile <name>`` slash command (toolset changes)
    - Future : context compression (history rewrite invalidates assumptions)
    - Future : user explicitly resets memory
    """
    if conversation_id in _cache:
        _cache.pop(conversation_id, None)
        logger.info("system_prompt_cache: INVALIDATE conv=%s", conversation_id)


def discard(conversation_id: str) -> None:
    """Drop the cache for a conversation (call on WS disconnect).
    Same as ``invalidate`` but semantic distinction in logs.
    """
    if conversation_id in _cache:
        _cache.pop(conversation_id, None)
        logger.debug("system_prompt_cache: DISCARD conv=%s", conversation_id)


def cache_stats(conversation_id: str) -> Optional[dict]:
    """Return the cache entry metadata for diagnostics. None if missing."""
    entry = _cache.get(conversation_id)
    if entry is None:
        return None
    return {
        "built_at": entry["built_at"],
        "build_count": entry["build_count"],
        "prompt_chars": len(entry["prompt"]),
    }


def cache_size() -> int:
    """Total number of conversations with a cached prompt."""
    return len(_cache)


def _reset_for_tests() -> None:
    """Test-only helper. Never call from production code."""
    _cache.clear()
