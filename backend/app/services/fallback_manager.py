# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/fallback_manager.py
# @brief      Per-conversation provider fallback chain (Hermes Chantier 4)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Per-conversation provider fallback chain — Hermes Chantier 4.

Why
---
Before this module, ELY had two parallel fallback systems:

1. **Construction-time** in ``get_llm_for_tier`` — cascades through providers
   only when *instantiation* fails (no API key, factory exception). If the
   instantiated LLM later plants on ``ainvoke`` (rate limit, timeout, billing,
   empty response), no further fallback runs.

2. **Invocation-time** in ``get_fallback_llms`` + the loop in
   ``nodes.py:agent_node`` (line ~932) — iterates through fallback providers
   when ``ainvoke`` raises. But it has four serious gaps:

   - It re-binds ``registry.all_tools`` (~145 tools) instead of the sticky
     toolset profile from Chantier 1, so the prompt cache prefix is destroyed
     and the model relearns a different catalogue mid-session.
   - No per-conversation memory. Every turn re-tries the primary even when
     it's been failing for the last 5 turns — re-incurring 429s, timeouts.
   - No WS event for the frontend. The user sees a 30-second silence when a
     swap is happening, with no UI signal.
   - No empty-response detection. A model that returns 3 empty replies in a
     row is left running until the user gives up.

This module unifies all that into a single ``FallbackManager`` with state
keyed by conversation_id. The contract is simple : ``get_or_create`` at the
start of every turn ; ``try_activate`` when an exception is recoverable ;
``record_response`` after every inference to track empty-replies.

Design choices (decided 2026-05-07)
-----------------------------------
- **Source of the chain** : we reuse ``tier_config[tier]["providers"]``,
  the user-configured ordered list per tier. No new DB table. The 1st
  provider = primary, the rest = fallbacks in order. Means the user only
  has one place to manage providers (Settings → Routage), not two.

- **Sticky for the conversation** : once we've switched to a fallback, we
  STAY on it for every subsequent turn of the same conversation. Re-trying
  the primary every turn would re-incur the same 429 / timeout. A new
  conversation starts back on the primary — so the user is never permanently
  stuck on a degraded provider.

- **Chain frozen at first use** : the list captured at ``get_or_create``
  is the chain we honour for the rest of the conversation. If the user
  changes tier_config mid-session, the new chain takes effect only on the
  NEXT conversation. Avoids surprising a running session with a freshly
  injected provider.

- **Empty-response trigger** : 3 consecutive empty replies (no content AND
  no tool_calls) → automatic switch with reason ``EMPTY_RESPONSE``. A
  non-empty reply resets the counter. 3 is conservative — a single empty
  reply can be transient.

WS events
---------
The manager populates a per-conversation queue of ``{type:"provider.switched",
from, to, reason, ts}`` events that the chat router (chat.py) drains and
sends over the WebSocket. The frontend can show a discreet toast.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Optional

logger = logging.getLogger(__name__)


# ── FailoverReason ────────────────────────────────────────────────────────────


class FailoverReason(str, Enum):
    """Why we asked for a switch. Used in logs, WS events and analytics."""
    RATE_LIMIT       = "rate_limit"        # HTTP 429 / "too many requests"
    BILLING          = "billing"           # 402, "quota exceeded", "insufficient"
    AUTH             = "auth"              # 401, 403, invalid key
    TIMEOUT          = "timeout"           # httpx timeout, stream timeout
    UNAVAILABLE      = "unavailable"       # 503, 404 model, deprecated
    EMPTY_RESPONSE   = "empty_response"    # ≥3 consecutive empty replies
    H1_HALLUCINATION = "h1_hallucination"  # local + 0 tool_calls + action verb
    BAD_REQUEST      = "bad_request"       # 400, invalid_argument (model schema bug)
    UNKNOWN          = "unknown"           # other recoverable exception


# Heuristic mapping from substrings found in exception messages → reason.
# Order matters: more specific keywords first. We DO NOT include very generic
# keywords (e.g. "error", "fail") — they would catch true programmer bugs and
# hide them behind a fallback retry.
_REASON_KEYWORDS: Final[tuple[tuple[str, FailoverReason], ...]] = (
    # H1 — synthetic exception thrown by the anti-hallucination guard
    ("h1_fallback",   FailoverReason.H1_HALLUCINATION),
    # Rate limiting
    ("429",           FailoverReason.RATE_LIMIT),
    ("rate limit",    FailoverReason.RATE_LIMIT),
    ("rate_limit",    FailoverReason.RATE_LIMIT),
    ("ratelimit",     FailoverReason.RATE_LIMIT),
    ("too many",      FailoverReason.RATE_LIMIT),
    # Billing / quota
    ("402",           FailoverReason.BILLING),
    ("quota",         FailoverReason.BILLING),
    ("insuffi",       FailoverReason.BILLING),
    ("billing",       FailoverReason.BILLING),
    ("payment",       FailoverReason.BILLING),
    # Auth
    ("401",           FailoverReason.AUTH),
    ("403",           FailoverReason.AUTH),
    ("invalid api",   FailoverReason.AUTH),
    ("invalid_api",   FailoverReason.AUTH),
    ("unauthorized",  FailoverReason.AUTH),
    # Unavailable
    ("503",           FailoverReason.UNAVAILABLE),
    ("unavailable",   FailoverReason.UNAVAILABLE),
    ("overloaded",    FailoverReason.UNAVAILABLE),
    ("deprecated",    FailoverReason.UNAVAILABLE),
    ("no longer",     FailoverReason.UNAVAILABLE),
    ("404",           FailoverReason.UNAVAILABLE),
    ("not_found",     FailoverReason.UNAVAILABLE),
    ("not found",     FailoverReason.UNAVAILABLE),
    # Timeout
    ("timeout",       FailoverReason.TIMEOUT),
    ("timed out",     FailoverReason.TIMEOUT),
    ("read timeout",  FailoverReason.TIMEOUT),
    # Bad request — model returns a structural error (often a schema mismatch)
    ("400",           FailoverReason.BAD_REQUEST),
    ("invalid_argument", FailoverReason.BAD_REQUEST),
    ("bad request",   FailoverReason.BAD_REQUEST),
)


def classify_exception(exc: BaseException) -> Optional[FailoverReason]:
    """Map an exception to a ``FailoverReason`` if it's recoverable, else None.

    None means : let the exception propagate. A real programmer bug
    (KeyError, AttributeError, TypeError on our own code) should NEVER be
    silently swallowed by a fallback — that hides bugs and creates ghost
    behaviour. Only known operational failures (network, billing, model
    behaviour) get a reason.
    """
    if exc is None:
        return None
    msg = str(exc).lower()
    if not msg:
        return None
    for keyword, reason in _REASON_KEYWORDS:
        if keyword in msg:
            return reason
    return None


# ── Per-conversation state ────────────────────────────────────────────────────


@dataclass
class _ConversationFallbackState:
    """Tracks where we are in the fallback chain for a single conversation."""

    tier: str                       # tier name (e.g. "medium")
    chain: list[str]                # ordered list of provider IDs/instance UUIDs
    current_index: int = 0          # 0 = primary, 1+ = fallback active
    empty_count: int = 0            # consecutive empty responses
    # (reason, from_provider, to_provider, ts_unix) — diagnostic history
    reason_history: list[tuple[FailoverReason, str, str, float]] = field(default_factory=list)
    # Unix timestamp at which we left the primary. Set by ``try_activate``
    # every time the chain advances past index 0. Reset to ``None`` by
    # ``reset_to_primary``. Used by ``should_retry_primary`` to decide when
    # to give the primary a fresh chance (audit Gemini §1.3, retry hotfix).
    fallback_activated_at: float | None = None

    @property
    def current_provider(self) -> str:
        """Provider ID currently in use. Empty string when chain is exhausted."""
        if 0 <= self.current_index < len(self.chain):
            return self.chain[self.current_index]
        return ""

    @property
    def is_exhausted(self) -> bool:
        """True once every provider in the chain has been tried."""
        return self.current_index >= len(self.chain)

    @property
    def is_active_fallback(self) -> bool:
        """True when we are NOT on the primary anymore (a switch has happened)."""
        return self.current_index > 0


# ── Module-level registries (bounded LRU) ─────────────────────────────────────

_MAX_STATES: Final[int] = 1000


class _BoundedDict(OrderedDict):
    """OrderedDict with a hard cap — oldest entries evicted FIFO when size
    exceeds ``maxsize``. Same pattern as ``conversation_filters._BoundedDict``.
    """

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value) -> None:  # type: ignore[override]
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)


# conversation_id → state
_states: _BoundedDict = _BoundedDict(maxsize=_MAX_STATES)
# conversation_id → list of pending WS events to drain
_pending_events: _BoundedDict = _BoundedDict(maxsize=_MAX_STATES)


# ── Public API ────────────────────────────────────────────────────────────────


def get_or_create(
    conversation_id: str,
    tier: str,
    chain: list[str],
) -> _ConversationFallbackState:
    """Return the state for ``conversation_id``, creating one on first call.

    The ``chain`` is captured the first time and frozen for this
    conversation's lifetime. Subsequent calls IGNORE the ``chain`` argument
    even if it differs — see module docstring (chain frozen at first use).

    Parameters
    ----------
    conversation_id
        Unique identifier of the user's conversation. Empty string is allowed
        but uses a shared "anonymous" slot — caller should provide a real id.
    tier
        Complexity tier (``"simple"``, ``"medium"``, ``"complex"``, etc.).
        Stored for diagnostics.
    chain
        Ordered list of provider IDs / LLMInstance UUIDs. The first item is
        the primary, the rest are fallbacks tried in order.
    """
    if conversation_id in _states:
        return _states[conversation_id]
    state = _ConversationFallbackState(tier=tier, chain=list(chain))
    _states[conversation_id] = state
    return state


def discard(conversation_id: str) -> None:
    """Drop state + pending events for a conversation (call on WS disconnect)."""
    _states.pop(conversation_id, None)
    _pending_events.pop(conversation_id, None)


def try_activate(
    conversation_id: str,
    reason: FailoverReason,
) -> Optional[str]:
    """Advance the conversation to the next provider in the chain.

    Returns
    -------
    str | None
        The new provider ID if a switch happened, ``None`` if the chain is
        exhausted or no state exists for ``conversation_id``.

    Side effects
    ------------
    - Records the switch in ``reason_history``
    - Emits a ``provider.switched`` WS event into the pending queue
    - Resets ``empty_count`` to 0
    """
    state = _states.get(conversation_id)
    if state is None:
        logger.debug("fallback.try_activate: no state for conv=%s", conversation_id)
        return None
    if state.is_exhausted:
        logger.debug("fallback.try_activate: already exhausted for conv=%s", conversation_id)
        return None

    old_provider = state.current_provider
    state.current_index += 1

    if state.is_exhausted:
        # We just walked off the end. No new provider to activate.
        logger.warning(
            "[fallback] conv=%s chain EXHAUSTED after %r (reason=%s, chain=%s)",
            conversation_id, old_provider, reason.value, state.chain,
        )
        # Still record the failed attempt for diagnostics.
        state.reason_history.append((reason, old_provider, "", time.time()))
        return None

    new_provider = state.current_provider
    ts = time.time()
    state.reason_history.append((reason, old_provider, new_provider, ts))
    state.empty_count = 0
    # Retry hotfix (audit Gemini §1.3) : remember when we left the primary
    # so `should_retry_primary` can decide to give it another chance after
    # the configured cool-down.
    state.fallback_activated_at = ts

    _pending_events.setdefault(conversation_id, []).append({
        "type": "provider.switched",
        "from": old_provider,
        "to": new_provider,
        "reason": reason.value,
        "ts": ts,
    })

    logger.warning(
        "[fallback] conv=%s switched %r → %r (reason=%s, chain_pos=%d/%d)",
        conversation_id, old_provider, new_provider, reason.value,
        state.current_index + 1, len(state.chain),
    )
    return new_provider


def record_response(
    conversation_id: str,
    content: str,
    has_tool_calls: bool,
) -> bool:
    """Track an inference result. Trigger fallback on 3 consecutive empties.

    A response is "empty" when both the text content is blank AND there are
    no structured tool_calls. An empty content with tool_calls is FINE
    (model decided to act, that's normal). A non-empty response resets the
    counter.

    Returns
    -------
    bool
        True if this response triggered a fallback switch (chain advanced).
        False otherwise.
    """
    state = _states.get(conversation_id)
    if state is None:
        return False

    is_empty = (not content or not content.strip()) and not has_tool_calls
    if is_empty:
        state.empty_count += 1
        logger.info(
            "[fallback] conv=%s empty response %d/3", conversation_id, state.empty_count,
        )
        if state.empty_count >= 3:
            new = try_activate(conversation_id, FailoverReason.EMPTY_RESPONSE)
            return new is not None
        return False

    # Non-empty: reset the counter.
    state.empty_count = 0
    return False


def drain_events(conversation_id: str) -> list[dict]:
    """Pop and return all pending WS events for a conversation."""
    return _pending_events.pop(conversation_id, [])


def get_state(conversation_id: str) -> Optional[_ConversationFallbackState]:
    """Read-only access for tests and diagnostics. May return None."""
    return _states.get(conversation_id)


# ── Retry-primary hotfix (audit Gemini 2026-05-25 §1.3) ──────────────────────
#
# Problem
# -------
# Without retry, a single transient failure on the primary (network blip,
# rate limit, a faux-positive H-1 detection — observed 2026-05-25 on conv
# e9b33b7d) sticks the WHOLE conversation on its fallback for the rest of
# the session. That's expensive (cloud→cloud), denies souveraineté (cloud
# instead of local), and ignores that the primary may have recovered
# seconds later.
#
# Solution
# --------
# When a fallback is active and the cool-down elapsed (default 10 min),
# `should_retry_primary` returns True. The caller (agent_node) then calls
# `reset_to_primary` which puts ``current_index = 0`` so the next inference
# tries the primary again. If the primary is still broken, the standard
# chantier-4 machinery re-advances and ``fallback_activated_at`` is reset
# to "now" — so the cool-down restarts. No risk of busy-looping.
#
# Kill-switch
# -----------
# ``FALLBACK_RETRY_PRIMARY_MINUTES`` env :
#   - unset / >0  : retry after N minutes (default 10)
#   - "0"         : never retry, legacy sticky-forever behaviour


def _retry_threshold_seconds() -> float:
    """Read the cool-down threshold from env (in seconds). 0 disables retry."""
    import os
    try:
        minutes = float(os.getenv("FALLBACK_RETRY_PRIMARY_MINUTES", "10"))
    except (ValueError, TypeError):
        minutes = 10.0
    return max(0.0, minutes) * 60.0


def should_retry_primary(
    conversation_id: str,
    *,
    now: Optional[float] = None,
) -> bool:
    """Return True if we should give the primary a fresh chance.

    Conditions (all must hold):
      - State exists for the conversation.
      - A fallback is currently active (``is_active_fallback``).
      - ``fallback_activated_at`` is set (sanity).
      - At least ``FALLBACK_RETRY_PRIMARY_MINUTES`` minutes elapsed since
        the activation (default 10).
      - The kill-switch is not set to 0 / disabled.

    Parameters
    ----------
    conversation_id :
        Same key as the rest of the API.
    now :
        Override "current time" for tests. Defaults to ``time.time()``.
    """
    threshold = _retry_threshold_seconds()
    if threshold <= 0:
        return False
    state = _states.get(conversation_id)
    if state is None or not state.is_active_fallback:
        return False
    if state.fallback_activated_at is None:
        return False
    _now = time.time() if now is None else now
    elapsed = _now - state.fallback_activated_at
    return elapsed >= threshold


def reset_to_primary(
    conversation_id: str,
    *,
    reason: str = "cooldown_elapsed",
) -> bool:
    """Send the conversation back to the primary provider (index 0).

    Used by ``should_retry_primary`` callers after the cool-down. Logs the
    reset for ops visibility. Returns True if a reset actually happened,
    False if the state was already on the primary or didn't exist.
    """
    state = _states.get(conversation_id)
    if state is None or not state.is_active_fallback:
        return False
    old_provider = state.current_provider
    state.current_index = 0
    state.fallback_activated_at = None
    state.empty_count = 0
    new_provider = state.current_provider
    ts = time.time()
    _pending_events.setdefault(conversation_id, []).append({
        "type": "provider.reset_to_primary",
        "from": old_provider,
        "to": new_provider,
        "reason": reason,
        "ts": ts,
    })
    logger.warning(
        "[fallback] conv=%s reset_to_primary %r → %r (reason=%s)",
        conversation_id, old_provider, new_provider, reason,
    )
    return True


def state_count() -> int:
    """How many conversations currently have an active fallback state."""
    return len(_states)


# ── Test-only utility ─────────────────────────────────────────────────────────


def _reset_for_tests() -> None:
    """Clear all state. Tests only — never call from production code."""
    _states.clear()
    _pending_events.clear()
