# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/sub_agents/registry.py
# @brief      Registry module
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
    from app.agent.sub_agents.config import SubAgentConfig

logger = logging.getLogger(__name__)


class SubAgentRegistry:
    """Thread-safe singleton registry of compiled sub-agent graphs.

    Each sub-agent is compiled once at startup via ``register()`` and can then
    be retrieved cheaply with ``get()``.  The registry never recompiles unless
    explicitly asked to via ``register()`` (which replaces an existing entry).
    """

    def __init__(self) -> None:
        self._graphs: dict[str, "CompiledStateGraph"] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, config: "SubAgentConfig") -> None:
        """Compile the sub-agent graph for *config* and store it.

        Safe to call multiple times — a second call for the same agent name
        replaces the previous compiled graph (useful for hot-reload scenarios).
        """
        from app.agent.sub_agents.factory import build_sub_agent_graph

        try:
            graph = build_sub_agent_graph(config)
            with self._lock:
                self._graphs[config.name] = graph
            logger.info(
                "Sub-agent compiled and registered: %s (%s)",
                config.display_name,
                config.name,
            )
        except Exception as exc:
            logger.error(
                "Failed to compile sub-agent '%s': %s — it will not be available",
                config.name,
                exc,
                exc_info=True,
            )

    # ------------------------------------------------------------------ #
    # Retrieval                                                            #
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> "CompiledStateGraph | None":
        """Return the compiled graph for *name*, or None if not registered."""
        with self._lock:
            return self._graphs.get(name)

    def list_names(self) -> list[str]:
        """Return the names of all registered sub-agents."""
        with self._lock:
            return list(self._graphs.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._graphs)


@lru_cache(maxsize=1)
def get_sub_agent_registry() -> SubAgentRegistry:
    """Return the process-wide SubAgentRegistry singleton."""
    return SubAgentRegistry()
