# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_google_auth_expiry.py
# @brief      Hotfix 2026-05-28 — Google OAuth expiry storage + safety-net refresh
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Regression tests for the 2026-05-28 Google OAuth hotfix.

Symptom that motivated the fix : every morning the « Briefing quotidien 9h »
mission reported « Google non connecté », even right after the user
re-consented via the UI. Root cause :

  - ``exchange_code`` returned the credentials dict without ``expiry``
  - ``build_credentials`` reconstructed the ``Credentials`` object without
    ``expiry``
  - With ``creds.expiry is None``, ``creds.expired`` always returns False
    (google-auth contract)
  - ``get_user_credentials`` therefore never invoked ``creds.refresh()``
  - After the access token's 1 h lifespan, every Google API call 401'd
  - The except branch in ``get_user_credentials`` swallowed the error and
    returned None — tools saw « not connected »

Three patches close this :

  1. ``exchange_code`` now persists ``expiry`` as ISO-8601
  2. ``build_credentials`` restores ``expiry`` from the dict
  3. ``get_user_credentials`` refreshes whenever ``refresh_token`` is
     present AND (``expired`` OR ``expiry`` is None) — the latter is the
     legacy-row safety net so existing accounts work without re-consent
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.google_auth import (
    _parse_expiry,
    _serialize_refreshed,
    build_credentials,
    get_user_credentials,
)


# ─────────────────────────────────────────────────────────────────────────
# _parse_expiry
# ─────────────────────────────────────────────────────────────────────────


def test_parse_expiry_none_returns_none():
    assert _parse_expiry(None) is None
    assert _parse_expiry("") is None


def test_parse_expiry_naive_iso_string():
    """The format ``exchange_code`` produces (Credentials.expiry.isoformat()
    on a naive UTC datetime)."""
    out = _parse_expiry("2026-05-28T10:15:30")
    assert out == datetime(2026, 5, 28, 10, 15, 30)
    assert out.tzinfo is None  # naive — google-auth requires this


def test_parse_expiry_tz_aware_is_stripped():
    """A defensive case: if someone stored an aware ISO string by mistake,
    we strip the tz so google-auth doesn't blow up on comparison."""
    out = _parse_expiry("2026-05-28T10:15:30+00:00")
    assert out is not None
    assert out.tzinfo is None


def test_parse_expiry_passthrough_for_datetime():
    """If a datetime object lands here (defensive), keep it naive UTC."""
    aware = datetime(2026, 5, 28, 10, 15, 30, tzinfo=timezone.utc)
    out = _parse_expiry(aware)
    assert out == datetime(2026, 5, 28, 10, 15, 30)
    assert out.tzinfo is None


def test_parse_expiry_garbage_returns_none():
    """A malformed string must not crash the refresh path."""
    assert _parse_expiry("not-a-date") is None
    assert _parse_expiry({"weird": "shape"}) is None


# ─────────────────────────────────────────────────────────────────────────
# build_credentials
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_credentials_restores_expiry(monkeypatch):
    """When the stored dict carries ``expiry``, ``creds.expiry`` is set
    so ``creds.expired`` reflects the truth."""
    # Stub _get_oauth_client so the test doesn't need a real config row.
    async def _fake_oauth():
        return ("test-cid", "test-cs", "http://localhost/cb")

    monkeypatch.setattr(
        "app.services.google_auth._get_oauth_client", _fake_oauth,
    )

    past = (datetime.utcnow() - timedelta(hours=2)).isoformat()
    creds = await build_credentials({
        "token": "ya29.token",
        "refresh_token": "rt-xyz",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["calendar"],
        "expiry": past,
    })
    assert creds.expiry is not None
    assert creds.expired is True
    assert creds.refresh_token == "rt-xyz"


@pytest.mark.asyncio
async def test_build_credentials_handles_missing_expiry_gracefully(monkeypatch):
    """Legacy rows have no ``expiry`` key — must not raise, expiry stays None."""
    async def _fake_oauth():
        return ("test-cid", "test-cs", "http://localhost/cb")
    monkeypatch.setattr(
        "app.services.google_auth._get_oauth_client", _fake_oauth,
    )
    creds = await build_credentials({
        "token": "ya29.token",
        "refresh_token": "rt-xyz",
        "scopes": [],
        # No "expiry" key at all
    })
    assert creds.expiry is None
    # google-auth contract: expiry=None → expired=False
    assert creds.expired is False


# ─────────────────────────────────────────────────────────────────────────
# get_user_credentials — safety net for legacy rows (no expiry)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_credentials_returns_none_on_empty_input():
    assert await get_user_credentials(None) is None
    assert await get_user_credentials("") is None


@pytest.mark.asyncio
async def test_legacy_row_no_expiry_triggers_refresh(monkeypatch):
    """The actual regression : a stored dict WITHOUT expiry but WITH a
    refresh_token must trigger a refresh, not be silently skipped.

    Pre-hotfix : ``creds.expired`` was False (because expiry=None), so
    the refresh branch never fired and the next API call 401'd. The
    hotfix adds an explicit ``expiry is None and refresh_token`` clause."""
    async def _fake_oauth():
        return ("cid", "cs", "http://x")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)

    refresh_called = []

    class _FakeCreds:
        token = "stale"
        refresh_token = "rt-xyz"
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = ["calendar"]
        expiry = None  # the legacy bug shape

        @property
        def expired(self):
            return False  # google-auth behaviour when expiry is None

        def refresh(self, request):
            refresh_called.append(True)
            self.token = "fresh"
            self.expiry = datetime.utcnow() + timedelta(hours=1)

    async def _fake_build(creds_dict):
        return _FakeCreds()

    monkeypatch.setattr("app.services.google_auth.build_credentials", _fake_build)

    creds = await get_user_credentials('{"token":"stale","refresh_token":"rt-xyz"}')
    assert creds is not None
    assert refresh_called == [True], (
        "Refresh MUST be triggered when expiry is None but refresh_token exists "
        "— this is the legacy-row safety net introduced by the 2026-05-28 hotfix"
    )
    assert creds.token == "fresh"


@pytest.mark.asyncio
async def test_expired_with_refresh_token_still_refreshes(monkeypatch):
    """Normal path (post-hotfix new rows): expiry set, token expired, refresh."""
    async def _fake_oauth():
        return ("cid", "cs", "http://x")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)

    refresh_called = []

    class _FakeCreds:
        token = "stale"
        refresh_token = "rt-xyz"
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = ["calendar"]
        expiry = datetime.utcnow() - timedelta(hours=2)

        @property
        def expired(self):
            return True

        def refresh(self, request):
            refresh_called.append(True)
            self.token = "fresh"
            self.expiry = datetime.utcnow() + timedelta(hours=1)

    async def _fake_build(creds_dict):
        return _FakeCreds()

    monkeypatch.setattr("app.services.google_auth.build_credentials", _fake_build)

    creds = await get_user_credentials('{"token":"stale","refresh_token":"rt-xyz","expiry":"x"}')
    assert refresh_called == [True]
    assert creds.token == "fresh"


@pytest.mark.asyncio
async def test_no_refresh_token_means_no_refresh_attempted(monkeypatch):
    """If the user never granted offline access, there's no refresh_token —
    we must NOT try to refresh (would crash with a misleading error)."""
    async def _fake_oauth():
        return ("cid", "cs", "http://x")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)

    refresh_called = []

    class _FakeCreds:
        token = "stale"
        refresh_token = None
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = []
        expiry = None

        @property
        def expired(self):
            return False

        def refresh(self, request):
            refresh_called.append(True)

    async def _fake_build(creds_dict):
        return _FakeCreds()

    monkeypatch.setattr("app.services.google_auth.build_credentials", _fake_build)

    creds = await get_user_credentials('{"token":"stale"}')
    assert refresh_called == []  # never attempted
    assert creds is not None


@pytest.mark.asyncio
async def test_refresh_failure_returns_stale_creds_not_none(monkeypatch):
    """If the refresh round-trip fails (network, revoked, etc.), we return
    the stale creds so the API call surfaces the real Google error message
    instead of the misleading « Google non connecté »."""
    async def _fake_oauth():
        return ("cid", "cs", "http://x")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)

    class _FakeCreds:
        token = "stale"
        refresh_token = "rt-revoked"
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = []
        expiry = None

        @property
        def expired(self):
            return False

        def refresh(self, request):
            raise Exception("invalid_grant: refresh token revoked")

    async def _fake_build(creds_dict):
        return _FakeCreds()

    monkeypatch.setattr("app.services.google_auth.build_credentials", _fake_build)

    creds = await get_user_credentials('{"token":"stale","refresh_token":"rt-revoked"}')
    assert creds is not None  # NOT None — let the tool see the 401
    assert creds.token == "stale"


# ─────────────────────────────────────────────────────────────────────────
# _serialize_refreshed (round-trip with build_credentials)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_serialize_refreshed_roundtrips_via_build(monkeypatch):
    """A freshly-refreshed Credentials object → JSON → back via
    build_credentials must preserve token, refresh_token, scopes, expiry."""
    async def _fake_oauth():
        return ("cid", "cs", "http://x")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)

    expiry = datetime(2026, 5, 28, 12, 16, 22)
    fake_creds = SimpleNamespace(
        token="new-token",
        refresh_token="rt-xyz",
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["calendar", "drive"],
        expiry=expiry,
    )
    serialized = _serialize_refreshed(fake_creds)
    import json
    parsed = json.loads(serialized)
    assert parsed["token"] == "new-token"
    assert parsed["refresh_token"] == "rt-xyz"
    assert parsed["scopes"] == ["calendar", "drive"]
    assert parsed["expiry"] == "2026-05-28T12:16:22"

    # And it deserialises cleanly through build_credentials
    creds = await build_credentials(parsed)
    assert creds.expiry == expiry
    assert creds.token == "new-token"
