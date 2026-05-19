# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/sub_agents/state.py
# @brief      LangGraph agent state schema
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SubAgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    # conversation_id needed to look up the per-conversation SecurityFilter
    # at tool execution time, so we can deanonymize [EMAIL_N]/[IBAN_N]/etc.
    # placeholders in tool args before they reach external APIs (Gmail, etc.)
    conversation_id: str
    # google_credentials removed — credentials are kept server-side in
    # app.services.credential_store (SEC-1) and looked up by user_id at
    # tool execution time. They never travel through the graph state.
    #
    # ── Memory cache (perf optim 2026-04-23) ─────────────────────────────
    # On stocke ici les blocs mémoire chargés au 1er tour de l'agent, pour
    # les RÉUTILISER aux itérations suivantes (tool calls en chaîne) sans
    # relancer get_relevant_* à chaque tool call. Invalide le cache du LLM
    # local (LM Studio) parce que les valeurs changent → et chaque
    # invalidation = +30-45s de prompt processing sur Gemma MLX 26B.
    # Tous total=False donc un état sans ces champs reste valide.
    _mem_constraints: list[str]
    _mem_memories: list[str]
    _mem_interactions: list[dict]
    _mem_user_ctx: str
    _mem_fetched_for_query: str   # sentinel = user_query pour lequel on a fetch
