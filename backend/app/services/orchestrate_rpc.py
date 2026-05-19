# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/orchestrate_rpc.py
# @brief      RPC server UDS pour le sandbox orchestrate.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.1.0-skeleton
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""RPC server UDS pour le sandbox ``orchestrate`` — squelette Jalon 1.

Le serveur tournera dans un thread dédié côté parent (backend), écoutera
sur une Unix Domain Socket éphémère dans ``/tmp/`` (nom = UUID par run),
et dispatchera les appels du child sandbox vers le ``tool_dispatcher``
fourni par le runner.

Status : SKELETON
=================
Toutes les méthodes lèvent ``NotImplementedError``. L'implémentation
arrive au Jalon 2 avec le protocole length-prefixed JSON, la
sérialisation ``_call_lock``, l'allow-list enforcement, et le support
des dispatchers async via event loop dédié au thread.
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
    """Serveur RPC UDS pour un run sandbox — squelette.

    Cycle de vie cible (Jalon 2) :

        rpc = OrchestrateRPCServer(
            user_id=user_id,
            allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
            max_tool_calls=50,
            tool_dispatcher=lambda name, args: ...,
        )
        socket_path = rpc.start()
        try:
            # subprocess child runs with ELY_RPC_SOCKET=socket_path
            ...
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
        self._thread: threading.Thread | None = None
        self._call_lock = threading.Lock()
        self._tools_dispatched: list[str] = []
        self._dispatch_count = 0
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────

    def start(self) -> Path:
        """Démarre le serveur dans un thread et retourne le path UDS.

        Permissions cibles : ``0o600`` (user-only).
        """
        raise NotImplementedError(
            "OrchestrateRPCServer.start() is a skeleton — Jalon 2 pending"
        )

    def stop(self) -> None:
        """Arrête le serveur — set stop_event + join thread + unlink socket."""
        raise NotImplementedError(
            "OrchestrateRPCServer.stop() is a skeleton — Jalon 2 pending"
        )

    @property
    def tools_dispatched(self) -> list[str]:
        """Liste ordonnée des tools effectivement appelés via RPC."""
        return list(self._tools_dispatched)

    @property
    def dispatch_count(self) -> int:
        return self._dispatch_count


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
