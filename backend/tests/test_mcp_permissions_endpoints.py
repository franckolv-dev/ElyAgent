# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_permissions_endpoints.py
# @brief      Endpoints admin des permissions MCP par utilisateur (mcp.py).
# @license    MIT
# =============================================================================
"""Tests des endpoints ``/admin/mcp/servers/{id}/permissions``.

L'admin est le SEUL à pouvoir ouvrir un serveur d'instance à un autre
utilisateur : « Toujours autoriser » (HITL) ne peut jamais écrire de règle
pour un non-admin refusé avant le HITL. On vérifie ici l'aller-retour
create/list/delete + le bout-en-bout avec l'ACL (une règle server-wide
créée par l'endpoint débloque bien check_mcp_tool_access).

Les handlers sont appelés directement (hermétique — pas de TestClient, pas
de JWT). require_admin est court-circuité en passant un User admin explicite.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select


async def _ensure_user(uid: str, role: str = "user") -> str:
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        if await db.get(User, uid) is None:
            db.add(User(id=uid, username=uid, email=f"{uid}@test.local",
                        hashed_password="x", role=role))
            await db.commit()
    return uid


async def _admin_user(uid: str):
    """User admin réel (les handlers lisent admin.id pour granted_by)."""
    from app.database import async_session
    from app.models.user import User
    await _ensure_user(uid, role="admin")
    async with async_session() as db:
        return await db.get(User, uid)


@pytest_asyncio.fixture
async def make_server():
    """Factory : MCPServer d'instance + un MCPTool. Nettoyage en teardown."""
    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer, MCPTool

    await init_db()
    created: list[str] = []

    async def _make(*, scope="instance", remote="translate_pdf_folder", risk="medium"):
        slug = f"perm_{uuid.uuid4().hex[:8]}"
        async with async_session() as db:
            srv = MCPServer(name=slug, slug=slug, transport="streamable_http",
                            url="https://x/mcp", scope=scope, trust_state="active",
                            kill_switch=False, enabled=True)
            db.add(srv)
            await db.commit()
            await db.refresh(srv)
            local = f"mcp__{slug}__{remote}"
            tool = MCPTool(server_id=srv.id, remote_name=remote, local_name=local,
                           risk_level=risk, enabled=False)
            db.add(tool)
            await db.commit()
            await db.refresh(tool)
            created.append(srv.id)
            return srv, tool, local

    yield _make

    from app.database import async_session as _s
    from app.models.mcp_server import (
        MCPServer as _S, MCPTool as _T, MCPToolPermission as _P,
    )
    async with _s() as db:
        for sid in created:
            for p in (await db.execute(select(_P).where(_P.server_id == sid))).scalars().all():
                await db.delete(p)
            for t in (await db.execute(select(_T).where(_T.server_id == sid))).scalars().all():
                await db.delete(t)
            srv = await db.get(_S, sid)
            if srv:
                await db.delete(srv)
        await db.commit()


# ── create ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_server_wide_permission(make_server):
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    wife = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    out = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=wife, tool_id=None, decision="allow"), admin=admin,
    )
    assert out.user_id == wife
    assert out.tool_id is None            # règle « tout le serveur »
    assert out.decision == "allow"
    assert out.granted_by == admin.id
    assert out.tool_name is None


@pytest.mark.asyncio
async def test_create_tool_specific_permission_sets_tool_name(make_server):
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv, tool, _local = await make_server(remote="translate_pdf_folder")
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    out = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, tool_id=tool.id, decision="deny"), admin=admin,
    )
    assert out.tool_id == tool.id
    assert out.tool_name == "translate_pdf_folder"
    assert out.decision == "deny"


@pytest.mark.asyncio
async def test_create_is_upsert(make_server):
    """Une 2e création pour (user, serveur, tool_id) remplace la décision."""
    from app.routers.mcp import (
        MCPPermissionCreate, create_mcp_server_permission,
        list_mcp_server_permissions,
    )

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    first = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, decision="allow"), admin=admin,
    )
    second = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, decision="deny"), admin=admin,
    )
    assert first.id == second.id          # même ligne, pas de doublon
    assert second.decision == "deny"
    rows = await list_mcp_server_permissions(srv.id)
    assert len([r for r in rows if r.user_id == user]) == 1


@pytest.mark.asyncio
async def test_create_accepts_ask_decision(make_server):
    """« ask » est une décision valide : accès accordé mais HITL préservé selon
    le risque (voir test ACL dédié)."""
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")
    out = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, decision="ask"), admin=admin,
    )
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_create_rejects_bad_decision(make_server):
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc:
        await create_mcp_server_permission(
            srv.id, MCPPermissionCreate(user_id=user, decision="allow_task"), admin=admin,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_unknown_user_404(make_server):
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc:
        await create_mcp_server_permission(
            srv.id, MCPPermissionCreate(user_id="ghost_user", decision="allow"), admin=admin,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_unknown_server_404(make_server):
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc:
        await create_mcp_server_permission(
            "no-such-server", MCPPermissionCreate(user_id=user, decision="allow"), admin=admin,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_tool_from_other_server_404(make_server):
    """tool_id qui n'appartient pas au serveur ⇒ 404 (pas de fuite inter-serveur)."""
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission

    srv_a, _tool_a, _ = await make_server()
    _srv_b, tool_b, _ = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc:
        await create_mcp_server_permission(
            srv_a.id, MCPPermissionCreate(user_id=user, tool_id=tool_b.id, decision="allow"), admin=admin,
        )
    assert exc.value.status_code == 404


# ── list ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_returns_rules_with_user_details(make_server):
    from app.routers.mcp import (
        MCPPermissionCreate, create_mcp_server_permission,
        list_mcp_server_permissions,
    )

    srv, tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, tool_id=None, decision="allow"), admin=admin,
    )
    await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, tool_id=tool.id, decision="deny"), admin=admin,
    )
    rows = await list_mcp_server_permissions(srv.id)
    assert len(rows) == 2
    for r in rows:
        assert r.username == user
        assert r.email == f"{user}@test.local"
    # server-wide sans tool_name, tool-specific avec.
    assert {r.tool_name for r in rows} == {None, "translate_pdf_folder"}


@pytest.mark.asyncio
async def test_list_unknown_server_404():
    from app.routers.mcp import list_mcp_server_permissions
    with pytest.raises(HTTPException) as exc:
        await list_mcp_server_permissions("no-such-server")
    assert exc.value.status_code == 404


# ── delete ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_removes_rule(make_server):
    from app.routers.mcp import (
        MCPPermissionCreate, create_mcp_server_permission,
        delete_mcp_server_permission, list_mcp_server_permissions,
    )

    srv, _tool, _local = await make_server()
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    user = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    created = await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=user, decision="allow"), admin=admin,
    )
    res = await delete_mcp_server_permission(srv.id, created.id)
    assert res["status"] == "deleted"
    rows = await list_mcp_server_permissions(srv.id)
    assert all(r.id != created.id for r in rows)


@pytest.mark.asyncio
async def test_delete_unknown_rule_404(make_server):
    from app.routers.mcp import delete_mcp_server_permission

    srv, _tool, _local = await make_server()
    with pytest.raises(HTTPException) as exc:
        await delete_mcp_server_permission(srv.id, "no-such-perm")
    assert exc.value.status_code == 404


# ── bout-en-bout : l'endpoint débloque bien l'ACL ────────────────────────────

@pytest.mark.asyncio
async def test_endpoint_grant_unblocks_acl(make_server):
    """Le scénario réel : sans règle, l'épouse est refusée ; après un grant
    server-wide via l'endpoint, check_mcp_tool_access la laisse passer."""
    from app.routers.mcp import MCPPermissionCreate, create_mcp_server_permission
    from app.services.mcp_acl import check_mcp_tool_access

    srv, _tool, local = await make_server(remote="translate_pdf_folder", risk="medium")
    admin = await _admin_user(f"adm_{uuid.uuid4().hex[:6]}")
    wife = await _ensure_user(f"u_{uuid.uuid4().hex[:6]}")

    # Avant : refusée (serveur d'instance, non-admin, aucune règle).
    assert (await check_mcp_tool_access(wife, local, is_admin=False)).allowed is False

    await create_mcp_server_permission(
        srv.id, MCPPermissionCreate(user_id=wife, tool_id=None, decision="allow"), admin=admin,
    )
    # Après : autorisée.
    assert (await check_mcp_tool_access(wife, local, is_admin=False)).allowed is True
