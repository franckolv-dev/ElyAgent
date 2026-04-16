# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/sub_agents/state.py
# @brief      LangGraph agent state schema
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

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SubAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    # google_credentials removed — credentials are kept server-side in
    # app.services.credential_store (SEC-1) and looked up by user_id at
    # tool execution time. They never travel through the graph state.
