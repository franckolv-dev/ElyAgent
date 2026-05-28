# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/state.py
# @brief      LangGraph agent state schema
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    # google_credentials removed — credentials are kept server-side in
    # app.services.credential_store (SEC-1) and looked up by user_id at
    # tool execution time. They never travel through the graph state.
    domain: str        # routing field: "research" | "workspace" | "infra" | "general"
    model_used: str    # "slm:<model>" or "llm:<model>" — set by agent_node for feedback
    routing_score: int # IntentRouter score 0-100 — stored for Phase 2 training
    # Hermes-style sticky toolset profile (Chantier 1, 2026-05-07).
    # Set once per conversation by the chat router (auto-detect on first
    # message or `/profile <name>` slash command). agent_node reads this
    # to bind the same ~30-tool catalog every turn — no per-turn keyword
    # filtering. Empty string ("") = fall back to the legacy keyword
    # filter (graceful migration: existing conversations created before
    # this column have NULL → "" → legacy behaviour).
    toolset_profile: str
    # Hermes Chantier 9 — iteration budget guard.
    # Incremented by ``agent_node`` each time it returns a response carrying
    # tool_calls (i.e. the loop will go back through ``tool_node`` and
    # bounce here for another inference). When the count crosses
    # ``MAX_AGENT_ITERATIONS`` (~80, defined in nodes.py), ``should_continue``
    # routes to ``force_summary`` instead of ``tools`` — the agent makes
    # ONE final API call WITHOUT tools and produces a textual summary so
    # the user always gets something even on tasks that exhaust the budget.
    iteration_count: int
