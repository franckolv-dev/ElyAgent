# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_acl.py
# @brief      J4 — ACL MCP : isolation multi-user, admin instance, risque→HITL.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.mcp_acl import check_mcp_tool_access


async def _ensure_user(uid: str, role: str = "user") -> str:
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        if await db.get(User, uid) is None:
            db.add(User(id=uid, username=uid, email=f"{uid}@test.local",
                        hashed_password="x", role=role))
            await db.commit()
    return uid


@pytest_asyncio.fixture
async def make_server():
    """Factory : crée un MCPServer + un MCPTool, renvoie (server, tool).
    Nettoie tout en teardown."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.mcp_server import MCPServer, MCPTool

    await init_db()
    created: list[str] = []

    async def _make(*, scope, owner=None, trust="active", kill=False,
                    risk="medium", remote="do_thing", annotations=None):
        if owner:
            await _ensure_user(owner)
        slug = f"acl_{uuid.uuid4().hex[:8]}"
        async with async_session() as db:
            srv = MCPServer(name=slug, slug=slug, transport="streamable_http",
                            url="https://x/mcp", scope=scope, owner_user_id=owner,
                            trust_state=trust, kill_switch=kill, enabled=True)
            db.add(srv)
            await db.commit()
            await db.refresh(srv)
            local = f"mcp__{slug}__{remote}"
            import json as _json
            tool = MCPTool(
                server_id=srv.id, remote_name=remote, local_name=local,
                risk_level=risk, enabled=False,
                annotations_json=_json.dumps(annotations) if annotations else None,
            )
            db.add(tool)
            await db.commit()
            created.append(srv.id)
            return srv, local

    yield _make

    from app.database import async_session as _s
    from app.models.mcp_server import MCPServer as _S, MCPTool as _T
    async with _s() as db:
        for sid in created:
            for t in (await db.execute(select(_T).where(_T.server_id == sid))).scalars().all():
                await db.delete(t)
            srv = await db.get(_S, sid)
            if srv:
                await db.delete(srv)
        await db.commit()


@pytest.mark.asyncio
async def test_user_server_owner_allowed(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner)
    d = await check_mcp_tool_access(owner, local, is_admin=False)
    assert d.allowed is True
    assert d.needs_hitl is True   # défaut "ask" → confirmation


@pytest.mark.asyncio
async def test_user_server_other_user_denied_isolation(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    other = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner)
    d = await check_mcp_tool_access(other, local, is_admin=False)
    assert d.allowed is False
    assert "autre utilisateur" in (d.reason or "")


@pytest.mark.asyncio
async def test_instance_server_admin_allowed_user_denied(make_server):
    _srv, local = await make_server(scope="instance")
    admin = await check_mcp_tool_access("admin_user", local, is_admin=True)
    assert admin.allowed is True
    user = await check_mcp_tool_access("plain_user", local, is_admin=False)
    assert user.allowed is False


@pytest.mark.asyncio
async def test_kill_switch_denies(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, kill=True)
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is False
    assert "kill" in (d.reason or "").lower()


@pytest.mark.asyncio
async def test_quarantined_server_denied(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, trust="quarantined")
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is False


@pytest.mark.asyncio
async def test_explicit_allow_skips_hitl(make_server):
    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool, MCPToolPermission
    from sqlalchemy import select

    owner = f"u_{uuid.uuid4().hex[:6]}"
    srv, local = await make_server(scope="user", owner=owner, risk="low")
    async with async_session() as db:
        tool = (await db.execute(select(MCPTool).where(MCPTool.local_name == local))).scalar_one()
        db.add(MCPToolPermission(user_id=owner, server_id=srv.id, tool_id=tool.id, decision="allow"))
        await db.commit()
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is True
    assert d.needs_hitl is False   # "allow" explicite → pas de confirmation


@pytest.mark.asyncio
async def test_unknown_tool_denied():
    d = await check_mcp_tool_access("u", "mcp__nope__ghost")
    assert d.allowed is False


# ── Consultation (lecture seule) → pas de HITL (demande Franck 2026-06-20) ────
@pytest.mark.asyncio
async def test_readonly_tool_skips_hitl_even_if_medium(make_server):
    """readOnlyHint=true + risque 'medium' (ex. param 'query' d'une recherche)
    → consultation, aucune friction HITL."""
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(
        scope="user", owner=owner, risk="medium",
        remote="search_datasets", annotations={"readOnlyHint": True},
    )
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is True
    assert d.needs_hitl is False


@pytest.mark.asyncio
async def test_low_risk_skips_hitl(make_server):
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, risk="low", remote="get_info")
    d = await check_mcp_tool_access(owner, local)
    assert d.needs_hitl is False


@pytest.mark.asyncio
async def test_high_risk_always_hitl_even_if_readonly(make_server):
    """Anti tool-poisoning : un nom dangereux (high/critical) NE peut PAS être
    rétrogradé par un readOnlyHint mensonger du serveur."""
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(
        scope="user", owner=owner, risk="critical",
        remote="delete_everything", annotations={"readOnlyHint": True},
    )
    d = await check_mcp_tool_access(owner, local)
    assert d.allowed is True
    assert d.needs_hitl is True


@pytest.mark.asyncio
async def test_medium_write_still_hitl(make_server):
    """Outil 'medium' sans readOnlyHint (écriture/sensible) → confirmation."""
    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, risk="medium", remote="do_thing")
    d = await check_mcp_tool_access(owner, local)
    assert d.needs_hitl is True


@pytest.mark.asyncio
async def test_set_permission_persists_allow(make_server):
    """« Toujours autoriser » écrit dans mcp_tool_permissions → ne re-demande plus
    (le bug : ça allait dans hitl_preferences, ignoré par le gate MCP)."""
    from app.services.mcp_acl import set_permission

    owner = f"u_{uuid.uuid4().hex[:6]}"
    _srv, local = await make_server(scope="user", owner=owner, risk="medium", remote="do_thing")
    # avant : medium write → HITL
    assert (await check_mcp_tool_access(owner, local)).needs_hitl is True
    # l'utilisateur clique « Toujours autoriser »
    assert await set_permission(owner, local, "allow") is True
    # après : plus de confirmation, et ça persiste (nouvelle session DB)
    assert (await check_mcp_tool_access(owner, local)).needs_hitl is False


# ── Règle « tout le serveur » (tool_id NULL) sur un serveur d'instance ────────
# Cas déclencheur : l'admin ouvre un serveur d'instance à un AUTRE utilisateur
# (l'épouse de Franck refusée sur mcp__pdf-folder-translator__translate_pdf_folder).
# La seule voie d'écriture pour un tiers passe par les endpoints admin ;
# ici on vérifie que l'ACL honore une ligne server-wide.

async def _grant_server_wide(user_id: str, server_id: str, decision: str) -> None:
    from app.database import async_session
    from app.models.mcp_server import MCPToolPermission
    async with async_session() as db:
        db.add(MCPToolPermission(
            user_id=user_id, server_id=server_id, tool_id=None, decision=decision,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_instance_server_wide_allow_opens_for_other_user(make_server):
    """tool_id NULL + decision=allow ⇒ un non-admin accède à un serveur
    d'instance qui, sans règle, lui serait refusé."""
    srv, local = await make_server(scope="instance", risk="medium")
    wife = f"u_{uuid.uuid4().hex[:6]}"
    await _ensure_user(wife)
    # Sans règle : refusé (admin-only).
    assert (await check_mcp_tool_access(wife, local, is_admin=False)).allowed is False
    # L'admin pose une règle server-wide « allow ».
    await _grant_server_wide(wife, srv.id, "allow")
    d = await check_mcp_tool_access(wife, local, is_admin=False)
    assert d.allowed is True
    assert d.needs_hitl is False  # « allow » explicite → aucune friction


@pytest.mark.asyncio
async def test_instance_server_wide_allow_covers_all_tools(make_server):
    """Une SEULE règle server-wide (tool_id NULL) ouvre bien TOUS les outils du
    serveur pour le non-admin — pas seulement celui qui a servi à la créer.
    (Test non-tautologique : sans la règle, chaque outil est refusé ; avec, les
    deux passent, ce qui exerce le lookup tool_id IS NULL sur 2 outils distincts.)"""
    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool
    from sqlalchemy import select

    srv, local_a = await make_server(scope="instance", risk="low", remote="tool_a")
    # 2e outil sur le MÊME serveur.
    async with async_session() as db:
        row = (await db.execute(
            select(MCPTool).where(MCPTool.local_name == local_a)
        )).scalar_one()
        local_b = f"mcp__{(await db.get(MCPServer, srv.id)).slug}__tool_b"
        db.add(MCPTool(server_id=srv.id, remote_name="tool_b", local_name=local_b,
                       risk_level="low", enabled=False))
        await db.commit()

    user = f"u_{uuid.uuid4().hex[:6]}"
    await _ensure_user(user)
    # Sans règle : les DEUX outils sont refusés.
    assert (await check_mcp_tool_access(user, local_a, is_admin=False)).allowed is False
    assert (await check_mcp_tool_access(user, local_b, is_admin=False)).allowed is False
    # Une seule règle server-wide allow → les DEUX passent.
    await _grant_server_wide(user, srv.id, "allow")
    assert (await check_mcp_tool_access(user, local_a, is_admin=False)).allowed is True
    assert (await check_mcp_tool_access(user, local_b, is_admin=False)).allowed is True


@pytest.mark.asyncio
async def test_instance_server_wide_ask_grants_but_keeps_hitl_on_sensitive(make_server):
    """decision=ask ouvre l'accès EN gardant le HITL selon le risque : un outil
    low ne demande rien, un outil critical confirme toujours. C'est la valeur qui
    évite qu'un allow server-wide neutralise le HITL des outils sensibles."""
    from app.database import async_session
    from app.models.mcp_server import MCPServer, MCPTool
    from sqlalchemy import select

    srv, local_low = await make_server(scope="instance", risk="low", remote="read_thing")
    async with async_session() as db:
        slug = (await db.get(MCPServer, srv.id)).slug
        local_crit = f"mcp__{slug}__delete_all"
        db.add(MCPTool(server_id=srv.id, remote_name="delete_all", local_name=local_crit,
                       risk_level="critical", enabled=False))
        await db.commit()

    user = f"u_{uuid.uuid4().hex[:6]}"
    await _ensure_user(user)
    await _grant_server_wide(user, srv.id, "ask")

    low = await check_mcp_tool_access(user, local_low, is_admin=False)
    assert low.allowed is True and low.needs_hitl is False   # lecture → aucune friction
    crit = await check_mcp_tool_access(user, local_crit, is_admin=False)
    assert crit.allowed is True and crit.needs_hitl is True  # sensible → confirmation gardée


@pytest.mark.asyncio
async def test_user_server_wide_deny_blocks_owner(make_server):
    """Sur un serveur PERSO, une règle server-wide deny bloque le propriétaire
    via la règle explicite (chemin distinct de la garde admin-only)."""
    owner = f"u_{uuid.uuid4().hex[:6]}"
    srv, local = await make_server(scope="user", owner=owner, risk="low")
    await _grant_server_wide(owner, srv.id, "deny")
    d = await check_mcp_tool_access(owner, local, is_admin=False)
    assert d.allowed is False
    assert "refusé" in (d.reason or "").lower()


@pytest.mark.asyncio
async def test_tool_rule_overrides_server_wide(make_server):
    """La règle la plus spécifique gagne : un deny au niveau outil l'emporte
    sur un allow server-wide."""
    from app.database import async_session
    from app.models.mcp_server import MCPTool, MCPToolPermission
    from sqlalchemy import select

    srv, local = await make_server(scope="instance", risk="low")
    user = f"u_{uuid.uuid4().hex[:6]}"
    await _ensure_user(user)
    await _grant_server_wide(user, srv.id, "allow")
    async with async_session() as db:
        tool = (await db.execute(
            select(MCPTool).where(MCPTool.local_name == local)
        )).scalar_one()
        db.add(MCPToolPermission(
            user_id=user, server_id=srv.id, tool_id=tool.id, decision="deny",
        ))
        await db.commit()
    d = await check_mcp_tool_access(user, local, is_admin=False)
    assert d.allowed is False  # le deny au niveau outil prime sur l'allow serveur
