# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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
        """Store or update credentials for user_id."""
        with self._lock:
            if credentials_json:
                self._data[user_id] = (credentials_json, time.monotonic())
            else:
                self._data.pop(user_id, None)

    def get(self, user_id: str) -> Optional[str]:
        """Return credentials_json for user_id, or None if absent/expired."""
        with self._lock:
            entry = self._data.get(user_id)
            if not entry:
                return None
            creds, ts = entry
            if time.monotonic() - ts > self._TTL:
                del self._data[user_id]
                return None
            return creds

    def clear(self, user_id: str) -> None:
        """Remove credentials for user_id (logout / revoke)."""
        with self._lock:
            self._data.pop(user_id, None)

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
