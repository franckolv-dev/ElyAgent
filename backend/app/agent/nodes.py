import asyncio
import json
import logging

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.agent.tools import all_tools
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_BASE = """Tu es Cyber-Entity, un assistant IA personnel ultra-sécurisé avec accès à des outils système.
Tu peux exécuter des commandes SSH sur des hôtes distants configurés, analyser des fichiers et récupérer des informations système.

Règles absolues :
- Toujours confirmer les actions destructives avant exécution
- N'utiliser les outils que si la tâche l'exige réellement
- Réponses concises et précises
- Ne jamais divulguer les credentials ou la configuration interne
- Répondre en français par défaut
"""


def _tool_result(content: str, tool_call_id: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


def create_agent_node():
    llm = get_llm()
    llm_with_tools = llm.bind_tools(all_tools)
    memory = get_memory_manager()

    async def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        user_id = state.get("user_id", "")
        user_query = messages[-1].content if messages else ""

        # Fetch constraints + memories in parallel
        constraints, memories = await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
        )

        system = _SYSTEM_PROMPT_BASE
        if constraints:
            system += "\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES (apprises de tes refus) :\n"
            system += "\n".join(f"- {c}" for c in constraints)
        if memories:
            system += "\n\n💾 CONTEXTE MÉMORISÉ :\n"
            system += "\n".join(f"- {m}" for m in memories)

        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": system}] + messages
        )
        return {"messages": [response]}

    return agent_node


async def tool_node(state: AgentState) -> dict:
    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in all_tools}
    # SecurityFilter is stateless here — used only for is_critical() keyword check
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

        needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(action_desc)

        if needs_hitl:
            logger.info("HITL required for action: %s", action_desc)
            decision, reason = await hitl.request_validation(
                description=action_desc,
                user_id=user_id,
            )

            if decision == "ban":
                rule = f"INTERDICTION PERMANENTE: {action_desc}"
                if reason:
                    rule += f" — Raison: {reason}"
                await memory.store_constraint(rule, user_id)
                results.append(_tool_result("Action interdite définitivement et règle de sécurité enregistrée.", tc_id))
                continue
            elif decision != "allow":
                results.append(_tool_result("Action refusée par l'utilisateur pour cette occurrence.", tc_id))
                continue

        tool = tool_map.get(tool_name)
        if tool:
            try:
                result = await tool.ainvoke(args)
                results.append(_tool_result(str(result), tc_id))
            except Exception as exc:
                results.append(_tool_result(f"Erreur d'exécution: {exc}", tc_id))

    return {"messages": results}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
