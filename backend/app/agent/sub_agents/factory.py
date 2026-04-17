# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/sub_agents/factory.py
# @brief      Factory module
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


# Canonical tool sets — imported from the single source of truth.
from app.agent.tool_sets import GOOGLE_TOOLS as _GOOGLE_TOOLS  # noqa: E402
from app.agent.tool_sets import USER_ID_TOOLS as _USER_ID_TOOLS  # noqa: E402


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
            import time as _t
            _t_start = _t.monotonic()
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

            # ── Dynamic tool sub-filtering ────────────────────────────────────
            # Even within a sub-agent, binding 70+ tools (workspace) makes the
            # prompt explode (~15-20k tokens of schemas) and slows inference to
            # 60+ seconds. We further filter based on keywords in the user query
            # so the LLM only sees the tools it actually needs.
            import re as _re_filter
            _last_user = ""
            for _m in reversed(messages):
                if hasattr(_m, "content") and getattr(_m, "type", None) == "human":
                    _last_user = (_m.content or "").lower()
                    break
            # Keyword → tool prefix mapping (only used when sub-agent has many tools)
            if len(agent_tools) > 20:
                _kw_filters: list[tuple[_re_filter.Pattern, tuple[str, ...]]] = [
                    (_re_filter.compile(r"\b(mails?|emails?|courriels?|inbox|gmail|courrier|messagerie|boîte (mail|courrier))\b"),
                     ("gmail_",)),
                    (_re_filter.compile(r"\b(calendar|calendrier|agenda|événements?|réunions?|meetings?|rendez.?vous)\b"),
                     ("calendar_",)),
                    (_re_filter.compile(r"\b(drive|fichiers?(?!.*local)|dossiers?(?!.*local))\b"),
                     ("drive_",)),
                    (_re_filter.compile(r"\b(docs?|documents?|google doc|gdoc)\b"),
                     ("docs_",)),
                    (_re_filter.compile(r"\b(sheets?|tableurs?|spreadsheets?|excel)\b"),
                     ("sheets_",)),
                    (_re_filter.compile(r"\b(tâches?|taches?|to.?do|todo)\b"),
                     ("tasks_",)),
                    (_re_filter.compile(r"\b(contacts?|annuaires?|carnet d'adresse)\b"),
                     ("contacts_",)),
                    (_re_filter.compile(r"\b(rappels?|cron|tâche planifiée|planifie|programme|hebdo|quotidien|chaque|tous les)\b"),
                     ("scheduler_",)),
                    (_re_filter.compile(r"\b(ssh|serveurs?|servers?)\b"),
                     ("ssh_",)),
                    (_re_filter.compile(r"\b(watchdog|surveille|veilles?|monitoring)\b"),
                     ("watchdog_",)),
                    (_re_filter.compile(r"\b(briefings?|matin|résumé|debrief)\b"),
                     ("briefing_",)),
                ]
                _matched_prefixes: set[str] = set()
                for _pattern, _prefixes in _kw_filters:
                    if _pattern.search(_last_user):
                        _matched_prefixes.update(_prefixes)
                # Always keep memory/preference tools so the agent can save context
                _ALWAYS_KEEP = ("save_user_preference", "save_constraint", "knowledge_search",
                                "knowledge_list", "smart_knowledge_query")
                if _matched_prefixes:
                    _filtered = [
                        t for t in agent_tools
                        if any(t.name.startswith(p) for p in _matched_prefixes)
                        or t.name in _ALWAYS_KEEP
                    ]
                    if _filtered:  # safety: don't end up with zero tools
                        logger.warning("⏱ TIMING[%s.subfilter] %d → %d tools (kw=%s)",
                                       cfg.name, len(agent_tools), len(_filtered),
                                       sorted(_matched_prefixes))
                        agent_tools = _filtered

            # Complexity routing: classify last user message and select LLM accordingly.
            # If the sub-agent has a fixed provider, use it; otherwise route by complexity.
            # workspace and infra do multi-step tool sequences. They used to be
            # forced to COMPLEX tier to work around Mistral's tool-calling quirks
            # (langchain_mistralai produces AIMessage content=None with tool_calls,
            # which Mistral rejects). That constraint doesn't apply to Ollama/Qwen3/
            # Gemma/Claude — so we fall back to MEDIUM tier minimum for these agents,
            # which is the best trade-off between speed and reliability for tool calls.
            _TOOL_HEAVY_AGENTS = {"workspace", "infra"}
            if cfg.llm_provider is not None:
                llm = get_llm_for_agent(cfg)
            elif cfg.name in _TOOL_HEAVY_AGENTS:
                # Never route these to SIMPLE (small models struggle with multi-turn tools).
                # MEDIUM is fast enough (qwen3:30b-a3b is a MoE → 3B active params).
                from app.services.llm_provider import ComplexityTier
                tier = classify_complexity(user_query)
                if tier == ComplexityTier.SIMPLE:
                    tier = ComplexityTier.MEDIUM
                llm = get_llm_for_tier(tier)
                logger.debug("Sub-agent '%s': tool-heavy, tier=%s", cfg.name, tier.value)
            else:
                tier = classify_complexity(user_query)
                llm = get_llm_for_tier(tier)
                logger.debug(
                    "Sub-agent '%s': complexity=%s, tier=%s",
                    cfg.name, tier.value, tier.value,
                )

            # Tool calling strategy.
            # Historical bug: forcing tool_choice="any" on the first user turn made
            # Claude actually emit tool_calls (instead of just announcing "I'll do X").
            # But this also forced llama3.2 / smaller models to invent a tool call for
            # trivial queries like "Bonjour" — triggering HITL on chitchat.
            # New rule: only force tool_choice="any" when the user message contains an
            # action keyword that clearly needs a tool (envoie/crée/liste/cherche/…).
            # Otherwise, "auto" — let the LLM choose to answer with text or a tool call.
            import re as _re_local
            from langchain_core.messages import HumanMessage as _HM
            _last = messages[-1] if messages else None
            _last_content = _last.content if (_last is not None and isinstance(_last, _HM)) else ""
            _action_kw = _re_local.compile(
                r"\b(envoie|envoyer|crée|créer|créé|liste|cherche|trouve|génère|exécute|"
                r"lance|planifie|programme|note|enregistre|sauvegarde|supprime|delete|"
                r"mail|email|calendrier|drive|sheet|doc|tâche|rappel|"
                r"ajoute|update|modifie|mets à jour|déplace|partage|"
                r"capture|screenshot|météo|news|traduis|"
                r"ssh|exécute|monitore|surveille)\b",
                _re_local.IGNORECASE,
            )
            _force_tools = (
                isinstance(_last, _HM)
                and bool(agent_tools)
                and bool(_action_kw.search(_last_content or ""))
            )
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

            from app.services.qwen_no_think import inject_no_think, strip_think_block
            _invoke_msgs = inject_no_think(
                [{"role": "system", "content": system}]
                + _sanitize_messages_for_mistral(messages)
            )
            _model_name = getattr(llm, 'model', None) or getattr(llm, 'model_name', '?')
            _prep_time = _t.monotonic() - _t_start
            logger.warning("⏱ TIMING[%s.prep] %.2fs — model=%s, tools=%d, msgs=%d", cfg.name, _prep_time, _model_name, len(agent_tools), len(messages))
            _infer_start = _t.monotonic()
            try:
                response = await llm_with_tools.ainvoke(_invoke_msgs)
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)
                logger.warning("⏱ TIMING[%s.infer] %.2fs — tool_calls=%d", cfg.name, _t.monotonic() - _infer_start, len(getattr(response, 'tool_calls', []) or []))
            except Exception as _primary_exc:
                # Recover from quota/rate-limit/auth errors by trying fallbacks
                from app.services.llm_provider import get_fallback_llms
                _exc_str = str(_primary_exc).lower()
                _recoverable = any(k in _exc_str for k in (
                    "429", "rate", "quota", "insuffi", "401", "403", "404",
                    "not_found", "not found", "overloaded", "503", "unavailable",
                    "deprecated", "no longer available",
                    "invalid_argument", "bad request", "400",
                ))
                if not _recoverable:
                    raise
                logger.warning(
                    "Sub-agent '%s' primary LLM failed (%s) — trying fallbacks",
                    cfg.name, _primary_exc,
                )
                response = None
                for _fb_label, _fb_llm in get_fallback_llms():
                    try:
                        _fb_with_tools = _fb_llm.bind_tools(agent_tools)
                        response = await _fb_with_tools.ainvoke(_invoke_msgs)
                        logger.info(
                            "Sub-agent '%s' fallback succeeded with %s",
                            cfg.name, _fb_label,
                        )
                        break
                    except Exception as _fb_exc:
                        logger.warning(
                            "Sub-agent '%s' fallback %s failed: %s",
                            cfg.name, _fb_label, _fb_exc,
                        )
                if response is None:
                    raise _primary_exc

            # Fire-and-forget: extract facts from this exchange for user memory
            if user_id:
                import asyncio as _asyncio
                from app.services.memory_service import extract_and_store_facts

                async def _safe_memory_extract(_uid, _msgs):
                    try:
                        await extract_and_store_facts(_uid, "", _msgs)
                    except Exception as _exc:
                        logger.debug("Memory extraction failed: %s", _exc)

                _asyncio.create_task(_safe_memory_extract(user_id, messages + [response]))

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

                # Inject hidden arguments — credentials fetched from server-side
                # store, never from graph state (SEC-1).
                if tool_name in _GOOGLE_TOOLS:
                    from app.services.credential_store import get_credential_store
                    _uid = state.get("user_id") or ""
                    args["user_google_credentials_json"] = (
                        get_credential_store().get(_uid) or ""
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
