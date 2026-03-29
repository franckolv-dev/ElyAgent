from __future__ import annotations

"""Factory that builds an isolated LangGraph StateGraph for a single sub-agent.

Each sub-agent graph has:
  - an ``agent_node``  — calls the LLM (bound to the sub-agent's tool subset)
  - a ``tools_node``   — executes tool calls with HITL + Vault logic
  - the standard ``should_continue`` loop  agent → tools → agent → …
"""

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import StateGraph, END

from app.agent.sub_agents.state import SubAgentState

if TYPE_CHECKING:
    from app.agent.sub_agents.config import SubAgentConfig

logger = logging.getLogger(__name__)


def _sanitize_messages_for_mistral(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Mistral rejects ANY AIMessage where content is None (HTTP 400, error code 3240).
    This applies whether or not tool_calls are present — force content to "" unconditionally."""
    sanitized = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content is None:
            msg = msg.model_copy(update={"content": ""})
        sanitized.append(msg)
    return sanitized


# ──────────────────────────────────────────────────────────────────────────────
# Helpers shared with nodes.py (duplicated here to keep sub-agents isolated)
# ──────────────────────────────────────────────────────────────────────────────

def _tool_result(content: str, tool_call_id: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


# Tools that need automatic argument injection (mirrors nodes.py constants)
_USER_ID_TOOLS = {
    "scheduler_list_tasks",
    "scheduler_create_task",
    "scheduler_delete_task",
    "browser_navigate",
    "browser_search_web",
    "browser_get_text",
    "browser_screenshot",
    "browser_click",
    "browser_fill",
    "browser_close",
    "watchdog_add",
    "watchdog_list",
    "watchdog_remove",
    "notes_create",
    "notes_list",
    "notes_read",
    "notes_update",
    "notes_delete",
    "notes_search",
}

_GOOGLE_TOOLS = {
    "gmail_list_emails",
    "gmail_read_email",
    "gmail_send_email",
    "gmail_list_labels",
    "gmail_create_label",
    "gmail_move_emails",
    "gmail_trash_emails",
    "gmail_search_for_cleanup",
    "calendar_list_events",
    "calendar_create_event",
    "drive_list_files",
    "drive_read_file",
    "docs_create_document",
    "docs_read_document",
    "docs_append_text",
    "sheets_create_spreadsheet",
    "sheets_read_spreadsheet",
    "sheets_append_rows",
    "tasks_list",
    "tasks_create",
    "tasks_complete",
    "contacts_search",
    "contacts_list",
    "contacts_create",
}


# ──────────────────────────────────────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────────────────────────────────────

def build_sub_agent_graph(config: "SubAgentConfig"):
    """Build and compile a StateGraph(SubAgentState) for *config*."""

    # ── Agent node ────────────────────────────────────────────────────────────

    def make_agent_node(cfg: "SubAgentConfig"):
        import asyncio
        import zoneinfo
        from datetime import datetime

        async def agent_node(state: SubAgentState) -> dict:
            from app.skills import get_skill_registry
            from app.services.memory_manager import get_memory_manager
            from app.services.llm_provider import (
                get_llm_for_agent,
                classify_complexity,
                get_llm_for_tier,
            )

            messages = state["messages"]
            user_id = state.get("user_id", "")
            user_query = messages[-1].content if messages else ""

            registry = get_skill_registry()
            memory = get_memory_manager()

            # Filter tools to this sub-agent's declared subset
            agent_tools = [t for t in registry.all_tools if t.name in cfg.tool_names]

            # Complexity routing: classify last user message and select LLM accordingly.
            # If the sub-agent has a fixed provider, use it; otherwise route by complexity.
            # workspace and infra always run multi-step tool sequences → force COMPLEX tier
            # to avoid Mistral's tool-calling history limitation (rejects content="" with
            # tool_calls present, which langchain_mistralai produces from null content).
            _ALWAYS_COMPLEX_AGENTS = {"workspace", "infra"}
            if cfg.llm_provider is not None:
                llm = get_llm_for_agent(cfg)
            elif cfg.name in _ALWAYS_COMPLEX_AGENTS:
                from app.services.llm_provider import ComplexityTier
                llm = get_llm_for_tier(ComplexityTier.COMPLEX)
                logger.debug("Sub-agent '%s': forced COMPLEX tier (multi-step tool agent)", cfg.name)
            else:
                tier = classify_complexity(user_query)
                llm = get_llm_for_tier(tier)
                logger.debug(
                    "Sub-agent '%s': complexity=%s, tier=%s",
                    cfg.name, tier.value, tier.value,
                )

            # Force tool calling on first turn (last message is HumanMessage).
            # Without this, Claude tends to respond with a planning text like "je vais
            # lancer la recherche…" without actually emitting tool_calls, which causes
            # should_continue() to return "end" and the action is never executed.
            # On subsequent turns (last msg = ToolMessage) we use auto so the LLM can
            # either call more tools or produce the final text response.
            from langchain_core.messages import HumanMessage as _HM
            _last = messages[-1] if messages else None
            _force_tools = isinstance(_last, _HM) and bool(agent_tools)
            if _force_tools:
                try:
                    llm_with_tools = llm.bind_tools(agent_tools, tool_choice="any")
                except Exception:
                    llm_with_tools = llm.bind_tools(agent_tools)
            else:
                llm_with_tools = llm.bind_tools(agent_tools)

            # Fetch memory context in parallel
            constraints, memories, past_interactions = await asyncio.gather(
                memory.get_relevant_constraints(user_query, user_id),
                memory.get_relevant_memories(user_query, user_id),
                memory.get_relevant_interactions(user_query, user_id, limit=3),
            )

            # Current date/time (Europe/Paris)
            _tz = zoneinfo.ZoneInfo("Europe/Paris")
            now = datetime.now(_tz)
            _days_fr = [
                "lundi", "mardi", "mercredi", "jeudi",
                "vendredi", "samedi", "dimanche",
            ]
            _months_fr = [
                "", "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            ]
            date_str = (
                f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} "
                f"{now.year}, {now.strftime('%H:%M')}"
            )

            system = cfg.system_prompt
            system += f"\n\nDate et heure : {date_str} (Europe/Paris)\n"

            # Inject structured user profile context if available
            if user_id:
                try:
                    from app.services.memory_service import get_user_context
                    user_ctx = await get_user_context(user_id)
                    if user_ctx:
                        system += f"\n\n{user_ctx}\n"
                except Exception as _ctx_exc:
                    logger.debug("Could not fetch user context: %s", _ctx_exc)

            if constraints:
                system += "\n\nCONTRAINTES DE SECURITE PERMANENTES :\n"
                system += "\n".join(f"- {c}" for c in constraints)
            if memories:
                system += "\n\nCONTEXTE MEMORISE :\n"
                system += "\n".join(f"- {m}" for m in memories)
            if past_interactions:
                system += "\n\nINTERACTIONS PASSEES :\n"
                for p in past_interactions:
                    system += (
                        f"- Q: {p.get('user_message', '')[:120]} "
                        f"-> R: {p.get('assistant_message', '')[:120]}\n"
                    )

            response = await llm_with_tools.ainvoke(
                [{"role": "system", "content": system}]
                + _sanitize_messages_for_mistral(messages)
            )

            # Fire-and-forget: extract facts from this exchange for user memory
            if user_id:
                try:
                    from app.services.memory_service import extract_and_store_facts
                    import asyncio as _asyncio
                    _asyncio.ensure_future(
                        extract_and_store_facts(user_id, "", messages + [response])
                    )
                except Exception as _mem_exc:
                    logger.debug("Memory extraction skipped: %s", _mem_exc)

            return {"messages": [response]}

        agent_node.__name__ = f"{cfg.name}_agent_node"
        return agent_node

    # ── Tools node ────────────────────────────────────────────────────────────

    def make_tools_node(cfg: "SubAgentConfig"):
        async def tools_node(state: SubAgentState) -> dict:
            from app.skills import get_skill_registry
            from app.services.hitl_manager import get_hitl_manager
            from app.services.memory_manager import get_memory_manager
            from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

            last_message = state["messages"][-1]
            user_id = state.get("user_id", "")
            results = []

            # Only expose tools declared for this sub-agent
            tool_map = {
                t.name: t
                for t in get_skill_registry().all_tools
                if t.name in cfg.tool_names
            }
            sf = SecurityFilter()
            hitl = get_hitl_manager()
            memory = get_memory_manager()

            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]
                args = dict(tool_call["args"])
                tc_id = tool_call["id"]

                # Inject hidden arguments
                if tool_name in _GOOGLE_TOOLS:
                    args["user_google_credentials_json"] = (
                        state.get("google_credentials") or ""
                    )
                if tool_name in _USER_ID_TOOLS:
                    args["user_id"] = state.get("user_id") or ""

                # Display args (never expose tokens/injected IDs)
                _hidden = {"user_google_credentials_json", "user_id"}
                display_args = {k: v for k, v in args.items() if k not in _hidden}
                action_desc = (
                    f"Outil: {tool_name} | Arguments: "
                    f"{json.dumps(display_args, ensure_ascii=False)}"
                )

                # ── Vault: resolve vault://label references ────────────────
                vault_refs_found = any(
                    isinstance(v, str) and v.startswith("vault://")
                    for v in args.values()
                )
                if vault_refs_found:
                    from app.services.vault_service import get_vault_service
                    vault = get_vault_service()
                    if vault.is_locked(user_id):
                        results.append(_tool_result(
                            "Vault verrouille — deverrouillez votre coffre-fort dans "
                            "Parametres > Vault pour utiliser ce secret.",
                            tc_id,
                        ))
                        continue
                    try:
                        args, _resolved = await vault.resolve_vault_refs(user_id, args)
                        if _resolved:
                            logger.info(
                                "Resolved vault refs %s for tool %s", _resolved, tool_name
                            )
                    except KeyError as exc:
                        results.append(_tool_result(
                            f"Secret introuvable dans le Vault : {exc}", tc_id
                        ))
                        continue

                # ── HITL check ─────────────────────────────────────────────
                needs_hitl = (
                    tool_name in ALWAYS_CRITICAL_TOOLS
                ) or sf.is_critical(action_desc)
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
                        results.append(_tool_result(
                            "Action interdite definitvement et regle de securite enregistree.",
                            tc_id,
                        ))
                        continue
                    elif decision != "allow":
                        results.append(_tool_result(
                            "Action refusee par l'utilisateur pour cette occurrence.", tc_id
                        ))
                        continue

                # ── Execute ────────────────────────────────────────────────
                tool = tool_map.get(tool_name)
                if tool:
                    try:
                        result = await tool.ainvoke(args)
                        results.append(_tool_result(str(result), tc_id))
                    except Exception as exc:
                        results.append(_tool_result(f"Erreur d'execution: {exc}", tc_id))
                else:
                    results.append(_tool_result(
                        f"Outil '{tool_name}' non disponible pour cet agent.", tc_id
                    ))

            return {"messages": results}

        tools_node.__name__ = f"{cfg.name}_tools_node"
        return tools_node

    # ── Conditional edge ──────────────────────────────────────────────────────

    def should_continue(state: SubAgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "end"

    # ── Assemble graph ────────────────────────────────────────────────────────

    graph = StateGraph(SubAgentState)

    graph.add_node("agent", make_agent_node(config))
    graph.add_node("tools", make_tools_node(config))

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "agent")

    return graph.compile()
