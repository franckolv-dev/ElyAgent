# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_oauth_ui_backend.py
# @brief      Client MCP v2 — J4 : surface backend de l'UI OAuth (schéma + /status)
# @license    MIT
# =============================================================================
"""Tests J4 backend : exposition NON secrète d'auth_type/oauth_client_id/
oauth_scopes (jamais le secret/cache), endpoint /status per-user, et
persistance auth_type via create/update."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.services import mcp_credentials as cred


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


# ── Redaction : MCPServerOut expose la config OAuth, JAMAIS le secret ─────────

def test_serverout_exposes_oauth_config_but_never_secret():
    from app.routers.mcp import MCPServerOut
    from app.models.mcp_server import MCPServer

    srv = MCPServer(
        id="s1", name="GH", slug="gh", transport="streamable_http",
        url="https://mcp.example/x", enabled=True, auth_type="oauth2",
        oauth_client_id="cid-123", oauth_scopes="repo read:user",
        oauth_client_secret_ref="enc:gcm:SECRET", oauth_metadata_json='{"token_endpoint":"x"}',
    )
    dumped = MCPServerOut.model_validate(srv).model_dump()
    assert dumped["auth_type"] == "oauth2"
    assert dumped["oauth_client_id"] == "cid-123"
    assert dumped["oauth_scopes"] == "repo read:user"
    # Invariant cadrage §13 : aucun secret/cache ne sort par l'API.
    assert "oauth_client_secret_ref" not in dumped
    assert "oauth_metadata_json" not in dumped
    assert "credential_ref" not in dumped


# ── create / update persistent auth_type sans casser les serveurs stdio ──────

@pytest.mark.asyncio
async def test_create_oauth_server_persists_auth_type():
    from app.routers.mcp import MCPServerCreate, create_mcp_server
    from app.database import async_session
    from app.models.mcp_server import MCPServer

    slug = f"gh_{uuid.uuid4().hex[:6]}"
    body = MCPServerCreate(
        name="GH", slug=slug, transport="streamable_http",
        url="https://mcp.example/x", auth_type="oauth2",
        oauth_client_id="cid-xyz", oauth_scopes="repo", enabled=False)
    out = await create_mcp_server(body, _=None)
    assert out.auth_type == "oauth2"
    assert out.oauth_client_id == "cid-xyz"
    async with async_session() as db:
        srv = (await db.execute(
            __import__("sqlalchemy").select(MCPServer).where(MCPServer.slug == slug)
        )).scalar_one()
    assert srv.auth_type == "oauth2"
    assert srv.oauth_scopes == "repo"


@pytest.mark.asyncio
async def test_create_stdio_server_defaults_auth_none():
    # Sans auth_type fourni, exclude_none ⇒ défaut modèle "none" (pré-J4 préservé).
    from app.routers.mcp import MCPServerCreate, create_mcp_server
    slug = f"fs_{uuid.uuid4().hex[:6]}"
    body = MCPServerCreate(name="FS", slug=slug, transport="stdio",
                           command="echo", enabled=False)
    out = await create_mcp_server(body, _=None)
    assert (out.auth_type or "none") == "none"
    assert out.oauth_client_id is None


# ── /status (per-user, lecture seule) ────────────────────────────────────────

def _settings(enabled=True):
    return SimpleNamespace(mcp_oauth_enabled=enabled,
                           mcp_oauth_redirect_uri="https://ely/api/mcp/oauth/callback",
                           frontend_url="https://ely")


async def _make_server(*, auth_type="oauth2", scope="instance", owner=None, slug=None):
    from app.database import async_session
    from app.models.mcp_server import MCPServer
    sid = f"srv-{uuid.uuid4().hex[:8]}"
    slug = slug or f"s{uuid.uuid4().hex[:6]}"
    async with async_session() as db:
        db.add(MCPServer(id=sid, name="GH", slug=slug, transport="streamable_http",
                         url="https://mcp/x", auth_type=auth_type, scope=scope,
                         owner_user_id=owner,
                         credential_ref=cred.oauth_label(slug) if auth_type == "oauth2" else None))
        await db.commit()
    return sid, slug


@pytest.mark.asyncio
async def test_status_404_when_flag_off(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    monkeypatch.setattr(r, "get_settings", lambda: _settings(enabled=False))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_status("x", current_user=SimpleNamespace(id="u"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_non_oauth_server(monkeypatch):
    from app.routers import mcp_oauth as r
    uid = f"o-{uuid.uuid4().hex[:8]}"; await _make_user(uid)
    sid, _ = await _make_server(auth_type="none")
    monkeypatch.setattr(r, "get_settings", lambda: _settings(enabled=True))
    out = await r.oauth_status(sid, current_user=SimpleNamespace(id=uid))
    assert out == {"oauth": False, "connected": False}


@pytest.mark.asyncio
async def test_status_oauth_not_connected_then_connected(monkeypatch):
    from app.routers import mcp_oauth as r
    uid = f"o-{uuid.uuid4().hex[:8]}"; await _make_user(uid); await _unlock(uid)
    sid, slug = await _make_server(auth_type="oauth2")
    monkeypatch.setattr(r, "get_settings", lambda: _settings(enabled=True))

    out = await r.oauth_status(sid, current_user=SimpleNamespace(id=uid))
    assert out["oauth"] is True and out["connected"] is False

    await cred.store_oauth_bundle(uid, slug, {"access_token": "AT", "scope": "repo"})
    out2 = await r.oauth_status(sid, current_user=SimpleNamespace(id=uid))
    assert out2["connected"] is True
    assert out2["scope"] == "repo"


@pytest.mark.asyncio
async def test_status_other_users_personal_server_is_404(monkeypatch):
    from fastapi import HTTPException
    from app.routers import mcp_oauth as r
    owner = f"own-{uuid.uuid4().hex[:8]}"; await _make_user(owner)
    intruder = f"int-{uuid.uuid4().hex[:8]}"; await _make_user(intruder)
    sid, _ = await _make_server(auth_type="oauth2", scope="user", owner=owner)
    monkeypatch.setattr(r, "get_settings", lambda: _settings(enabled=True))
    with pytest.raises(HTTPException) as exc:
        await r.oauth_status(sid, current_user=SimpleNamespace(id=intruder))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_locked_vault(monkeypatch):
    from app.routers import mcp_oauth as r
    uid = f"o-{uuid.uuid4().hex[:8]}"; await _make_user(uid)
    svc = await _unlock(uid)
    sid, slug = await _make_server(auth_type="oauth2")
    await cred.store_oauth_bundle(uid, slug, {"access_token": "AT"})
    await svc.lock_vault(uid)
    monkeypatch.setattr(r, "get_settings", lambda: _settings(enabled=True))
    out = await r.oauth_status(sid, current_user=SimpleNamespace(id=uid))
    assert out == {"oauth": True, "connected": False, "locked": True}
