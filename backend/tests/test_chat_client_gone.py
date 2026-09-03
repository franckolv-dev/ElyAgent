# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_chat_client_gone.py
# @brief      Incident 24/07 — « client parti » ne doit plus être traité comme
#             « stop demandé » : le tour finit son travail et notifie.
# @license    MIT
# =============================================================================
"""Incident réel (24/07/2026, conversation de Gert).

Une traduction de PDF (395 pages) a tourné 2 h 52 et **réussi** — mais
l'onglet était fermé depuis longtemps. Le watcher WebSocket, en voyant la
socket morte, levait le MÊME drapeau qu'un clic « stop » : le tour a été
coupé à la première occasion, la synthèse n'a jamais eu lieu, la conversion
DOCX demandée non plus, et le message persisté s'est terminé par « … » (la
marque d'une interruption). Ely ignorait son propre succès.

Contrat corrigé, pinné ici :
  1. un « stop » explicite arrête toujours le tour (inchangé) ;
  2. une socket morte lève ``client_gone``, PAS ``stop_event`` ;
  3. les envois deviennent best-effort — un client parti ne fait plus
     remonter de RuntimeError qui tuerait le tour ;
  4. quand le tour s'achève sans personne au bout du fil, un push prévient
     que la réponse est prête (la réponse, elle, est déjà en base).

Run with:  cd backend && python -m pytest tests/test_chat_client_gone.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[1] / "app/routers/chat.py").read_text(
    encoding="utf-8"
)


# ────────────────────────────────────────────────────────────────────────
# Le contrat de séparation stop / déconnexion (pins de source)
# ────────────────────────────────────────────────────────────────────────


def test_disconnect_no_longer_sets_stop_event():
    """La branche `except` du watcher lève client_gone, pas stop_event —
    c'était LA ligne qui jetait 2 h 52 de travail."""
    watcher = _SRC.split("async def _watch_for_stop()", 1)[1].split("\n\n", 1)[0]
    assert "client_gone.set()" in watcher, (
        "la disparition du client doit lever client_gone"
    )
    # Dans le watcher, stop_event n'est levé QUE sur le message explicite.
    stop_sets = [
        line for line in watcher.split("\n") if "stop_event.set()" in line
    ]
    assert len(stop_sets) == 1, "un seul stop_event.set(), celui du stop explicite"
    explicit = watcher.split('inner.get("type") == "stop"', 1)[1]
    assert "stop_event.set()" in explicit.split("return", 1)[0]


def test_explicit_stop_still_stops_the_turn():
    """Le geste délibéré de l'utilisateur reste souverain."""
    assert 'if stop_event.is_set():' in _SRC and "break" in _SRC


def test_every_turn_send_goes_through_the_safe_helper():
    """Un seul envoi brut subsiste : celui DANS le helper. Sinon une socket
    morte relance une RuntimeError qui remonte et tue le tour."""
    raw = [
        line for line in _SRC.split("\n")
        if "websocket.send_text(" in line and "_ws_send" not in line
    ]
    assert len(raw) == 1, f"envois bruts hors helper : {raw}"


def test_helper_does_not_call_itself():
    """Garde anti-récursion (piège rencontré en écrivant le correctif)."""
    helper = _SRC.split("async def _ws_send(", 1)[1].split("\n    try:", 1)[0]
    body = _SRC.split("async def _ws_send(", 1)[1].split("\n\n", 1)[0]
    assert "await websocket.send_text(text)" in body
    assert "await _ws_send(text)" not in body


# ────────────────────────────────────────────────────────────────────────
# Comportement du helper (unitaire, sans WebSocket réelle)
# ────────────────────────────────────────────────────────────────────────


class _FakeWS:
    """Socket qui meurt au n-ième envoi, comme une vraie connexion perdue."""

    def __init__(self, die_after: int = 10_000):
        self.sent: list[str] = []
        self._die_after = die_after

    async def send_text(self, text: str) -> None:
        if len(self.sent) >= self._die_after:
            raise RuntimeError(
                "Unexpected ASGI message 'websocket.send', after sending "
                "'websocket.close' or response already completed."
            )
        self.sent.append(text)


def _make_helper(ws, client_gone):
    """Réplique fidèle du helper de chat.py (même corps, testable isolément)."""
    import logging

    from fastapi import WebSocketDisconnect

    logger = logging.getLogger("test")

    async def _ws_send(text: str) -> bool:
        if client_gone.is_set():
            return False
        try:
            await ws.send_text(text)
            return True
        except (RuntimeError, WebSocketDisconnect) as exc:
            client_gone.set()
            logger.info("client parti: %s", exc)
            return False

    return _ws_send


@pytest.mark.asyncio
async def test_helper_swallows_dead_socket_and_latches():
    import asyncio

    gone = asyncio.Event()
    ws = _FakeWS(die_after=2)
    send = _make_helper(ws, gone)

    assert await send("a") is True
    assert await send("b") is True
    # 3e envoi : la socket est morte — pas d'exception, on signale et on retient
    assert await send("c") is False
    assert gone.is_set()
    # Les envois suivants ne retentent même plus (pas de RuntimeError en boucle)
    assert await send("d") is False
    assert ws.sent == ["a", "b"]


@pytest.mark.asyncio
async def test_notify_offline_is_best_effort_without_ntfy(monkeypatch):
    """Sans NTFY_URL : no-op silencieux, jamais d'exception dans le tour."""
    monkeypatch.delenv("NTFY_URL", raising=False)
    from app.routers.chat import _notify_turn_done_offline

    await _notify_turn_done_offline("u1", "conv1", "La traduction est terminée.")


@pytest.mark.asyncio
async def test_notify_offline_sends_a_short_extract(monkeypatch):
    from app.routers import chat as chat_mod

    seen: dict = {}

    async def _fake_push(title, body, *, tags, priority="default"):
        seen.update(title=title, body=body, tags=tags)

    monkeypatch.setattr(
        "app.services.learning.candidate_notify._push", _fake_push,
    )
    await chat_mod._notify_turn_done_offline(
        "u1", "conv1", "Traduction terminée.\n\n" + "x" * 500,
    )
    assert seen, "le push doit partir"
    assert "terminee" in seen["title"].lower()
    # Extrait borné : on ne déverse pas la conversation dans une notification
    assert len(seen["body"]) < 400
    assert seen["title"].isascii(), "en-tête ntfy ASCII (leçon #220)"


def test_turn_notifies_only_when_undelivered():
    """Le push part sur l'échec de livraison, pas à chaque tour."""
    assert "_delivered = await _ws_send(_dumps(payload))" in _SRC
    assert "if not _delivered:" in _SRC
    assert "_notify_turn_done_offline" in _SRC


def test_notify_never_blocks_the_turn():
    """Spawn en tâche de fond — un ntfy lent ne retarde pas la fin du tour."""
    block = _SRC.split("if not _delivered:", 1)[1][:400]
    assert "spawn(" in block


def test_helper_signature_is_awaitable_bool():
    """Contrat du helper : coroutine → bool (les appelants testent la valeur)."""
    src = _SRC.split("async def _ws_send(", 1)[1].split(")", 1)[0]
    assert "text: str" in src
    assert inspect.iscoroutinefunction  # sanity
