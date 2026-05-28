# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_rpc.py
# @brief      RPC server UDS pour le sandbox orchestrate (Sprint 2.7 — Jalon 2).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    0.2.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""RPC server UDS pour le sandbox ``orchestrate``.

Le serveur tourne dans un thread dédié côté parent (backend), écoute sur
une Unix Domain Socket éphémère dans ``/tmp/`` (nom = UUID par run), et
dispatche les appels du child sandbox vers le ``tool_dispatcher`` fourni
par le runner.

Protocole de transport
======================
Length-prefixed JSON :

    [4-byte unsigned int big-endian = longueur du payload][payload JSON UTF-8]

Justification vs newline-delimited : les payloads peuvent contenir
``\\n`` (extraits HTML, sorties de tools verbeuses…). Le header
explicite élimine toute ambiguïté de délimiteur. ``struct.pack("!I")``
limite à 4 GiB — bien plus que nécessaire ; on cap à ``_MAX_PAYLOAD_BYTES``
côté serveur pour parer aux attaques de saturation mémoire.

Format des messages
===================
Requête (child → parent) :

    {"tool": "gmail_list_emails", "args": {"query": "from:shein.com"}}

Réponse succès (parent → child) :

    {"ok": true, "result": <any-JSON-serialisable>}

Réponse erreur (parent → child) :

    {"ok": false, "error": "...", "error_type": "ToolNotAllowed"}

Sérialisation
=============
Tous les appels sont sérialisés via ``_call_lock`` (threading.Lock). Pas
de parallélisme côté script — c'est le trade-off accepté par Hermes
v0.12.0 (fix de la course concurrente RPC sans request-id).

Allow-list enforcement (§4.1)
=============================
Tout appel à un tool absent de ``allowed_tools`` retourne
``ToolNotAllowed`` immédiatement (sans incrémenter ``dispatch_count``,
sans rien tenter d'exécuter). Le message d'erreur liste les tools
autorisés — utile pour que le LLM corrige son script au prochain tour.

Comptage tools_dispatched (§4.4 — décision actée le 19 mai)
===========================================================
Chaque dispatch réussi append le nom du tool à ``_tools_dispatched``.
Le runner lit cette liste après le ``stop()`` et la transmet au nœud
agent qui la passera au ``completion_guard``. Permet de détecter une
hallucination du type « j'ai supprimé X » alors qu'aucun tool destructif
n'a effectivement été appelé.

Dispatcher async
================
Le ``tool_dispatcher`` peut retourner une coroutine — typique vu que
les tools ELY sont quasiment tous ``async def``. Le serveur RPC tourne
dans un thread (pas dans l'event loop FastAPI), donc on instancie un
event loop dédié au thread (``asyncio.new_event_loop()``) et on
``run_until_complete()`` chaque coroutine. Le loop est fermé proprement
au ``stop()``.

Anonymisation (§4.2 — Jalon 6)
==============================
Branchement prévu dans ``_handle_request`` :
    - avant dispatch : ``security_filter.deanonymize`` des ``args``
    - après dispatch : ``security_filter.anonymize`` du ``result``

Non implémenté ici (Jalon 6), le code documente les hooks via TODO.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Protocole de transport
# ──────────────────────────────────────────────────────────────────────

_HEADER_FMT = "!I"           # 4-byte unsigned int big-endian
_HEADER_SIZE = 4
_MAX_PAYLOAD_BYTES = 4_000_000   # 4 MB — protection saturation côté serveur
_RECV_CHUNK = 65_536
_ACCEPT_TIMEOUT_SECONDS = 0.2    # pour vérifier _stop_event périodiquement
_CONN_TIMEOUT_SECONDS = 60.0     # patience laissée aux scripts lents


# ──────────────────────────────────────────────────────────────────────
# Erreurs structurées (retournées au script côté child)
# ──────────────────────────────────────────────────────────────────────


class OrchestrateRPCError(Exception):
    """Erreur côté serveur RPC, retournée comme dict JSON au child."""


class ToolNotAllowedError(OrchestrateRPCError):
    """Le script a tenté d'appeler un tool hors ``allowed_tools``."""


class MaxToolCallsExceeded(OrchestrateRPCError):
    """Le script a dépassé ``max_tool_calls`` (DoS-protection)."""


# ──────────────────────────────────────────────────────────────────────
# RPC server
# ──────────────────────────────────────────────────────────────────────


class OrchestrateRPCServer:
    """Serveur RPC UDS pour un run sandbox.

    Cycle de vie typique :

        rpc = OrchestrateRPCServer(
            user_id=user_id,
            allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
            max_tool_calls=50,
            tool_dispatcher=my_dispatcher,
        )
        socket_path = rpc.start()
        try:
            # ... lancer le subprocess child avec ELY_RPC_SOCKET=socket_path ...
        finally:
            rpc.stop()
        dispatched = rpc.tools_dispatched
    """

    def __init__(
        self,
        *,
        user_id: str,
        allowed_tools: frozenset[str],
        max_tool_calls: int,
        tool_dispatcher: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        if not user_id:
            raise ValueError("OrchestrateRPCServer requires a non-empty user_id")
        if not allowed_tools:
            raise ValueError("OrchestrateRPCServer requires a non-empty allow-list")
        if max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be > 0")
        if tool_dispatcher is None:
            raise ValueError("tool_dispatcher must not be None")

        self.user_id = user_id
        self.allowed_tools = allowed_tools
        self.max_tool_calls = max_tool_calls
        self.tool_dispatcher = tool_dispatcher

        self._socket_path: Path | None = None
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._call_lock = threading.Lock()
        self._tools_dispatched: list[str] = []
        self._dispatch_count = 0
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────

    def start(self) -> Path:
        """Crée le socket UDS, lance le thread d'accept-loop, retourne le path."""
        if self._thread is not None:
            raise RuntimeError("OrchestrateRPCServer already started")

        self._socket_path = make_socket_path()
        # Should not exist (UUID-based) but defensive.
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(self._socket_path))
        os.chmod(self._socket_path, 0o600)
        self._server_socket.listen(1)
        self._server_socket.settimeout(_ACCEPT_TIMEOUT_SECONDS)

        self._thread = threading.Thread(
            target=self._accept_loop,
            daemon=True,
            name=f"OrchestrateRPC-{self.user_id}",
        )
        self._thread.start()

        logger.debug(
            "OrchestrateRPCServer started for user=%s on %s", self.user_id, self._socket_path
        )
        return self._socket_path

    def stop(self, timeout: float = 5.0) -> None:
        """Arrête le serveur — set stop_event, join thread, close socket."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "OrchestrateRPCServer.stop(): thread did not exit cleanly for user=%s",
                    self.user_id,
                )
            self._thread = None
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        if self._socket_path is not None and self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass

    @property
    def tools_dispatched(self) -> list[str]:
        """Liste ordonnée des tools effectivement appelés via RPC."""
        return list(self._tools_dispatched)

    @property
    def dispatch_count(self) -> int:
        return self._dispatch_count

    @property
    def socket_path(self) -> Path | None:
        return self._socket_path

    # ── Internals ─────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Thread principal — boucle d'accept jusqu'à stop_event."""
        # Each thread needs its own event loop for awaiting async tools.
        self._loop = asyncio.new_event_loop()
        try:
            assert self._server_socket is not None
            while not self._stop_event.is_set():
                try:
                    conn, _ = self._server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    # Server socket closed by stop()
                    break
                try:
                    self._handle_connection(conn)
                except Exception:  # noqa: BLE001 — never let the thread die silently
                    logger.exception(
                        "OrchestrateRPCServer: unhandled exception in connection handler"
                    )
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
        finally:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass
            self._loop = None

    def _handle_connection(self, conn: socket.socket) -> None:
        """Boucle read-request / send-response sur une connexion client."""
        conn.settimeout(_CONN_TIMEOUT_SECONDS)
        while not self._stop_event.is_set():
            try:
                request = _recv_message(conn)
            except (ConnectionError, OSError, socket.timeout):
                return
            except OrchestrateRPCError as exc:
                # Bad framing — send error and close.
                try:
                    _send_message(conn, {
                        "ok": False,
                        "error": str(exc),
                        "error_type": "ProtocolError",
                    })
                except (ConnectionError, OSError):
                    pass
                return

            if request is None:
                return  # clean EOF, child closed its end

            response = self._handle_request(request)
            try:
                _send_message(conn, response)
            except (ConnectionError, OSError):
                return

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch une requête déjà décodée. Sérialisé via ``_call_lock``."""
        with self._call_lock:
            tool_name = request.get("tool")
            args = request.get("args") or {}

            # ── Format validation ─────────────────────────────────────
            if not isinstance(tool_name, str) or not tool_name:
                return _error("missing or invalid 'tool' field", "BadRequest")
            if not isinstance(args, dict):
                return _error("'args' must be a dict", "BadRequest")

            # ── Resource cap (DoS protection) ─────────────────────────
            if self._dispatch_count >= self.max_tool_calls:
                return _error(
                    f"max_tool_calls={self.max_tool_calls} exceeded — "
                    f"the sandbox refuses further dispatches in this run",
                    "MaxToolCallsExceeded",
                )

            # ── Allow-list enforcement ────────────────────────────────
            if tool_name not in self.allowed_tools:
                return _error(
                    f"tool {tool_name!r} is not in the sandbox allow-list. "
                    f"Available: {sorted(self.allowed_tools)}",
                    "ToolNotAllowed",
                )

            # TODO Jalon 6 : security_filter.deanonymize(args)
            #   args = await security_filter.deanonymize(args, user_id=self.user_id)

            # ── Real dispatch ─────────────────────────────────────────
            try:
                result = self.tool_dispatcher(tool_name, args)
                if asyncio.iscoroutine(result):
                    assert self._loop is not None
                    result = self._loop.run_until_complete(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "orchestrate RPC dispatcher failed for tool=%s user=%s",
                    tool_name, self.user_id,
                )
                return _error(str(exc), type(exc).__name__)

            # TODO Jalon 6 : result = security_filter.anonymize(result, user_id=...)

            self._tools_dispatched.append(tool_name)
            self._dispatch_count += 1
            return {"ok": True, "result": result}


# ──────────────────────────────────────────────────────────────────────
# Frame I/O helpers (length-prefixed JSON)
# ──────────────────────────────────────────────────────────────────────


def _recv_exact(conn: socket.socket, n: int) -> bytes | None:
    """Read exactly ``n`` bytes from ``conn``, or return None on clean EOF.

    Returns ``b""`` if zero bytes are requested. Returns ``None`` if the
    peer closed the connection before any byte arrived.
    """
    if n == 0:
        return b""
    buf = bytearray()
    while len(buf) < n:
        remaining = n - len(buf)
        chunk = conn.recv(min(remaining, _RECV_CHUNK))
        if not chunk:
            return None if not buf else bytes(buf)
        buf.extend(chunk)
    return bytes(buf)


def _recv_message(conn: socket.socket) -> dict[str, Any] | None:
    """Read one length-prefixed JSON message, or return None on clean EOF."""
    header = _recv_exact(conn, _HEADER_SIZE)
    if header is None:
        return None
    if len(header) < _HEADER_SIZE:
        raise OrchestrateRPCError("truncated header from RPC client")
    (length,) = struct.unpack(_HEADER_FMT, header)
    if length > _MAX_PAYLOAD_BYTES:
        raise OrchestrateRPCError(
            f"payload too large: {length} bytes (max {_MAX_PAYLOAD_BYTES})"
        )
    if length == 0:
        return {}
    payload = _recv_exact(conn, length)
    if payload is None or len(payload) < length:
        raise OrchestrateRPCError("truncated payload from RPC client")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrchestrateRPCError(f"invalid JSON from RPC client: {exc}") from exc
    if not isinstance(decoded, dict):
        raise OrchestrateRPCError("RPC payload must be a JSON object")
    return decoded


def _send_message(conn: socket.socket, data: dict[str, Any]) -> None:
    """Send one length-prefixed JSON message."""
    payload = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
    if len(payload) > _MAX_PAYLOAD_BYTES:
        # Truncate cleanly with a marker rather than crashing the sandbox.
        truncated = {
            "ok": False,
            "error": (
                f"response too large ({len(payload)} bytes > "
                f"{_MAX_PAYLOAD_BYTES} max) — tool result truncated"
            ),
            "error_type": "ResponseTooLarge",
        }
        payload = json.dumps(truncated).encode("utf-8")
    header = struct.pack(_HEADER_FMT, len(payload))
    conn.sendall(header + payload)


def _error(message: str, error_type: str) -> dict[str, Any]:
    """Build a structured error response."""
    return {"ok": False, "error": message, "error_type": error_type}


# ──────────────────────────────────────────────────────────────────────
# Helpers — création du socket path unique
# ──────────────────────────────────────────────────────────────────────


def make_socket_path() -> Path:
    """Génère un path UDS unique dans ``/tmp/`` pour un nouveau run.

    Format : ``/tmp/ely_orchestrate_<uuid4>.sock`` — pas de collision
    possible entre runs concurrents.
    """
    return Path("/tmp") / f"ely_orchestrate_{uuid.uuid4().hex}.sock"


__all__ = [
    "OrchestrateRPCError",
    "ToolNotAllowedError",
    "MaxToolCallsExceeded",
    "OrchestrateRPCServer",
    "make_socket_path",
]
