# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/checkpointer.py
# @brief      LangGraph AsyncSqliteSaver singleton for mission state
# =============================================================================
"""LangGraph AsyncSqliteSaver singleton for persistence loops.

Each mission has its own `thread_id` (the mission UUID), and LangGraph
stores the full graph state (messages, tool calls, intermediate variables)
in `data/missions_checkpoints.sqlite`. This is what makes a mission
**resumable across backend restarts** — when the heartbeat loop ticks a
mission again, it loads the exact state and continues.

The user-visible metadata (status, plan, audit trail) lives in the main
SQL DB via `app/models/mission.py`. These two stores complement each
other: the checkpointer is the engine's memory, the SQL tables are the
human-readable record.

Usage :
    from app.agent.missions.checkpointer import get_mission_checkpointer

    cp = await get_mission_checkpointer()
    graph = build_mission_graph().compile(checkpointer=cp)

    # First tick of a new mission
    state = await graph.ainvoke({...}, config={"configurable": {"thread_id": mission.id}})

    # Later tick (resume) — same thread_id, no need to repass the full history
    state = await graph.ainvoke({...}, config={"configurable": {"thread_id": mission.id}})
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default location: persistent volume so missions survive Docker container
# recreation (the `data/` dir is mounted from the host in docker-compose).
_DEFAULT_DB_PATH = "/app/data/missions_checkpoints.sqlite"

_checkpointer = None  # lazy-init singleton
_checkpointer_ctx = None  # holds the async context manager so we can close it


async def get_mission_checkpointer():
    """Lazy-init and return the global AsyncSqliteSaver singleton.

    `langgraph-checkpoint-sqlite` exposes the saver as an async context
    manager. We open it once at first call and keep it alive for the
    lifetime of the backend (closed at shutdown via `close_mission_checkpointer`).
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer is not None:
        return _checkpointer

    db_path = os.environ.get("MISSIONS_CHECKPOINT_DB", _DEFAULT_DB_PATH)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    _checkpointer_ctx = AsyncSqliteSaver.from_conn_string(db_path)
    _checkpointer = await _checkpointer_ctx.__aenter__()
    logger.info("Mission checkpointer initialized at %s", db_path)
    return _checkpointer


async def close_mission_checkpointer() -> None:
    """Close the checkpointer cleanly. Called at FastAPI shutdown."""
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            await _checkpointer_ctx.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("Failed to close mission checkpointer cleanly: %s", exc)
        _checkpointer_ctx = None
        _checkpointer = None
