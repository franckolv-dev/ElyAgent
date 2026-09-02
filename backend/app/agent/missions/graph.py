# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/graph.py
# @brief      Persistence-loop LangGraph topology (Plan → Act → Eval → Replan)
# =============================================================================
"""Persistence-loop LangGraph topology.

PHASE 2 — node implementations live in `nodes.py`. This file is just the
topology + routing decisions.

Topology :

    [START] ──► plan ──► act ──► eval ──► (decide_next)
                  ▲                              │
                  └──── replan ◄─── failure ─────┤
                                                 │
                       END ◄──── success/done ───┘

Decisions :
  - `plan` is the entry point. On a fresh mission it builds plan v1; on a
    resumed mission with an existing plan_version, it just refreshes
    state and falls through to act.
  - `eval` is where success/failure is judged AND where the budget is
    checked (single source of truth).
  - `replan` is only called when consecutive_failures ≥ 3.
  - The graph EXITS at the end of one iteration. The heartbeat re-enters
    it on the next tick. Inside `act`, the actor chains its tool calls in
    one conversation (bounded by MAX_ACTIONS_PER_TICK) so that one tick is
    one attempt at the step, not one tool call — but the graph itself
    never loops : the budget guards and the kill-switch keep their grip
    between ticks.
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, START, END

from app.agent.missions.state import MissionState
from app.agent.missions.nodes import plan_node, act_node, eval_node, replan_node

logger = logging.getLogger(__name__)


# ── Routing ──────────────────────────────────────────────────────────────────

def decide_after_eval(state: MissionState) -> Literal["replan", "end"]:
    """Where to go after evaluation.

    - If `done` flag set → exit graph (heartbeat re-enters next tick if
      mission still has work).
    - If `consecutive_failures` ≥ 3 → replan.
    - Otherwise also exit; the heartbeat will pick the next sub-task on
      the next tick.
    """
    if state.get("done"):
        return "end"
    if state.get("failed"):
        return "end"
    failures = state.get("consecutive_failures", 0)
    if failures >= 3:
        return "replan"
    return "end"


def decide_after_plan(state: MissionState) -> Literal["act", "end"]:
    """If planning failed catastrophically, exit early."""
    if state.get("failed"):
        return "end"
    return "act"


# ── Graph builder ────────────────────────────────────────────────────────────

def build_mission_graph() -> StateGraph:
    """Compile the persistence-loop graph.

    Returns the *uncompiled* StateGraph — caller must do
    `.compile(checkpointer=...)` to get a runnable graph.

    Caller is responsible for providing the checkpointer at compile time
    (so tests can use MemorySaver while production uses AsyncSqliteSaver).
    """
    g = StateGraph(MissionState)

    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("eval", eval_node)
    g.add_node("replan", replan_node)

    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", decide_after_plan, {"act": "act", "end": END})
    g.add_edge("act", "eval")
    g.add_conditional_edges("eval", decide_after_eval, {"replan": "replan", "end": END})
    g.add_edge("replan", "act")  # after replan, retry directly

    return g
