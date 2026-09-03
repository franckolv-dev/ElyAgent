# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_oauth_refresh.py
# @brief      Client MCP v2 — J3 : refresh / rotation / révocation OAuth.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests J3 : refresh proactif + rotation, MCPAuthRequired, révocation +
endpoint de déconnexion par utilisateur."""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.services import mcp_credentials as cred
from app.services import mcp_oauth


# ── Client HTTP factice ──────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("pas de JSON")
        return self._data


class _Client:
    def __init__(self, post_map=None):
        self.post_map = post_map or {}
        self.posted = []

    async def post(self, url, json=None, data=None, headers=None):
        self.posted.append((url, data))
        return self.post_map.get(url, _Resp(404))

    async def aclose(self):
        pass


# ── Service : refresh / revoke / bundle ──────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_access_token_success():
    client = _Client(post_map={
        "https://as/token": _Resp(200, {"access_token": "newAT", "expires_in": 3600})})
    token = await mcp_oauth.refresh_access_token(
        client, "https://as/token", refresh_token="RT", client_id="cid",
        resource="https://mcp")
    assert token["access_token"] == "newAT"
    _, data = client.posted[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "RT"
    assert data["resource"] == "https://mcp"


@pytest.mark.asyncio
async def test_refresh_access_token_rejected_raises():
    client = _Client(post_map={"https://as/token": _Resp(400, {"error": "invalid_grant"})})
    with pytest.raises(mcp_oauth.MCPOAuthError):
        await mcp_oauth.refresh_access_token(
            client, "https://as/token", refresh_token="RT", client_id="cid",
            resource="https://mcp")


@pytest.mark.asyncio
async def test_revoke_token_outcomes():
    ok = _Client(post_map={"https://as/revoke": _Resp(200, {})})
    assert await mcp_oauth.revoke_token(ok, "https://as/revoke", "RT") is True
    ko = _Client(post_map={"https://as/revoke": _Resp(503, {})})
    assert await mcp_oauth.revoke_token(ko, "https://as/revoke", "RT") is False


def test_build_bundle_rotation_carries_prev_refresh():
    # Réponse sans refresh_token → on conserve l'ancien.
    b = mcp_oauth.build_bundle({"access_token": "AT2", "expires_in": 60},
                               now=1000, prev_refresh_token="RT_old")
    assert b["refresh_token"] == "RT_old"
    # Réponse AVEC refresh_token → rotation.
    b2 = mcp_oauth.build_bundle({"access_token": "AT2", "refresh_token": "RT_new"},
                                now=1000, prev_refresh_token="RT_old")
    assert b2["refresh_token"] == "RT_new"


def test_discover_meta_includes_revocation_endpoint():
    # La clé est désormais propagée (J3) pour permettre la révocation.
    import inspect
    src = inspect.getsource(mcp_oauth.discover_authorization_server)
    assert "revocation_endpoint" in src


# ── Credentials refresh-aware (Vault + DB) ───────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _make_user(uid: str):
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@t.local",
                    hashed_password="x"))
        await db.commit()


async def _unlock(uid: str):
    from app.services.vault_service import get_vault_service
    svc = get_vault_service()
    await svc.unlock_vault(uid, "pw")
    return svc


_META = {"token_endpoint": "https://as/token", "resource": "https://mcp",
         "revocation_endpoint": "https://as/revoke"}


def _srv(slug, *, expires_at, refresh_token="RT", with_ref=True):
    import json
    return SimpleNamespace(
        slug=slug, auth_type="oauth2",
        credential_ref=cred.oauth_label(slug) if with_ref else None,
        oauth_metadata_json=json.dumps(_META), oauth_client_id="cid",
        oauth_client_secret_ref=None, allow_private_network=False,
        _expires_at=expires_at, _refresh_token=refresh_token)


@pytest.mark.asyncio
async def test_valid_token_no_refresh(monkeypatch):
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {
        "access_token": "AT", "refresh_token": "RT",
        "expires_at": int(time.time()) + 9999})

    called = {"n": 0}
    monkeypatch.setattr(mcp_oauth, "refresh_access_token",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    srv = _srv(slug, expires_at=int(time.time()) + 9999)
    headers = await cred.resolve_user_headers(uid, srv)
    assert headers == {"Authorization": "Bearer AT"}
    assert called["n"] == 0  # pas de refresh


@pytest.mark.asyncio
async def test_expired_token_refreshes_and_rotates(monkeypatch):
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {
        "access_token": "OLD", "refresh_token": "RT_old",
        "expires_at": int(time.time()) - 100})

    async def _fake_refresh(*a, **k):
        return {"access_token": "FRESH", "refresh_token": "RT_new", "expires_in": 3600}
    monkeypatch.setattr(mcp_oauth, "default_http_client", lambda **k: _Client())
    monkeypatch.setattr(mcp_oauth, "refresh_access_token", _fake_refresh)

    srv = _srv(slug, expires_at=int(time.time()) - 100)
    headers = await cred.resolve_user_headers(uid, srv)
    assert headers == {"Authorization": "Bearer FRESH"}
    # Rotation persistée dans le Vault.
    stored = await cred.load_oauth_bundle(uid, srv)
    assert stored["access_token"] == "FRESH"
    assert stored["refresh_token"] == "RT_new"


@pytest.mark.asyncio
async def test_expired_without_refresh_token_raises_auth_required(monkeypatch):
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {
        "access_token": "OLD", "expires_at": int(time.time()) - 100})
    srv = _srv(slug, expires_at=int(time.time()) - 100)
    with pytest.raises(cred.MCPAuthRequired):
        await cred.resolve_user_headers(uid, srv)


@pytest.mark.asyncio
async def test_refresh_rejected_raises_auth_required(monkeypatch):
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {
        "access_token": "OLD", "refresh_token": "RT", "expires_at": int(time.time()) - 100})

    async def _boom(*a, **k):
        raise mcp_oauth.MCPOAuthError("invalid_grant")
    monkeypatch.setattr(mcp_oauth, "default_http_client", lambda **k: _Client())
    monkeypatch.setattr(mcp_oauth, "refresh_access_token", _boom)

    srv = _srv(slug, expires_at=int(time.time()) - 100)
    with pytest.raises(cred.MCPAuthRequired):
        await cred.resolve_user_headers(uid, srv)


@pytest.mark.asyncio
async def test_purged_bundle_raises_auth_required():
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    # credential_ref pointe sur le label oauth mais aucun secret stocké.
    srv = _srv(slug, expires_at=0)
    with pytest.raises(cred.MCPAuthRequired):
        await cred.resolve_user_headers(uid, srv)


@pytest.mark.asyncio
async def test_locked_vault_fail_closed():
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    svc = await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {"access_token": "AT", "refresh_token": "RT"})
    await svc.lock_vault(uid)
    srv = _srv(slug, expires_at=int(time.time()) + 9999)
    with pytest.raises(PermissionError):
        await cred.resolve_user_headers(uid, srv)


@pytest.mark.asyncio
async def test_revoke_oauth_calls_endpoint_and_purges(monkeypatch):
    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    slug = f"s{uuid.uuid4().hex[:6]}"
    await cred.store_oauth_bundle(uid, slug, {"access_token": "AT", "refresh_token": "RT"})

    seen = {}
    async def _fake_revoke(client, endpoint, token, **k):
        seen["endpoint"] = endpoint
        seen["token"] = token
        return True
    monkeypatch.setattr(mcp_oauth, "default_http_client", lambda **k: _Client())
    monkeypatch.setattr(mcp_oauth, "revoke_token", _fake_revoke)

    srv = _srv(slug, expires_at=0)
    await cred.revoke_oauth(uid, srv)
    assert seen["endpoint"] == "https://as/revoke"
    assert seen["token"] == "RT"
    # Bundle purgé → KeyError ensuite.
    with pytest.raises(KeyError):
        await cred.load_oauth_bundle(uid, srv)


# ── Endpoint de déconnexion ──────────────────────────────────────────────────

def _fake_settings(enabled=True):
    return SimpleNamespace(mcp_oauth_enabled=enabled,
                           mcp_oauth_redirect_uri="https://ely/api/mcp/oauth/callback",
                           frontend_url="https://ely")


@pytest.mark.asyncio
async def test_disconnect_endpoint(monkeypatch):
    from app.routers import mcp_oauth as r
    from app.database import async_session
    from app.models.mcp_server import MCPServer

    uid = f"o-{uuid.uuid4().hex[:8]}"
    await _make_user(uid); await _unlock(uid)
    sid = f"srv-{uuid.uuid4().hex[:8]}"
    slug = f"s{uuid.uuid4().hex[:6]}"
    import json
    async with async_session() as db:
        db.add(MCPServer(id=sid, name="GH", slug=slug, transport="streamable_http",
                         url="https://mcp/x", auth_type="oauth2", scope="instance",
                         credential_ref=cred.oauth_label(slug),
                         oauth_metadata_json=json.dumps(_META), oauth_client_id="cid"))
        await db.commit()
    await cred.store_oauth_bundle(uid, slug, {"access_token": "AT", "refresh_token": "RT"})

    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=True))
    monkeypatch.setattr(mcp_oauth, "default_http_client", lambda **k: _Client())
    monkeypatch.setattr(mcp_oauth, "revoke_token", lambda *a, **k: _aint(True))

    out = await r.oauth_disconnect(sid, current_user=SimpleNamespace(id=uid))
    assert out["status"] == "disconnected"
    async with async_session() as db:
        srv = await db.get(MCPServer, sid)
    with pytest.raises(KeyError):
        await cred.load_oauth_bundle(uid, srv)


@pytest.mark.asyncio
async def test_disconnect_404_when_flag_off(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=False))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_disconnect("x", current_user=SimpleNamespace(id="u"))
    assert exc.value.status_code == 404


async def _aint(value):
    return value
