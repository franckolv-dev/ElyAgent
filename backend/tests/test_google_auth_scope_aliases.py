# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_google_auth_scope_aliases.py
# @brief      Fix 2026-07-18 — identity aliases filtered out of rebuilt Credentials
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Regression tests for the 2026-07-18 refresh-scope-warning fix.

Symptom : google-auth 2.49.x logged
« Not all requested scopes were granted by the authorization server,
missing scopes email. » at EVERY token refresh. Benign (this version
keeps the requested scopes as granted), but it polluted a real diagnosis
on 18/07 by landing in the middle of a gmail_list_emails call.

Root cause : the stored credentials dict carries the short identity
aliases (``openid``, ``email``) requested at the initial consent (see
SCOPES in google_auth.py — needed for /userinfo account identification).
At refresh time Google reports granted scopes in canonical form
(``…/auth/userinfo.email``), so google-auth flags the alias ``email`` as
"missing". ``build_credentials`` now drops the identity aliases when
rebuilding the ``Credentials`` object ; real Google API scopes pass
through verbatim. Counterpart of OAUTHLIB_RELAX_TOKEN_SCOPE, which
relaxes the same alias mismatch during the initial authorization flow.
"""
from __future__ import annotations

import json

import pytest

from app.services.google_auth import _serialize_refreshed, build_credentials

GMAIL = "https://www.googleapis.com/auth/gmail.modify"
DRIVE = "https://www.googleapis.com/auth/drive"


@pytest.fixture
def fake_oauth_client(monkeypatch):
    """Stub _get_oauth_client so tests never touch the DB."""
    async def _fake_oauth():
        return ("test-cid", "test-cs", "http://localhost/cb")
    monkeypatch.setattr("app.services.google_auth._get_oauth_client", _fake_oauth)


@pytest.mark.asyncio
async def test_identity_aliases_filtered_from_rebuilt_credentials(fake_oauth_client):
    """``openid``/``email`` must NOT reach the Credentials constructor —
    google-auth compares them against the canonical forms Google returns
    at refresh, and logs a spurious "missing scopes" warning every time."""
    creds = await build_credentials({
        "token": "ya29.token",
        "refresh_token": "rt-xyz",
        "scopes": ["openid", "email", GMAIL],
    })
    assert creds.scopes == [GMAIL]


@pytest.mark.asyncio
async def test_missing_scopes_key_stays_none(fake_oauth_client):
    """Rows without a ``scopes`` key must keep scopes=None (google-auth
    then skips the requested-vs-granted comparison entirely)."""
    creds = await build_credentials({
        "token": "ya29.token",
        "refresh_token": "rt-xyz",
    })
    assert creds.scopes is None


@pytest.mark.asyncio
async def test_serialize_refreshed_persists_filtered_scopes(fake_oauth_client):
    """``_serialize_refreshed`` persists ``creds.scopes`` : after the
    filter the stored dict converges to API scopes only. ``profile`` is
    in the alias set too (defensive — our SCOPES never requested it)."""
    creds = await build_credentials({
        "token": "ya29.token",
        "refresh_token": "rt-xyz",
        "scopes": ["openid", "email", "profile", GMAIL, DRIVE],
    })
    persisted = json.loads(_serialize_refreshed(creds))
    assert persisted["scopes"] == [GMAIL, DRIVE]
