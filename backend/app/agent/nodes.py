from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.agent.tools import all_tools
from app.services.llm_provider import get_llm

SYSTEM_PROMPT = """You are Cyber-Entity, an AI assistant with access to system tools.
You can execute SSH commands on configured remote hosts, analyze files, and retrieve system information.

Rules:
- Always confirm destructive actions before executing
- Only use tools when explicitly asked or when the task requires it
- Be concise and clear in your responses
- If a command is blocked, explain why and suggest alternatives
- Never reveal system credentials or internal configuration details
"""


def create_agent_node():
    llm = get_llm()
    llm_with_tools = llm.bind_tools(all_tools)

    async def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        )
        return {"messages": [response]}

    return agent_node


async def tool_node(state: AgentState) -> dict:
    last_message = state["messages"][-1]
    results = []

    tool_map = {t.name: t for t in all_tools}

    for tool_call in last_message.tool_calls:
        tool = tool_map.get(tool_call["name"])
        if tool:
            result = await tool.ainvoke(tool_call["args"])
            results.append(
                {"role": "tool", "content": str(result), "tool_call_id": tool_call["id"]}
            )

    return {"messages": results}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
