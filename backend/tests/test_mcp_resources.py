# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_resources.py
# @brief      J6 — resources/prompts : outils model-facing + normalisation.
# @license    Elastic License 2.0
# =============================================================================
"""Tests J6 : les 4 outils resources/prompts (flag, isolation, kill_switch,
instance→admin, stdio refusé, outbound sur get_prompt), normalisation des
résultats, pagination, et câblage (self-gating + user_id)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.skills.builtin import mcp_model_skill as M
from app.services import mcp_results, mcp_remote, mcp_client


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
async def owned():
    from app.database import init_db
    await init_db()
    return await _ensure_user(f"u_{uuid.uuid4().hex[:8]}")


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(M, "_flag_resources_on", lambda: True)


async def _make_server(uid, *, scope="user", trust_state="active", kill_switch=False,
                       transport="streamable_http", owner="__self__"):
    from app.database import async_session
    from app.models.mcp_server import MCPServer
    await _ensure_user(uid)
    slug = f"res_{uuid.uuid4().hex[:8]}"
    owner_id = uid if owner == "__self__" else owner
    async with async_session() as db:
        srv = MCPServer(name=slug, slug=slug, transport=transport,
                        url="https://x/mcp" if transport != "stdio" else None,
                        command="echo" if transport == "stdio" else None,
                        scope=scope, owner_user_id=owner_id if scope == "user" else None,
                        trust_state=trust_state, kill_switch=kill_switch,
                        enabled=True, auth_type="none")
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        return srv.id


# ── Flag ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resources_off_by_default():
    out = await M.mcp_list_resources.coroutine(server_id="x", user_id="u")
    assert "désactivés" in out
    out2 = await M.mcp_get_prompt.coroutine(server_id="x", prompt_name="p", user_id="u")
    assert "désactivés" in out2


# ── Garde d'accès (isolation / kill_switch / instance→admin / stdio) ─────────

@pytest.mark.asyncio
async def test_read_denies_other_users_server(flag_on, owned):
    sid = await _make_server(owned)
    other = await _ensure_user(f"u_{uuid.uuid4().hex[:8]}")
    out = await M.mcp_read_resource.coroutine(server_id=sid, uri="res://x", user_id=other)
    assert "introuvable ou non accessible" in out


@pytest.mark.asyncio
async def test_read_refuses_quarantined_server(flag_on, owned):
    sid = await _make_server(owned, trust_state="quarantined")
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=owned)
    assert "quarantaine" in out.lower() or "désactivé" in out.lower()


@pytest.mark.asyncio
async def test_read_refuses_kill_switch(flag_on, owned):
    sid = await _make_server(owned, kill_switch=True)
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=owned)
    assert "désactivé" in out.lower() or "quarantaine" in out.lower()


@pytest.mark.asyncio
async def test_instance_server_requires_admin(flag_on, owned):
    sid = await _make_server(owned, scope="instance")
    # owned est un user simple → refus.
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=owned)
    assert "administrateur" in out.lower()


@pytest.mark.asyncio
async def test_instance_server_allows_admin(flag_on, monkeypatch):
    admin = await _ensure_user(f"a_{uuid.uuid4().hex[:8]}", role="admin")
    sid = await _make_server(admin, scope="instance")

    async def _fake_list(srv, user_id):
        return [SimpleNamespace(uri="res://a", name="A", description="d", mimeType="text/plain")]
    monkeypatch.setattr(mcp_remote, "remote_list_resources", _fake_list)
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=admin)
    assert "res://a" in out


@pytest.mark.asyncio
async def test_stdio_server_refused(flag_on, owned):
    sid = await _make_server(owned, transport="stdio")
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=owned)
    assert "local" in out.lower() and "stdio" in out.lower()


# ── read_resource / get_prompt — succès & sécurité ───────────────────────────

@pytest.mark.asyncio
async def test_read_resource_rejects_vault_uri(flag_on, owned):
    sid = await _make_server(owned)
    out = await M.mcp_read_resource.coroutine(server_id=sid, uri="vault://secret", user_id=owned)
    assert "invalide" in out.lower()


@pytest.mark.asyncio
async def test_read_resource_returns_normalized(flag_on, owned, monkeypatch):
    sid = await _make_server(owned)

    async def _fake_read(srv, user_id, uri, *, local_name="mcp"):
        return "[ressource MCP res://x (contenu non vérifié)]\nhello"
    monkeypatch.setattr(mcp_remote, "remote_read_resource", _fake_read)
    out = await M.mcp_read_resource.coroutine(server_id=sid, uri="res://x", user_id=owned)
    assert "contenu non vérifié" in out and "hello" in out


@pytest.mark.asyncio
async def test_get_prompt_blocks_secret_in_args(flag_on, owned):
    sid = await _make_server(owned)
    out = await M.mcp_get_prompt.coroutine(
        server_id=sid, prompt_name="p",
        arguments={"k": "ghp_ABCDEFGHIJKLMNOPQRSTUV012345"}, user_id=owned)
    assert "bloqué" in out.lower()


@pytest.mark.asyncio
async def test_get_prompt_returns_with_banner(flag_on, owned, monkeypatch):
    sid = await _make_server(owned)

    async def _fake_get(srv, user_id, name, arguments, *, local_name="mcp"):
        return mcp_results.normalize_prompt_result(
            SimpleNamespace(description="d", messages=[
                SimpleNamespace(role="user", content=SimpleNamespace(type="text", text="salut"))]))
    monkeypatch.setattr(mcp_remote, "remote_get_prompt", _fake_get)
    out = await M.mcp_get_prompt.coroutine(server_id=sid, prompt_name="p", user_id=owned)
    assert "NON FIABLE" in out and "salut" in out


# ── Normalisation (unitaire, pur) ────────────────────────────────────────────

def test_normalize_resource_text_and_blob():
    import base64
    res = SimpleNamespace(contents=[
        SimpleNamespace(uri="res://t", mimeType="text/plain", text="bonjour"),
        SimpleNamespace(uri="res://b", mimeType="image/png",
                        blob=base64.b64encode(b"\x89PNG").decode(), text=None),
    ])
    out = mcp_results.normalize_resource_result(res)
    assert "contenu non vérifié" in out and "bonjour" in out
    assert "/tmp/ely-attachments" in out  # binaire hors-contexte


def test_normalize_prompt_has_banner_and_messages():
    res = SimpleNamespace(description="desc", messages=[
        SimpleNamespace(role="user", content=SimpleNamespace(type="text", text="hello")),
    ])
    out = mcp_results.normalize_prompt_result(res)
    assert out.startswith("⚠️")
    assert "NON FIABLE" in out
    assert "hello" in out


def test_normalize_prompt_handles_list_content():
    # .content non conforme (liste de blocs) : on ne perd pas le contenu.
    res = SimpleNamespace(description=None, messages=[
        SimpleNamespace(role="user", content=[
            SimpleNamespace(type="text", text="un"),
            SimpleNamespace(type="text", text="deux"),
        ]),
    ])
    out = mcp_results.normalize_prompt_result(res)
    assert "un" in out and "deux" in out


def test_normalize_prompt_fences_untrusted_messages():
    res = SimpleNamespace(description=None, messages=[
        SimpleNamespace(role="user", content=SimpleNamespace(type="text", text="x")),
    ])
    out = mcp_results.normalize_prompt_result(res)
    assert "contenu serveur, non fiable" in out


@pytest.mark.asyncio
async def test_tool_error_does_not_leak_url(flag_on, owned, monkeypatch):
    # Une exception contenant un secret (URL avec token) ne doit PAS être
    # renvoyée brute au modèle — seule la classe d'exception transparaît.
    sid = await _make_server(owned)

    class _LeakyError(Exception):
        pass

    async def _boom(srv, user_id):
        raise _LeakyError("connect to https://x/mcp?token=ghp_SUPERSECRET failed")
    monkeypatch.setattr(mcp_remote, "remote_list_resources", _boom)
    out = await M.mcp_list_resources.coroutine(server_id=sid, user_id=owned)
    assert "ghp_SUPERSECRET" not in out
    assert "token=" not in out
    assert "_LeakyError" in out  # classe d'exception = forme stable


def test_normalize_resource_caps_size():
    big = "x" * (2 * 1024 * 1024)
    res = SimpleNamespace(contents=[SimpleNamespace(uri="r", mimeType="text/plain", text=big)])
    out = mcp_results.normalize_resource_result(res, max_text_bytes=1024)
    assert "tronqué" in out
    assert len(out.encode("utf-8")) < 2000


# ── Pagination ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_resources_paginates():
    pages = [
        SimpleNamespace(resources=[1, 2], nextCursor="c1"),
        SimpleNamespace(resources=[3], nextCursor=None),
    ]
    calls = []

    async def _list(cursor=None):
        calls.append(cursor)
        return pages.pop(0)
    out = await mcp_client._collect_resources(_list)
    assert out == [1, 2, 3]
    assert calls == [None, "c1"]


@pytest.mark.asyncio
async def test_collect_prompts_bounded_to_100_pages():
    async def _list(cursor=None):
        return SimpleNamespace(prompts=["p"], nextCursor="always")
    out = await mcp_client._collect_prompts(_list)
    assert len(out) == 100  # borne dure


# ── Câblage ──────────────────────────────────────────────────────────────────

def test_wiring_names_registered():
    from app.agent.tool_node import _MCP_SELF_GATING_TOOLS
    from app.agent.tool_sets import USER_ID_TOOLS
    new = {"mcp_list_resources", "mcp_read_resource", "mcp_list_prompts", "mcp_get_prompt"}
    assert new <= M.MCP_MODEL_TOOL_NAMES
    assert new <= _MCP_SELF_GATING_TOOLS
    assert new <= USER_ID_TOOLS
