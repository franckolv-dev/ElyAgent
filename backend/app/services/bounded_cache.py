# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/bounded_cache.py
# @brief      Cache borné LRU + TTL partagé — remplace les 4 _BoundedDict
#             FIFO dupliqués (revue multi-utilisateurs 2026-06-10, B-7).
# @license    Elastic License 2.0
# =============================================================================
"""Bounded LRU dict with optional idle-TTL.

Four modules (conversation_filters, frozen_memory, system_prompt_cache,
fallback_manager) each had their own copy of a ``_BoundedDict`` capped at
1000 entries with **FIFO** eviction on insert. FIFO is the wrong policy
for per-conversation state: under load (~1000 cumulative active
conversations), the evicted entry is the *oldest created* — which can be a
conversation **still in progress**. Worst case documented by the review:
losing the PII ``SecurityFilter`` vault mid-conversation makes the
placeholders already present in the LLM context unresolvable → tool calls
go out with a literal ``[EMAIL_0]`` (the 2026-05-07 Gmail bug, reborn).

``BoundedLRUDict`` fixes the policy:

- **LRU** : every read (``[]``, ``get``, ``setdefault``) refreshes the
  entry — eviction targets the conversation idle the longest, never an
  active one.
- **TTL d'inactivité** (optionnel) : une entrée non touchée depuis
  ``ttl_seconds`` est considérée absente (expiration paresseuse à
  l'accès) — les conversations abandonnées ne squattent pas le cache
  jusqu'à l'éviction par taille.

Drop-in pour les usages existants : ``setdefault``/``get``/``pop``/
``[]``/``in``/``len`` conservent la même signature.
"""
from __future__ import annotations

import time
from collections import OrderedDict

_MISSING = object()


class BoundedLRUDict(OrderedDict):
    """OrderedDict borné, éviction LRU, TTL d'inactivité optionnel."""

    def __init__(self, maxsize: int = 1000, ttl_seconds: float | None = None) -> None:
        super().__init__()
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._touched: dict = {}

    # ── interne ──────────────────────────────────────────────────────────

    def _expired(self, key) -> bool:
        if self._ttl is None:
            return False
        ts = self._touched.get(key)
        return ts is not None and (time.monotonic() - ts) > self._ttl

    def _touch(self, key) -> None:
        self.move_to_end(key)
        self._touched[key] = time.monotonic()

    def _drop(self, key) -> None:
        super().__delitem__(key)
        self._touched.pop(key, None)

    # ── écriture ─────────────────────────────────────────────────────────

    def __setitem__(self, key, value) -> None:  # type: ignore[override]
        super().__setitem__(key, value)
        self._touch(key)
        while len(self) > self._maxsize:
            oldest, _ = super().popitem(last=False)
            self._touched.pop(oldest, None)

    def setdefault(self, key, default=None):  # type: ignore[override]
        existing = self.get(key, _MISSING)  # passe par l'expiration + touch
        if existing is not _MISSING:
            return existing
        self[key] = default
        return default

    # ── lecture (touch + expiration paresseuse) ──────────────────────────

    def __getitem__(self, key):  # type: ignore[override]
        if self._expired(key):
            self._drop(key)
        value = super().__getitem__(key)  # KeyError si absent/expiré
        self._touch(key)
        return value

    def get(self, key, default=None):  # type: ignore[override]
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key) -> bool:  # type: ignore[override]
        if self._expired(key):
            self._drop(key)
            return False
        return super().__contains__(key)

    # ── suppression ──────────────────────────────────────────────────────

    def pop(self, key, *args):  # type: ignore[override]
        self._touched.pop(key, None)
        return super().pop(key, *args)

    def __delitem__(self, key) -> None:  # type: ignore[override]
        self._drop(key)

    def sweep(self) -> int:
        """Purge proactive des entrées expirées. Retourne le nombre retiré."""
        if self._ttl is None:
            return 0
        expired = [k for k in list(super().keys()) if self._expired(k)]
        for k in expired:
            self._drop(k)
        return len(expired)
