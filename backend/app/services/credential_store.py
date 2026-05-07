# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/credential_store.py
# @brief      Server-side credential store for Google OAuth tokens
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Server-side credential store for Google OAuth tokens.

Credentials are kept in process memory, indexed by user_id.
They are NEVER stored in the LangGraph agent state, preventing
exposure in logs, event streams, or LLM context (SEC-1).

Lifecycle:
- set()   : called when a WebSocket session starts (or credentials refreshed)
- get()   : called by tool executor nodes at execution time
- clear() : called on logout or when credentials are revoked
"""
from __future__ import annotations

import threading
import time
from typing import Optional


class _CredentialStore:
    """Thread-safe in-memory store: user_id → google_credentials_json."""

    _TTL = 3600.0  # evict entries not refreshed for 1 hour

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {user_id: (credentials_json, last_updated_ts)}
        self._data: dict[str, tuple[str, float]] = {}

    def set(self, user_id: str, credentials_json: str | None) -> None:
        """Store or update credentials for user_id.

        ``user_id`` is normalized to ``str`` so callers passing a UUID object
        (SQLAlchemy column) and callers passing a string (JWT ``sub``) hit
        the same cache entry. Bug discovered 2026-05-07.
        """
        key = str(user_id)
        with self._lock:
            if credentials_json:
                self._data[key] = (credentials_json, time.monotonic())
            else:
                self._data.pop(key, None)

    def get(self, user_id: str) -> Optional[str]:
        """Return credentials_json for user_id, or None if absent/expired."""
        key = str(user_id)
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            creds, ts = entry
            if time.monotonic() - ts > self._TTL:
                del self._data[key]
                return None
            return creds

    def clear(self, user_id: str) -> None:
        """Remove credentials for user_id (logout / revoke)."""
        key = str(user_id)
        with self._lock:
            self._data.pop(key, None)

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.monotonic()
        with self._lock:
            expired = [uid for uid, (_, ts) in self._data.items()
                       if now - ts > self._TTL]
            for uid in expired:
                del self._data[uid]
        return len(expired)


_store = _CredentialStore()


def get_credential_store() -> _CredentialStore:
    return _store
