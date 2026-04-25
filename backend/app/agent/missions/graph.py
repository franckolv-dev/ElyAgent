# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/graph.py
# @brief      Persistence-loop LangGraph topology (Plan → Act → Eval → Replan)
# =============================================================================
"""Persistence-loop LangGraph topology.

PHASE 1 SCOPE — this is the SKELETON only. Each node is a stub that logs
its execution and returns a minimal state mutation. The real reasoning
(actual planning with the LLM, real tool dispatch, real evaluation) lands
in PHASE 2.

The topology itself is final and matches what we agreed on :

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
  - `replan` is only called when consecutive_failures ≥ N (config).
  - The graph EXITS at the end of one iteration. The heartbeat re-enters
    it on the next tick. We don't run a tight inner loop because that
    would defeat the budget guards and the kill-switch.
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, START, END

from app.agent.missions.state import MissionState

logger = logging.getLogger(__name__)


# ── Node stubs (Phase 1 placeholders) ─────────────────────────────────────────

async def plan_node(state: MissionState) -> dict:
    """Build or refresh the plan for the mission.

    PHASE 1: trivial pass-through that initializes plan_version=1 if
    missing and logs the goal.
    PHASE 2: will call the LLM with the goal + existing plan + recent
    history to produce a structured plan tree.
    """
    mid = state.get("mission_id", "?")
    iteration = state.get("iteration", 0) + 1
    plan_version = state.get("plan_version", 0)

    if plan_version == 0:
        logger.info("[mission %s] plan_node: building initial plan (iter=%d)", mid, iteration)
        return {
            "iteration": iteration,
            "plan_version": 1,
            "plan_text": f"# Plan v1\n\n- [ ] Atteindre le goal : {state.get('goal','')[:200]}",
            "consecutive_failures": 0,
        }
    logger.info("[mission %s] plan_node: existing plan v%d (iter=%d)", mid, plan_version, iteration)
    return {"iteration": iteration}


async def act_node(state: MissionState) -> dict:
    """Execute the next concrete action (tool call) toward the current step.

    PHASE 1: no-op — returns a synthetic "noop" tool result so the loop
    can exit cleanly.
    PHASE 2: will invoke the LLM with the plan + tools, capture the
    tool_call, dispatch it through the existing ToolNode infrastructure,
    and write the result back to state.
    """
    mid = state.get("mission_id", "?")
    logger.info("[mission %s] act_node: (Phase 1 stub — no real action)", mid)
    return {
        "last_tool_name": "noop",
        "last_tool_input": {},
        "last_tool_output": "Phase 1 skeleton — real action wiring lands in Phase 2.",
    }


async def eval_node(state: MissionState) -> dict:
    """Judge whether the last action succeeded and update counters.

    PHASE 1: hardcodes success=True so the loop exits at done.
    PHASE 2: will compare tool output to the step's expected outcome,
    consult the LLM if ambiguous, and feed `consecutive_failures` accordingly.
    """
    mid = state.get("mission_id", "?")
    logger.info("[mission %s] eval_node: (Phase 1 stub — synthetic success)", mid)
    return {
        "last_eval_success": True,
        "last_eval_reason": "Phase 1 skeleton — no real evaluation yet.",
        "consecutive_failures": 0,
        "done": True,
        "final_summary": (
            f"[skeleton] Goal reçu: {state.get('goal','?')[:100]}. "
            "La logique réelle Plan→Act→Eval arrive en Phase 2."
        ),
    }


async def replan_node(state: MissionState) -> dict:
    """Build a new plan version after repeated failures.

    PHASE 1: simply bumps plan_version with a stub plan.
    PHASE 2: real LLM-driven replan with reflection on what went wrong.
    """
    mid = state.get("mission_id", "?")
    new_version = state.get("plan_version", 1) + 1
    logger.info("[mission %s] replan_node: bumping to v%d", mid, new_version)
    return {
        "plan_version": new_version,
        "plan_text": f"# Plan v{new_version}\n\n- [ ] Tentative alternative",
        "consecutive_failures": 0,
    }


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
