# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/state.py
# @brief      MissionState — LangGraph state schema for the persistence loop
# =============================================================================
"""LangGraph state schema for the persistence loop.

This is the dictionary-shaped state that flows through Plan→Act→Eval→Replan.
Mutated nodes return partial dicts that LangGraph merges into the global
state. The `messages` list uses the standard `add_messages` reducer so
appends accumulate across nodes.
"""
from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class MissionState(TypedDict, total=False):
    """State carried through one iteration of the loop.

    Persisted automatically by the AsyncSqliteSaver between ticks — when
    the heartbeat resumes a mission, all these fields are restored from
    the checkpoint.
    """
    # ── Identity (set at graph entry, never mutated) ──
    mission_id: str
    user_id: str
    goal: str

    # ── Plan (mutated by `plan_node` and `replan_node`) ──
    plan_text: str                  # human-readable markdown
    plan_json: Optional[dict]       # structured: {steps: [{id, description, status}]}
    plan_version: int               # incremented on each replan

    # ── Current iteration context ──
    current_step_id: Optional[str]  # which subtask we're working on
    iteration: int                  # tick counter (1, 2, 3…)

    # ── Sprint 4c (missions structurées) — contexte d'item ──
    current_item_index: Optional[int]   # index dans mission_step_runs (foreach)
    last_edge_case: Optional[dict]      # {"name": …, "detail": …} signalé par l'acteur

    # ── Last action telemetry (set by `act_node`, read by `eval_node`) ──
    last_tool_name: Optional[str]
    last_tool_input: Optional[dict]
    last_tool_output: Optional[str]
    # Le tour entier de l'acteur : les actions jouées dans ce tick, dans
    # l'ordre ({"tool", "ok"}), et sa conclusion en texte quand il a cessé
    # d'appeler des outils. L'évaluateur juge l'ÉTAPE, pas le dernier appel.
    tick_actions: list[dict]
    actor_final_text: Optional[str]

    # ── Last evaluation verdict (set by `eval_node`) ──
    last_eval_success: Optional[bool]
    last_eval_reason: Optional[str]
    consecutive_failures: int  # bumps on failure, resets on success — used to trigger replan

    # ── Conversation buffer (LLM context for next call) ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Terminal flags (any True → loop exits) ──
    done: bool
    final_summary: Optional[str]
    failed: bool
    failure_reason: Optional[str]
