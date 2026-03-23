"""Agent graph — builds and returns the compiled LangGraph.

The supervisor-based multi-agent architecture is used by default:
  router → {research | workspace | infra | general} → tools → (loop)

The old single-agent graph is kept as ``build_simple_agent_graph()`` for
testing and for channels (Telegram, WhatsApp, scheduler) that build their
own graph instance and may want the simpler version.

``build_agent_graph()`` is the public API used by all callers.
"""
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes import create_agent_node, tool_node, should_continue


def build_simple_agent_graph() -> StateGraph:
    """Single-agent graph (original architecture).

    Useful for unit tests or when the supervisor overhead is not desired.
    """
    graph = StateGraph(AgentState)
    graph.add_node("agent", create_agent_node())
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def build_agent_graph() -> StateGraph:
    """Multi-agent supervisor graph (production architecture).

    Routes each request to the most appropriate specialist:
    - research  : web, weather, news, translate, browser
    - workspace : Gmail, Calendar, Drive, Docs, Sheets, Tasks
    - infra     : SSH, cron, watchdog, briefing
    - general   : all tools (complex / cross-domain requests)
    """
    from app.agent.supervisor import build_supervisor_graph
    return build_supervisor_graph()
