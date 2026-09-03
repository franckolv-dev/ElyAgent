# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_desktop_ws_resilience.py
# @brief      Tests for desktop_registry resilience to Cloudflare tunnel blips
# @license    MIT
# =============================================================================
"""Tests de résilience de la WebSocket ELY Desktop.

Contexte : le tunnel Cloudflare reset périodiquement la WS du daemon (rotation
des connexions edge, « connection reset by peer »). Le daemon se reconnecte en
~2 s, mais ce blip faisait avorter les tâches en cours : is_connected() échouait
sec et send_command() partait en timeout 30 s sur la connexion morte.

Le fix : ensure_connected() attend la reconnexion pendant une grâce (~15 s),
et send_command() détecte le remplacement de connexion en cours de commande
pour re-tenter une fois sur la nouvelle. unregister() est gardé par identité
pour qu'un vieux handler ne désenregistre pas la connexion fraîche.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services import desktop_registry
from app.services.desktop_registry import (
    DesktopNotConnectedError,
    DesktopTimeoutError,
)


class FakeWebSocket:
    """Juste assez de starlette.WebSocket pour desktop_registry."""

    def __init__(self, fail_send: bool = False):
        self.sent: list[str] = []
        self.fail_send = fail_send

    async def send_text(self, payload: str) -> None:
        if self.fail_send:
            raise RuntimeError("WebSocket is closed")
        self.sent.append(payload)


@pytest.fixture(autouse=True)
def clean_registry():
    desktop_registry._connections.clear()
    yield
    desktop_registry._connections.clear()


def _register(user_id: str = "u1", ws: FakeWebSocket | None = None):
    ws = ws or FakeWebSocket()
    conn = desktop_registry.register(user_id, ws, {"platform": "test"})
    return conn, ws


def _last_cmd_id(ws: FakeWebSocket) -> str:
    return json.loads(ws.sent[-1])["cmd_id"]


# ─────────────────────────────────────────────────────────────────────────
# ensure_connected — grâce de reconnexion
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_connected_immediate():
    _register("u1")
    assert await desktop_registry.ensure_connected("u1", grace=0.1) is True


@pytest.mark.asyncio
async def test_ensure_connected_never_connects():
    assert await desktop_registry.ensure_connected("u1", grace=0.2) is False


@pytest.mark.asyncio
async def test_ensure_connected_survives_blip():
    """Le daemon revient pendant la grâce → True (le blip est invisible)."""

    async def reconnect_later():
        await asyncio.sleep(0.15)
        _register("u1")

    task = asyncio.create_task(reconnect_later())
    assert await desktop_registry.ensure_connected("u1", grace=2.0) is True
    await task


# ─────────────────────────────────────────────────────────────────────────
# send_command — retry sur remplacement de connexion
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_command_nominal():
    _, ws = _register("u1")

    async def respond():
        while not ws.sent:
            await asyncio.sleep(0.01)
        desktop_registry.deliver_result(
            "u1",
            {"cmd_id": _last_cmd_id(ws), "status": "ok", "result": {"entries": []}},
        )

    task = asyncio.create_task(respond())
    result = await desktop_registry.send_command("u1", "list_dir", {"path": "/x"})
    assert result == {"entries": []}
    await task


@pytest.mark.asyncio
async def test_send_command_retries_when_send_fails_then_reconnects():
    """Socket mort à l'envoi (reset CF) → attend la nouvelle connexion et
    re-tente une fois dessus."""
    _register("u1", FakeWebSocket(fail_send=True))
    new_ws = FakeWebSocket()

    async def reconnect_and_respond():
        await asyncio.sleep(0.1)
        _register("u1", new_ws)  # remplace la connexion morte
        while not new_ws.sent:
            await asyncio.sleep(0.01)
        desktop_registry.deliver_result(
            "u1",
            {"cmd_id": _last_cmd_id(new_ws), "status": "ok", "result": {"ok": 1}},
        )

    task = asyncio.create_task(reconnect_and_respond())
    result = await desktop_registry.send_command(
        "u1", "stat_file", {"path": "/x"}, reconnect_grace=2.0
    )
    assert result == {"ok": 1}
    assert len(new_ws.sent) == 1
    await task


@pytest.mark.asyncio
async def test_send_command_retries_when_replaced_mid_wait():
    """Commande partie sur la connexion A, A meurt pendant l'attente du
    résultat → détection du remplacement (sans attendre le timeout 30 s)
    et re-tentative sur B."""
    _, ws_a = _register("u1")
    ws_b = FakeWebSocket()

    async def replace_and_respond():
        while not ws_a.sent:
            await asyncio.sleep(0.01)
        _register("u1", ws_b)  # A ne répondra jamais : remplacée par B
        while not ws_b.sent:
            await asyncio.sleep(0.01)
        desktop_registry.deliver_result(
            "u1",
            {"cmd_id": _last_cmd_id(ws_b), "status": "ok", "result": {"ok": 2}},
        )

    task = asyncio.create_task(replace_and_respond())
    result = await desktop_registry.send_command(
        "u1", "read_file", {"path": "/x"}, timeout=30.0, reconnect_grace=2.0
    )
    assert result == {"ok": 2}
    await task


@pytest.mark.asyncio
async def test_send_command_plain_timeout_no_retry():
    """Daemon vivant mais muet → DesktopTimeoutError, pas de re-tentative."""
    _, ws = _register("u1")
    with pytest.raises(DesktopTimeoutError):
        await desktop_registry.send_command("u1", "list_dir", {"path": "/x"}, timeout=0.3)
    assert len(ws.sent) == 1


@pytest.mark.asyncio
async def test_send_command_gone_for_good():
    """Connexion perdue en cours de commande, jamais de retour → erreur
    « non connecté » après la grâce (pas un faux timeout)."""
    _, ws = _register("u1")

    async def drop():
        while not ws.sent:
            await asyncio.sleep(0.01)
        desktop_registry._connections.clear()  # déconnexion sans retour

    task = asyncio.create_task(drop())
    with pytest.raises(DesktopNotConnectedError):
        await desktop_registry.send_command(
            "u1", "list_dir", {"path": "/x"}, timeout=30.0, reconnect_grace=0.3
        )
    await task


@pytest.mark.asyncio
async def test_send_command_waits_for_initial_connection():
    """Pas connecté au moment de l'appel mais le daemon revient pendant la
    grâce → la commande part quand même (blip invisible pour l'outil)."""
    ws = FakeWebSocket()

    async def connect_and_respond():
        await asyncio.sleep(0.1)
        _register("u1", ws)
        while not ws.sent:
            await asyncio.sleep(0.01)
        desktop_registry.deliver_result(
            "u1",
            {"cmd_id": _last_cmd_id(ws), "status": "ok", "result": {"ok": 3}},
        )

    task = asyncio.create_task(connect_and_respond())
    result = await desktop_registry.send_command(
        "u1", "list_dir", {"path": "/x"}, reconnect_grace=2.0
    )
    assert result == {"ok": 3}
    await task


# ─────────────────────────────────────────────────────────────────────────
# unregister — garde d'identité (course reconnexion rapide vs vieux handler)
# ─────────────────────────────────────────────────────────────────────────


def test_unregister_ignores_stale_handler():
    """Le daemon s'est reconnecté AVANT que le vieux handler WS ne meure :
    le finally du vieux handler ne doit pas désenregistrer la connexion
    fraîche."""
    _, old_ws = _register("u1")
    _register("u1", FakeWebSocket())  # reconnexion rapide

    desktop_registry.unregister("u1", ws=old_ws)  # vieux handler
    assert desktop_registry.is_connected("u1") is True


def test_unregister_without_ws_still_works():
    _register("u1")
    desktop_registry.unregister("u1")
    assert desktop_registry.is_connected("u1") is False


def test_unregister_matching_ws():
    _, ws = _register("u1")
    desktop_registry.unregister("u1", ws=ws)
    assert desktop_registry.is_connected("u1") is False
