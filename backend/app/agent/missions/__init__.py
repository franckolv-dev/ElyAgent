# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/__init__.py
# @brief      Persistence-loop / goal-driven agent module
# =============================================================================
"""Persistence-loop (goal-driven) agent module.

Distinct from the request-response supervisor in `app/agent/supervisor.py` :
this is the cyclic Plan → Act → Eval → Replan loop that pursues a Mission
across multiple iterations and survives backend restarts.
"""
from app.agent.missions.checkpointer import get_mission_checkpointer
from app.agent.missions.graph import build_mission_graph

__all__ = ["get_mission_checkpointer", "build_mission_graph"]
