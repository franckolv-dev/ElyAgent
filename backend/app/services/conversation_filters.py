# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/conversation_filters.py
# @brief      Per-conversation SecurityFilter registry (PII anonymization)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Shared registry of per-conversation SecurityFilter instances.

The SecurityFilter holds the bidirectional mapping between real PII values
(emails, phone numbers, IBANs, etc.) and their placeholders (``[EMAIL_0]``,
``[PHONE_0]``, etc.). It MUST be the same instance throughout a conversation
so a placeholder created when the user first sent ``follivier@datasolution.fr``
can be resolved back to the real address when the LLM later emits a tool
call ``gmail_send_email(to="[EMAIL_0]", ...)``.

Before this module existed, the registry was a private ``_filters`` dict in
``app/routers/chat.py``. Tool execution lives in ``app/agent/nodes.py`` and
needs the same registry to deanonymize tool-call arguments before the API
call — but importing chat.py from nodes.py would create a circular import
(chat → graph → nodes). Hosting the registry here in a dedicated services
module breaks the cycle.

(Discovered 2026-05-07 — bug observed: ``gmail_send_with_local_attachment``
called with ``to="[EMAIL_0]"`` because tool args were never deanonymized
before reaching the Gmail API, which rejected the placeholder as an
invalid recipient.)
"""
from __future__ import annotations

from typing import Final

from app.services.bounded_cache import BoundedLRUDict
from app.services.security_filter import SecurityFilter

_FILTERS_MAXSIZE: Final[int] = 1000

# B-7 (revue 2026-06-10) : LRU + TTL d'inactivité 24 h au lieu du FIFO —
# l'éviction FIFO pouvait détruire le vault PII d'une conversation ENCORE
# ACTIVE sous charge (placeholders [EMAIL_0] du contexte LLM devenant
# irrésolubles → le bug Gmail du 2026-05-07 qui renaissait).
_filters: BoundedLRUDict = BoundedLRUDict(
    maxsize=_FILTERS_MAXSIZE, ttl_seconds=24 * 3600,
)


def get_filter(conversation_id: str) -> SecurityFilter:
    """Return the SecurityFilter for ``conversation_id``, creating one
    on first access. Same lifecycle as ``setdefault``."""
    return _filters.setdefault(conversation_id, SecurityFilter())


def discard_filter(conversation_id: str) -> None:
    """Drop the filter for ``conversation_id`` (called on conversation end)."""
    _filters.pop(conversation_id, None)


def filter_count() -> int:
    """Return how many conversations currently have a registered filter."""
    return len(_filters)
