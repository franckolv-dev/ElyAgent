# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_oauth_foundation.py
# @brief      Client MCP v2 — J1 : socle OAuth (bundle Vault + resolve oauth2)
# @license    Elastic License 2.0
# =============================================================================
"""Tests du socle OAuth (J1) : stockage/lecture du bundle dans le Vault du
propriétaire + branche ``oauth2`` de ``resolve_user_headers``.

Invariants vérifiés :
* round-trip bundle store/load (chiffré dans le Vault, jamais en clair ailleurs) ;
* ``resolve_user_headers`` renvoie un Bearer depuis le bundle, None si non connecté ;
* fail-closed : Vault verrouillé ⇒ ``PermissionError`` (pas de contournement) ;
* purge (``clear_oauth_bundle``) ⇒ le secret disparaît ;
* le modèle ``MCPServer`` porte bien les colonnes OAuth non secrètes (J1) ;
* le flag ``mcp_oauth_enabled`` est OFF par défaut (rétrocompat stricte).
"""
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


async def _make_user(uid: str) -> None:
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}",
                    email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()


async def _unlocked_vault(uid: str):
    # Le singleton — c'est lui que `mcp_credentials` utilise via get_vault_service().
    from app.services.vault_service import get_vault_service
    svc = get_vault_service()
    await svc.unlock_vault(uid, "correct-horse-battery")
    return svc


def _srv(slug: str, ref: str | None, auth_type: str = "oauth2") -> SimpleNamespace:
    return SimpleNamespace(slug=slug, auth_type=auth_type, credential_ref=ref,
                           auth_header_name=None)


_BUNDLE = {
    "access_token": "at-xyz",
    "refresh_token": "rt-abc",
    "expires_at": 9999999999,
    "token_type": "Bearer",
    "scope": "repo read:user",
    "obtained_at": 1719600000,
}


@pytest.mark.asyncio
async def test_store_then_load_roundtrip():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    svc = await _unlocked_vault(uid)

    ref = await cred.store_oauth_bundle(uid, "github", _BUNDLE)
    assert ref == cred.oauth_label("github") == "mcp::github::oauth"

    loaded = await cred.load_oauth_bundle(uid, _srv("github", ref))
    assert loaded == _BUNDLE

    # Le label vit bien dans le Vault, distinct du label `credential`.
    labels = {e["label"] for e in await svc.list_secrets(uid)}
    assert "mcp::github::oauth" in labels
    assert cred.credential_label("github") not in labels


@pytest.mark.asyncio
async def test_resolve_user_headers_oauth2_bearer():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    await _unlocked_vault(uid)

    ref = await cred.store_oauth_bundle(uid, "notion", _BUNDLE)
    headers = await cred.resolve_user_headers(uid, _srv("notion", ref))
    assert headers == {"Authorization": "Bearer at-xyz"}


@pytest.mark.asyncio
async def test_resolve_returns_none_when_not_connected():
    # oauth2 mais pas de credential_ref ⇒ pas encore connecté ⇒ None.
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    await _unlocked_vault(uid)
    assert await cred.resolve_user_headers(uid, _srv("linear", None)) is None
    assert await cred.load_oauth_bundle(uid, _srv("linear", None)) is None


@pytest.mark.asyncio
async def test_resolve_none_when_bundle_missing_access_token():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    await _unlocked_vault(uid)
    ref = await cred.store_oauth_bundle(uid, "empty", {"refresh_token": "rt"})
    assert await cred.resolve_user_headers(uid, _srv("empty", ref)) is None


@pytest.mark.asyncio
async def test_load_ignores_non_oauth_servers():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    await _unlocked_vault(uid)
    ref = await cred.store_oauth_bundle(uid, "bearer-srv", _BUNDLE)
    # auth_type=bearer ⇒ load_oauth_bundle ne touche pas au bundle.
    assert await cred.load_oauth_bundle(uid, _srv("bearer-srv", ref, "bearer")) is None


@pytest.mark.asyncio
async def test_fail_closed_when_vault_locked():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    svc = await _unlocked_vault(uid)
    ref = await cred.store_oauth_bundle(uid, "gh", _BUNDLE)

    await svc.lock_vault(uid)
    with pytest.raises(PermissionError):
        await cred.load_oauth_bundle(uid, _srv("gh", ref))
    with pytest.raises(PermissionError):
        await cred.resolve_user_headers(uid, _srv("gh", ref))


@pytest.mark.asyncio
async def test_clear_oauth_bundle_purges_secret():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    await _unlocked_vault(uid)
    ref = await cred.store_oauth_bundle(uid, "purge", _BUNDLE)
    srv = _srv("purge", ref)

    await cred.clear_oauth_bundle(uid, srv)
    # Secret disparu ⇒ get_secret lève KeyError, propagée par load.
    with pytest.raises(KeyError):
        await cred.load_oauth_bundle(uid, srv)


@pytest.mark.asyncio
async def test_corrupt_bundle_treated_as_absent():
    uid = f"oauth-{uuid.uuid4().hex[:8]}"
    await _make_user(uid)
    svc = await _unlocked_vault(uid)
    # On écrit du JSON invalide directement sous le label oauth.
    await svc.store_secret(uid, cred.oauth_label("corrupt"), "{not-json")
    srv = _srv("corrupt", cred.oauth_label("corrupt"))
    assert await cred.load_oauth_bundle(uid, srv) is None


def test_model_has_oauth_columns():
    from app.models.mcp_server import MCPServer
    cols = set(MCPServer.__table__.columns.keys())
    assert {"oauth_metadata_json", "oauth_client_id",
            "oauth_client_secret_ref", "oauth_scopes"} <= cols


def test_oauth_flag_off_by_default():
    from app.config import Settings
    s = Settings()
    assert s.mcp_oauth_enabled is False
    assert s.mcp_oauth_redirect_uri.endswith("/api/mcp/oauth/callback")
