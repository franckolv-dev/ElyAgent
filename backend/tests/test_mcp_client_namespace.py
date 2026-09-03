# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_client_namespace.py
# @brief      Lot 0 du client MCP — namespace, garde anti-collision, args,
#             redaction des secrets, kill switch.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests du Lot 0 (stabilisation client MCP).

Couvre les invariants de sécurité ajoutés au Lot 0 :
  - namespace ``mcp__<slug>__<tool>`` (aucun masquage d'outil natif) ;
  - garde anti-collision (fail-closed) ;
  - parsing strict de ``args_json`` ;
  - redaction de ``env_json`` dans l'API (valeurs jamais renvoyées) ;
  - ``kill_switch`` court-circuite le chargement.
"""
from __future__ import annotations

import re
import uuid

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Namespace
# ─────────────────────────────────────────────────────────────────────────


def test_namespaced_basic():
    from app.services.mcp_client import namespaced_tool_name

    assert namespaced_tool_name("github", "search") == "mcp__github__search"
    assert namespaced_tool_name("notion", "search") == "mcp__notion__search"


def test_namespaced_two_servers_same_remote_no_collision():
    """Deux serveurs exposant `search` produisent des noms locaux distincts."""
    from app.services.mcp_client import namespaced_tool_name

    a = namespaced_tool_name("github", "search")
    b = namespaced_tool_name("notion", "search")
    assert a != b


def test_namespaced_sanitizes_hostile_remote_name():
    """Le nom distant est une entrée NON fiable → caractères hostiles neutralisés."""
    from app.services.mcp_client import namespaced_tool_name

    local = namespaced_tool_name("ns", "weird name!@# /../")
    assert local.startswith("mcp__ns__")
    # Plus aucun caractère hors [a-zA-Z0-9_-]
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", local)


def test_namespaced_bounded_length():
    from app.services.mcp_client import namespaced_tool_name

    local = namespaced_tool_name("ns", "x" * 500)
    assert len(local) <= 128


def test_namespaced_never_shadows_native_prefix():
    """Tout nom MCP commence par `mcp__` → ne peut jamais être un nom natif."""
    from app.services.mcp_client import namespaced_tool_name

    assert namespaced_tool_name("x", "gmail_send").startswith("mcp__")


# ─────────────────────────────────────────────────────────────────────────
# Garde anti-collision (fail-closed)
# ─────────────────────────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _register_native_skill(tool_names: list[str]) -> str:
    """Enregistre une skill NON-mcp ; renvoie son nom pour le cleanup."""
    from app.skills.base import Skill
    from app.skills.registry import get_skill_registry

    name = f"native_{uuid.uuid4().hex[:8]}"
    skill = Skill(
        name=name,
        display_name=name,
        description="fake native skill",
        icon="🔧",
        scopes=["default"],
        tools=[_FakeTool(n) for n in tool_names],
        author="test",
    )
    get_skill_registry().register_or_replace(skill)
    return name


def test_guard_drops_tool_colliding_with_native():
    from app.services.mcp_client import MCPClientManager
    from app.skills.registry import get_skill_registry

    shadow = "mcp__x__shadow"
    native = _register_native_skill([shadow])
    try:
        mgr = MCPClientManager()
        tools = [_FakeTool(shadow), _FakeTool("mcp__x__safe")]
        kept = mgr._guard_collisions("x", tools)
        names = {t.name for t in kept}
        assert shadow not in names          # collision → écarté
        assert "mcp__x__safe" in names      # le sain reste
    finally:
        get_skill_registry().unregister(native)


def test_guard_drops_tool_colliding_with_other_mcp_server():
    from app.services import mcp_client
    from app.services.mcp_client import MCPClientManager

    mcp_client._MCP_TOOL_NAMES["othersrv"] = {"mcp__x__dup"}
    try:
        mgr = MCPClientManager()
        kept = mgr._guard_collisions("x", [_FakeTool("mcp__x__dup"), _FakeTool("mcp__x__ok")])
        names = {t.name for t in kept}
        assert "mcp__x__dup" not in names
        assert "mcp__x__ok" in names
    finally:
        mcp_client._MCP_TOOL_NAMES.pop("othersrv", None)


# ─────────────────────────────────────────────────────────────────────────
# args_json
# ─────────────────────────────────────────────────────────────────────────


def test_parse_args_json_valid_list():
    from app.services.mcp_client import _parse_args_json

    assert _parse_args_json('["-y", "@scope/server", "/data"]') == ["-y", "@scope/server", "/data"]


def test_parse_args_json_none_is_legacy():
    from app.services.mcp_client import _parse_args_json

    assert _parse_args_json(None) is None
    assert _parse_args_json("") is None


def test_parse_args_json_rejects_non_list_and_non_string():
    from app.services.mcp_client import _parse_args_json

    assert _parse_args_json('"just a string"') is None
    assert _parse_args_json('{"a": 1}') is None
    assert _parse_args_json('["ok", 3, true]') is None   # liste mais pas que des str
    assert _parse_args_json("not json{") is None


# ─────────────────────────────────────────────────────────────────────────
# Redaction des secrets (router)
# ─────────────────────────────────────────────────────────────────────────


def test_mcpserverout_never_exposes_env_json():
    from app.routers.mcp import MCPServerOut

    assert "env_json" not in MCPServerOut.model_fields
    assert "env_keys" in MCPServerOut.model_fields


def test_env_key_names_returns_names_only():
    from app.routers.mcp import _env_key_names

    keys = _env_key_names('{"GITHUB_TOKEN": "ghp_secret", "FOO": "bar"}')
    assert keys == ["FOO", "GITHUB_TOKEN"]       # trié, NOMS seulement


def test_env_key_names_handles_empty_and_garbage():
    from app.routers.mcp import _env_key_names

    assert _env_key_names(None) is None
    assert _env_key_names("") is None
    assert _env_key_names("not-json{") is None
    assert _env_key_names('["a","b"]') is None   # JSON valide mais pas un objet


def test_decorate_with_runtime_redacts_secret_value():
    """Le secret ne doit apparaître NULLE PART dans la réponse sérialisée."""
    from app.models.mcp_server import MCPServer
    from app.routers.mcp import _decorate_with_runtime

    secret = "ghp_TOP_SECRET_VALUE"
    srv = MCPServer(
        id="t",
        name="gh",
        slug=f"gh_{uuid.uuid4().hex[:6]}",
        transport="stdio",
        command="noop",
        env_json=f'{{"GITHUB_TOKEN": "{secret}"}}',
        enabled=True,
    )
    out = _decorate_with_runtime(srv)
    dumped = out.model_dump_json()
    assert secret not in dumped
    assert "env_json" not in dumped
    assert out.env_keys == ["GITHUB_TOKEN"]


# ─────────────────────────────────────────────────────────────────────────
# Kill switch
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_load(monkeypatch):
    """Un serveur kill-switché n'est jamais chargé : `_build_tools` n'est
    même pas appelé, et la skill n'apparaît pas dans le registre."""
    from app.models.mcp_server import MCPServer
    from app.services.mcp_client import MCPClientManager
    from app.skills.registry import get_skill_registry

    mgr = MCPClientManager()

    async def _boom(self, srv):  # _build_tools ne doit PAS être atteint
        raise AssertionError("_build_tools must not run for a kill-switched server")

    monkeypatch.setattr(MCPClientManager, "_build_tools", _boom)

    slug = f"killed_{uuid.uuid4().hex[:6]}"
    srv = MCPServer(
        id="k", name="killed", slug=slug,
        transport="stdio", command="noop",
        enabled=True, kill_switch=True,
    )
    # Ne lève pas (court-circuit) et n'enregistre rien.
    await mgr.load_server(srv)
    assert get_skill_registry().get_skill(f"mcp_{slug}") is None
