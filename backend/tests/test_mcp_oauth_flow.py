# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_oauth_flow.py
# @brief      Client MCP v2 — J2 : flow OAuth (découverte, PKCE, échange, endpoints)
# @license    MIT
# =============================================================================
"""Tests J2 : mécanique OAuth (service hermétique avec client HTTP factice) +
endpoints start/callback (style direct-handler, comme test_mcp_router)."""
from __future__ import annotations

import base64
import hashlib
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio

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
    def __init__(self, get_map=None, post_map=None):
        self.get_map = get_map or {}
        self.post_map = post_map or {}
        self.posted = []

    async def get(self, url):
        return self.get_map.get(url, _Resp(404))

    async def post(self, url, json=None, data=None, headers=None):
        self.posted.append((url, json, data))
        return self.post_map.get(url, _Resp(404))

    async def aclose(self):
        pass


_AS_META = {
    "issuer": "https://as.example.com",
    "authorization_endpoint": "https://as.example.com/authorize",
    "token_endpoint": "https://as.example.com/token",
    "registration_endpoint": "https://as.example.com/register",
    "scopes_supported": ["read", "write"],
}


def _discovery_client():
    return _Client(get_map={
        "https://mcp.example.com/.well-known/oauth-protected-resource":
            _Resp(200, {"authorization_servers": ["https://as.example.com"]}),
        "https://as.example.com/.well-known/oauth-authorization-server":
            _Resp(200, _AS_META),
    })


# ── PKCE ─────────────────────────────────────────────────────────────────────

def test_pkce_pair_is_s256():
    verifier, challenge = mcp_oauth.generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert "=" not in challenge


# ── Découverte ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_prm_then_as_metadata():
    meta = await mcp_oauth.discover_authorization_server(
        _discovery_client(), "https://mcp.example.com/mcp")
    assert meta["authorization_endpoint"] == "https://as.example.com/authorize"
    assert meta["token_endpoint"] == "https://as.example.com/token"
    assert meta["registration_endpoint"] == "https://as.example.com/register"
    assert meta["resource"] == "https://mcp.example.com"


@pytest.mark.asyncio
async def test_discover_falls_back_to_origin_as_own_as():
    # Pas de PRM → le serveur MCP est son propre AS (origine).
    client = _Client(get_map={
        "https://mcp.example.com/.well-known/oauth-authorization-server":
            _Resp(200, {**_AS_META, "issuer": "https://mcp.example.com"}),
    })
    meta = await mcp_oauth.discover_authorization_server(
        client, "https://mcp.example.com/mcp")
    assert meta["token_endpoint"] == "https://as.example.com/token"
    assert meta["resource"] == "https://mcp.example.com"


@pytest.mark.asyncio
async def test_discover_oidc_fallback():
    client = _Client(get_map={
        "https://mcp.example.com/.well-known/oauth-protected-resource":
            _Resp(200, {"authorization_servers": ["https://as.example.com"]}),
        # oauth-authorization-server absent → OIDC openid-configuration.
        "https://as.example.com/.well-known/openid-configuration":
            _Resp(200, _AS_META),
    })
    meta = await mcp_oauth.discover_authorization_server(
        client, "https://mcp.example.com/mcp")
    assert meta["authorization_endpoint"] == "https://as.example.com/authorize"


@pytest.mark.asyncio
async def test_discover_raises_when_nothing_found():
    with pytest.raises(mcp_oauth.MCPOAuthError):
        await mcp_oauth.discover_authorization_server(
            _Client(), "https://mcp.example.com/mcp")


# ── DCR ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_client_success_public():
    client = _Client(post_map={
        "https://as.example.com/register":
            _Resp(201, {"client_id": "abc123"}),
    })
    reg = await mcp_oauth.register_client(
        client, "https://as.example.com/register", "https://ely/cb")
    assert reg["client_id"] == "abc123"
    assert reg["client_secret"] is None
    # Client public : token_endpoint_auth_method=none demandé.
    _, body, _ = client.posted[0]
    assert body["token_endpoint_auth_method"] == "none"
    assert body["redirect_uris"] == ["https://ely/cb"]


@pytest.mark.asyncio
async def test_register_client_failure_raises():
    client = _Client(post_map={
        "https://as.example.com/register": _Resp(400, {"error": "nope"})})
    with pytest.raises(mcp_oauth.MCPOAuthError):
        await mcp_oauth.register_client(
            client, "https://as.example.com/register", "https://ely/cb")


# ── URL d'autorisation ───────────────────────────────────────────────────────

def test_build_authorization_url_params():
    meta = {"authorization_endpoint": "https://as.example.com/authorize",
            "resource": "https://mcp.example.com"}
    url = mcp_oauth.build_authorization_url(
        meta, client_id="cid", redirect_uri="https://ely/cb",
        state="st4te", code_challenge="chAl", scope="read write")
    q = parse_qs(urlsplit(url).query)
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == ["chAl"]
    assert q["state"] == ["st4te"]
    assert q["resource"] == ["https://mcp.example.com"]
    assert q["scope"] == ["read write"]
    assert q["client_id"] == ["cid"]


# ── Échange + bundle ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_code_success():
    client = _Client(post_map={
        "https://as.example.com/token":
            _Resp(200, {"access_token": "at", "refresh_token": "rt",
                        "expires_in": 3600, "token_type": "Bearer"})})
    token = await mcp_oauth.exchange_code(
        client, "https://as.example.com/token", code="c", redirect_uri="https://ely/cb",
        client_id="cid", code_verifier="ver", resource="https://mcp.example.com")
    assert token["access_token"] == "at"
    _, _, data = client.posted[0]
    assert data["grant_type"] == "authorization_code"
    assert data["code_verifier"] == "ver"
    assert data["resource"] == "https://mcp.example.com"


@pytest.mark.asyncio
async def test_exchange_code_without_access_token_raises():
    client = _Client(post_map={
        "https://as.example.com/token": _Resp(200, {"token_type": "Bearer"})})
    with pytest.raises(mcp_oauth.MCPOAuthError):
        await mcp_oauth.exchange_code(
            client, "https://as.example.com/token", code="c",
            redirect_uri="https://ely/cb", client_id="cid",
            code_verifier="ver", resource="https://mcp.example.com")


def test_build_bundle_computes_expiry():
    bundle = mcp_oauth.build_bundle(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
         "scope": "read"}, now=1_000_000)
    assert bundle["access_token"] == "at"
    assert bundle["expires_at"] == 1_003_600
    assert bundle["obtained_at"] == 1_000_000
    assert bundle["token_type"] == "Bearer"


# ── Endpoints (direct-handler) ───────────────────────────────────────────────

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


async def _make_oauth_server(uid: str, *, client_id="cid", scope="instance"):
    from app.database import async_session
    from app.models.mcp_server import MCPServer
    sid = f"srv-{uuid.uuid4().hex[:8]}"
    slug = f"oauthsrv_{uuid.uuid4().hex[:6]}"
    async with async_session() as db:
        db.add(MCPServer(id=sid, name="GH", slug=slug, transport="streamable_http",
                         url="https://mcp.example.com/mcp", auth_type="oauth2",
                         oauth_client_id=client_id, scope=scope,
                         owner_user_id=uid if scope == "user" else None))
        await db.commit()
    return sid, slug


def _fake_settings(enabled=True):
    return SimpleNamespace(
        mcp_oauth_enabled=enabled,
        mcp_oauth_redirect_uri="https://ely.local/api/mcp/oauth/callback",
        frontend_url="https://ely.local")


@pytest.mark.asyncio
async def test_start_404_when_flag_off(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=False))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_start("whatever", current_user=SimpleNamespace(id="u1"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_callback_404_when_flag_off(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=False))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_callback(code="c", state="s")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_start_then_callback_happy_path(monkeypatch):
    from app.routers import mcp_oauth as r
    from app.services import mcp_credentials, mcp_oauth as svc

    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    sid, slug = await _make_oauth_server(uid)

    # Vault déverrouillé (le callback range le bundle dans le Vault du user).
    from app.services.vault_service import get_vault_service
    await get_vault_service().unlock_vault(uid, "pw")

    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=True))
    monkeypatch.setattr(svc, "default_http_client", lambda **k: _Client())
    monkeypatch.setattr(svc, "discover_authorization_server",
                        lambda *a, **k: _async({**_AS_META, "resource": "https://mcp.example.com"}))
    monkeypatch.setattr(svc, "exchange_code",
                        lambda *a, **k: _async({"access_token": "AT", "refresh_token": "RT",
                                                "expires_in": 3600, "token_type": "Bearer"}))

    out = await r.oauth_start(sid, current_user=SimpleNamespace(id=uid))
    assert out["url"].startswith("https://as.example.com/authorize?")
    q = parse_qs(urlsplit(out["url"]).query)
    state = q["state"][0]
    assert q["resource"] == ["https://mcp.example.com"]

    resp = await r.oauth_callback(code="thecode", state=state)
    assert "mcp_oauth=connected" in resp.headers["location"]

    # Bundle rangé dans le Vault + credential_ref posé sur le serveur.
    from app.database import async_session
    from app.models.mcp_server import MCPServer
    async with async_session() as db:
        srv = await db.get(MCPServer, sid)
    assert srv.credential_ref == mcp_credentials.oauth_label(slug)
    bundle = await mcp_credentials.load_oauth_bundle(uid, srv)
    assert bundle["access_token"] == "AT"
    # State consommé (usage unique).
    assert state not in r._pending_states


@pytest.mark.asyncio
async def test_callback_rejects_unknown_state(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    monkeypatch.setattr(r, "get_settings", lambda: _fake_settings(enabled=True))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_callback(code="c", state="does-not-exist")
    assert exc.value.status_code == 400


async def _async(value):
    return value
