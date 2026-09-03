# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_gateway_gates_fail_closed.py
# @brief      V0-3 — les deux gardes de sécurité de la passerelle ne
#             disparaissent plus en silence quand leur vérification échoue.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du fail-closed des gardes de la passerelle (audit Opus 5 §4.6).

Deux gardes attrapaient toute exception, la journalisaient en ``debug``, et
laissaient ``needs_hitl`` à ``False`` :

- le **canary des outils io** (`tool_gateway.py:240-247`) — un outil
  auto-généré à egress réel s'exécutait alors sans validation ;
- l'**ACL MCP** (`:253-259`) — un outil de serveur MCP tiers passait sans
  confirmation.

« Si l'appel lève, la garde disparaît silencieusement. » C'est le pire mode
de panne pour une garde : invisible et permissif.

⚠️ Le fail-closed doit rester **scopé**. `io_canary_requires_hitl` rend déjà
`False` d'emblée quand le profil io est éteint (l'état de la prod) : forcer
le HITL sur *tout* outil parce que ce module ne s'importe plus serait une
régression bien pire que le trou qu'on bouche. Quand la garde n'a rien à
garder, ne rien exiger n'est pas « échouer ouvert ».

Run with:  cd backend && python -m pytest tests/test_gateway_gates_fail_closed.py -v
"""
from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio

from app.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


class _RecordingHitl:
    """HITL espion : enregistre les sollicitations et autorise."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def request_validation(self, description, user_id):
        self.prompts.append(description)
        return ("allow", None)


class _HarmlessTool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def ainvoke(self, args):
        return "ok"


def _ctx(hitl):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-gate-{uuid.uuid4()}"
    return GatewayContext(
        user_id="u-gate", conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=hitl, memory=None,
    )


def _boom(*_a, **_kw):
    raise RuntimeError("vérification indisponible")


# ------------------------------------------------------- canary des outils io

@pytest.mark.asyncio
async def test_io_canary_failure_forces_hitl_when_io_profile_is_enabled(monkeypatch, caplog):
    """Profil io ACTIF + vérification du canary en panne → HITL exigé.
    Avant : l'outil s'exécutait sans validation."""
    import app.services.learning.learned_tools_runtime_io as io_mod
    from app.services.tool_gateway import execute_tool_call

    monkeypatch.setattr(io_mod, "io_canary_requires_hitl", _boom)
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "true")
    monkeypatch.delenv("LEARNED_PYTHON_TOOLS_DISABLED", raising=False)

    hitl = _RecordingHitl()
    with caplog.at_level(logging.WARNING):
        await execute_tool_call(
            _ctx(hitl), {"name": "some_io_tool", "args": {}, "id": "g1"},
            {"some_io_tool": _HarmlessTool("some_io_tool")},
        )

    assert hitl.prompts, "la garde a disparu : aucun HITL alors qu'elle est en panne"
    assert any("canary" in r.message.lower() for r in caplog.records), (
        "une garde qui tombe doit être visible en WARNING, pas en debug"
    )


@pytest.mark.asyncio
async def test_io_canary_failure_is_a_noop_when_io_profile_is_disabled(monkeypatch):
    """Profil io ÉTEINT (l'état de la prod) : la garde ne protège rien, donc
    sa panne ne doit pas déclencher un HITL sur chaque outil."""
    import app.services.learning.learned_tools_runtime_io as io_mod
    from app.services.tool_gateway import execute_tool_call

    monkeypatch.setattr(io_mod, "io_canary_requires_hitl", _boom)
    monkeypatch.setenv("LEARNED_PYTHON_TOOLS_IO_ENABLED", "false")

    hitl = _RecordingHitl()
    await execute_tool_call(
        _ctx(hitl), {"name": "some_tool", "args": {}, "id": "g2"},
        {"some_tool": _HarmlessTool("some_tool")},
    )

    assert not hitl.prompts, (
        "HITL déclenché alors que le profil io est éteint — régression majeure"
    )


# ------------------------------------------------------------------ ACL MCP

@pytest.mark.asyncio
async def test_mcp_acl_failure_forces_hitl(monkeypatch, caplog):
    """ACL MCP illisible → l'outil MCP passe sous validation humaine.
    Avant : il s'exécutait sans confirmation."""
    import app.services.mcp_acl as acl_mod
    from app.services.tool_gateway import execute_tool_call

    monkeypatch.setattr(acl_mod, "needs_hitl", _boom)

    tool = "mcp__weather__forecast"
    hitl = _RecordingHitl()
    with caplog.at_level(logging.WARNING):
        await execute_tool_call(
            _ctx(hitl), {"name": tool, "args": {}, "id": "g3"},
            {tool: _HarmlessTool(tool)},
        )

    assert hitl.prompts, "la garde ACL MCP a disparu au lieu de se refermer"
    assert any("acl" in r.message.lower() or "mcp" in r.message.lower()
               for r in caplog.records), "panne de garde invisible"


@pytest.mark.asyncio
async def test_mcp_acl_failure_does_not_gate_non_mcp_tools(monkeypatch):
    """Le fail-closed reste scopé : un outil natif n'est pas impacté par une
    ACL MCP en panne."""
    import app.services.mcp_acl as acl_mod
    from app.services.tool_gateway import execute_tool_call

    monkeypatch.setattr(acl_mod, "needs_hitl", _boom)

    hitl = _RecordingHitl()
    await execute_tool_call(
        _ctx(hitl), {"name": "plain_tool", "args": {}, "id": "g4"},
        {"plain_tool": _HarmlessTool("plain_tool")},
    )

    assert not hitl.prompts


@pytest.mark.asyncio
async def test_healthy_gates_still_let_harmless_tools_through():
    """Non-régression : gardes saines, outil inoffensif → aucun HITL."""
    from app.services.tool_gateway import execute_tool_call

    hitl = _RecordingHitl()
    msg = await execute_tool_call(
        _ctx(hitl), {"name": "calm_tool", "args": {}, "id": "g5"},
        {"calm_tool": _HarmlessTool("calm_tool")},
    )

    assert not hitl.prompts
    assert "ok" in msg.content if hasattr(msg, "content") else True
