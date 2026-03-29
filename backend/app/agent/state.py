from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    google_credentials: str
    domain: str        # routing field: "research" | "workspace" | "infra" | "general"
    model_used: str    # "slm:<model>" or "llm:<model>" — set by agent_node for feedback
    routing_score: int # IntentRouter score 0-100 — stored for Phase 2 training
