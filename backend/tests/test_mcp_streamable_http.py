# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mcp_streamable_http.py
# @brief      J2 — transport Streamable HTTP (build + garde egress).
# @license    Elastic License 2.0
# =============================================================================
"""Le transport MCP moderne : Streamable HTTP.

Couvre (a) le refus egress AVANT toute connexion (cibles internes/non-HTTPS)
sans toucher au réseau, et (b) le chemin nominal qui construit des outils
namespacés, avec le SDK MCP moqué.
"""
from __future__ import annotations

import uuid

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Garde egress dans le builder (aucun réseau)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://10.0.0.1/mcp",        # IP privée littérale
    "https://127.0.0.1/mcp",       # loopback
    "https://169.254.169.254/mcp", # métadonnées cloud
    "https://localhost/mcp",       # hostname interne
    "http://mcp.example.com/mcp",  # non-HTTPS
])
async def test_streamable_http_blocked_targets_yield_no_tools(url):
    """Une cible interdite ⇒ 0 outil, sans tentative de connexion."""
    from app.models.mcp_server import MCPServer
    from app.services.mcp_client import MCPClientManager

    mgr = MCPClientManager()
    srv = MCPServer(
        id="x", name="bad", slug=f"bad_{uuid.uuid4().hex[:6]}",
        transport="streamable_http", url=url, enabled=True,
    )
    tools = await mgr._build_streamable_http_tools(srv)
    assert tools == []


@pytest.mark.asyncio
async def test_streamable_http_no_url_yields_no_tools():
    from app.models.mcp_server import MCPServer
    from app.services.mcp_client import MCPClientManager

    mgr = MCPClientManager()
    srv = MCPServer(id="x", name="n", slug="nourl", transport="streamable_http", url=None)
    assert await mgr._build_streamable_http_tools(srv) == []


# ─────────────────────────────────────────────────────────────────────────
# Chemin nominal (SDK moqué)
# ─────────────────────────────────────────────────────────────────────────


class _FakeMCPTool:
    def __init__(self, name, desc, schema):
        self.name = name
        self.description = desc
        self.inputSchema = schema


class _FakeListResult:
    def __init__(self, tools):
        self.tools = tools


class _FakeSession:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        pass

    async def list_tools(self):
        return _FakeListResult([
            _FakeMCPTool("search", "Search docs",
                         {"type": "object", "properties": {"q": {"type": "string"}},
                          "required": ["q"]}),
        ])


class _FakeStreamCtx:
    async def __aenter__(self):
        # streamablehttp_client renvoie un 3-tuple (read, write, get_session_id)
        return (object(), object(), lambda: "sid")

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_streamable_http_builds_namespaced_tools(monkeypatch):
    import mcp
    import mcp.client.streamable_http as shttp

    from app.models.mcp_server import MCPServer
    from app.services import mcp_egress
    from app.services.mcp_client import MCPClientManager

    # Skip la vraie résolution DNS (pas de réseau dans les tests).
    monkeypatch.setattr(mcp_egress, "validate_egress_url", lambda *a, **k: None)
    monkeypatch.setattr(shttp, "streamablehttp_client",
                        lambda *a, **k: _FakeStreamCtx())
    monkeypatch.setattr(mcp, "ClientSession", _FakeSession)

    mgr = MCPClientManager()
    slug = f"remote_{uuid.uuid4().hex[:6]}"
    srv = MCPServer(
        id="r", name="Remote", slug=slug,
        transport="streamable_http", url="https://mcp.example.com/mcp",
        enabled=True,
    )
    tools = await mgr._build_streamable_http_tools(srv)
    assert len(tools) == 1
    # Nom local namespacé, pas le nom distant brut.
    assert tools[0].name == f"mcp__{slug}__search"
