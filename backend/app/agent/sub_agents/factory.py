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

            # Filter tools to this sub-agent's declared subset.
            # PERF: tri alphabétique par nom → ordre déterministe entre appels,
            # nécessaire pour que le prompt cache LM Studio puisse matcher les
            # tool schemas d'un turn à l'autre. Sans ce tri, l'ordre dépend de
            # l'enregistrement des skills (peut varier sur restart) et casse
            # le cache même quand les memories sont stables.
            agent_tools = sorted(
                [t for t in registry.all_tools if t.name in cfg.tool_names],
                key=lambda t: t.name,
            )

            # ── Dynamic tool sub-filtering ────────────────────────────────────
            # Even within a sub-agent, binding 70+ tools (workspace) makes the
            # prompt explode (~15-20k tokens of schemas) and slows inference to
            # 60+ seconds. We further filter based on keywords in the user query
            # so the LLM only sees the tools it actually needs.
            import re as _re_filter
            _last_user = ""
            for _m in reversed(messages):
                if hasattr(_m, "content") and getattr(_m, "type", None) == "human":
                    # HumanMessage.content peut être str OU list[dict] (multi-bloc
                    # texte+image). On extrait le texte dans les 2 cas sinon
                    # .lower() / .search() crashent avec TypeError.
                    _raw = _m.content or ""
                    if isinstance(_raw, list):
                        _raw = " ".join(
                            (b.get("text", "") if isinstance(b, dict) else str(b))
                            for b in _raw
                        )
                    _last_user = str(_raw).lower()
                    break
            # Keyword → tool prefix mapping (only used when sub-agent has many tools)
            if len(agent_tools) > 20:
                _kw_filters: list[tuple[_re_filter.Pattern, tuple[str, ...]]] = [
                    # Gmail implies possible need for contacts_search to resolve
                    # "prepare a mail for <name>" → need to look up <name>'s email
                    # "mai" = common STT transcription glitch of "mail"; we also
                    # catch "courriel[s]" and "message" (when combined with "prépare"/"envoyer").
                    (_re_filter.compile(r"\b(mails?|mai|emails?|e.?mail|courriels?|inbox|gmail|courrier|messagerie|boîte (mail|courrier)|brouillons?|drafts?)\b"),
                     ("gmail_", "contacts_")),
                    # "rappel dans l'agenda/planning/calendrier" → calendar (événement ponctuel)
                    # "rappel + tous les jours/chaque matin/hebdo" → scheduler (cron récurrent)
                    # "rappel" seul → les deux (laisse le LLM décider)
                    (_re_filter.compile(r"\b(calendar|calendrier|agenda|planning|événements?|réunions?|meetings?|rendez.?vous)\b"),
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
                    # Recurring reminder → scheduler (cron)
                    (_re_filter.compile(r"\b(cron|tâche planifiée|planifie|programme|hebdo|quotidien|récurrent|toutes les|tous les|chaque (jour|matin|soir|semaine|mois))\b"),
                     ("scheduler_",)),
                    # "rappel" sans contexte récurrent = plutôt calendar (événement ponctuel)
                    # On inclut les deux pour laisser le LLM choisir
                    (_re_filter.compile(r"\brappels?\b"),
                     ("calendar_", "scheduler_")),
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
            # IMPORTANT: Walk backwards to find the last *actual* user message.
            # After a tool call the final message is a ToolMessage; keying
            # _force_tools off messages[-1] would lose the original user
            # intent and drop back to "auto" mode, in which case Claude
            # narrates « le système demande confirmation » instead of
            # actually calling the destructive follow-up tool.
            # We also count tool messages since that last user turn — past
            # ~2 tool calls we release the `tool_choice="any"` constraint so
            # Claude can close the turn with a "done" text reply instead of
            # looping on the same tool (e.g. redeleting an already-deleted
            # file because the constraint forbids text output).
            from langchain_core.messages import ToolMessage as _TM
            _last_user_msg = None
            _tool_calls_since_user = 0
            for _m in reversed(messages):
                if isinstance(_m, _HM):
                    _last_user_msg = _m
                    break
                if isinstance(_m, _TM):
                    _tool_calls_since_user += 1
            # Extract text from HumanMessage.content (str or list[dict] for
            # multi-bloc text+image). Without this, _action_kw.search(list)
            # raises TypeError on multimodal inputs.
            _last_content_raw = _last_user_msg.content if _last_user_msg is not None else ""
            if isinstance(_last_content_raw, list):
                _last_content = " ".join(
                    (b.get("text", "") if isinstance(b, dict) else str(b))
                    for b in _last_content_raw
                )
            else:
                _last_content = str(_last_content_raw) if _last_content_raw else ""
            _action_kw = _re_local.compile(
                r"\b(envoie|envoyer|crée|créer|créé|liste[rz]?|listes?|"
                r"prépare[rz]?|prépares?|compose[rz]?|composes?|rédige[rz]?|rédiges?|"
                r"brouillons?|drafts?|répondre?|réponds?|réponse|"
                r"cherche|trouve|génère|exécute|"
                r"lance|planifie|programme|notes?|enregistre|sauvegarde|supprime|delete|"
                r"affiche[rz]?|montre[rz]?|quels?(?: sont)?|quelles?(?: sont)?|"
                r"mails?|emails?|calendrier|drive|sheets?|docs?|tâches?|rappels?|"
                r"ajoute|update|modifie|mets à jour|déplace|partage|"
                r"capture|screenshot|météo|news|traduis|"
                r"ssh|monitore|surveille)\b",
                _re_local.IGNORECASE,
            )
            _force_tools = (
                _last_user_msg is not None
                and bool(agent_tools)
                and bool(_action_kw.search(_last_content or ""))
                # Release the constraint once the agent has already run 2+
                # tools in this turn — otherwise it can't close the turn
                # with a final text response and loops on the same tool.
                and _tool_calls_since_user < 2
            )
            if _force_tools:
                # ── tool_choice mapping per provider ──────────────────────
                # Anthropic / Mistral / Gemini → "any"
                # OpenAI / LM Studio (OpenAI-compatible) → "required"
                # Sending "any" to LM Studio returns HTTP 400
                # ("Invalid tool_choice value: 'any'. Supported values:
                #  none, auto, required") which LangChain then silently
                # degrades to text output → tool_calls=0 on every turn.
                # Detect ChatOpenAI (LM Studio, DeepSeek, OpenRouter) and
                # switch to "required".
                _cls = type(llm).__name__
                _is_openai_compat = _cls == "ChatOpenAI"
                _tool_choice_forced = "required" if _is_openai_compat else "any"
                try:
                    llm_with_tools = llm.bind_tools(agent_tools, tool_choice=_tool_choice_forced)
                except Exception:
                    llm_with_tools = llm.bind_tools(agent_tools)
            else:
                llm_with_tools = llm.bind_tools(agent_tools)

            # ── Memory context — cached per user turn ─────────────────────
            # PERF (2026-04-23) : sans ce cache, on refetchait memories +
            # constraints + interactions + user_ctx à CHAQUE itération de
            # l'agent (y compris entre tool calls d'un même tour). Or ces
            # valeurs changent à chaque fetch (Qdrant ordering, timestamps),
            # ce qui invalide le prompt cache de LM Studio → Gemma MLX 26B
            # retraite 15 000 tokens (~45s) à chaque tour de boucle. Avec
            # le cache, on fetch une fois au premier appel du turn
            # utilisateur, et on réutilise pour tous les tool calls en
            # cascade → cache LM Studio peut enfin hit.
            #
            # Invalidation : quand `user_query` change (= nouveau message
            # utilisateur), les memories sont re-fetched. On garde donc la
            # fraîcheur pour chaque nouveau prompt de l'utilisateur.
            _cached_query = state.get("_mem_fetched_for_query")
            if _cached_query == user_query:
                # Hit — réutilise les blocs du state
                constraints = state.get("_mem_constraints", []) or []
                memories = state.get("_mem_memories", []) or []
                past_interactions = state.get("_mem_interactions", []) or []
                user_ctx = state.get("_mem_user_ctx", "") or ""
                logger.debug("[%s] memory cache HIT for turn (query=%.30s...)", cfg.name, user_query)
                _cache_updates = {}
            else:
                # Miss — fetch en parallèle puis stocke pour les tool calls suivants
                from app.services.memory_service import get_user_context as _get_user_ctx
                _uc_task = _get_user_ctx(user_id) if user_id else None
                constraints, memories, past_interactions, user_ctx = await asyncio.gather(
                    memory.get_relevant_constraints(user_query, user_id),
                    memory.get_relevant_memories(user_query, user_id),
                    memory.get_relevant_interactions(user_query, user_id, limit=3),
                    _uc_task if _uc_task is not None else asyncio.sleep(0, result=""),
                )
                logger.debug("[%s] memory cache MISS — fetched for new turn", cfg.name)
                _cache_updates = {
                    "_mem_constraints": constraints or [],
                    "_mem_memories": memories or [],
                    "_mem_interactions": past_interactions or [],
                    "_mem_user_ctx": user_ctx or "",
                    "_mem_fetched_for_query": user_query,
                }

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

            # ── Build system prompt ────────────────────────────────────────
            # Two modes depending on the target model :
            # 1. COMPACT (local LLMs via LM Studio / llama.cpp) : ~300
            #    tokens total. Small models (7B-14B) follow textual
            #    instructions literally and get confused by ELY's verbose
            #    prompt, preferring to text-respond rather than tool-call.
            # 2. FULL (frontier cloud models) : the historical prompt
            #    with all behavioural rules, identity, memories, etc.
            #    Frontier models navigate this richness well.
            from app.services.qwen_no_think import is_local_openai_llm
            _use_compact = is_local_openai_llm(llm)

            if _use_compact:
                from app.agent.compact_prompt import build_compact_system_prompt
                system = build_compact_system_prompt(
                    agent_name=cfg.name,
                    date_str=date_str,
                    user_ctx=user_ctx or "",
                    memories=memories,
                    constraints=constraints,
                )
                logger.info("[%s] compact prompt mode active (%d chars)", cfg.name, len(system))
            else:
                # FULL mode — unchanged, dynamic tail ordering preserved
                # so LM Studio prefix cache can retain cfg.system_prompt.
                system = cfg.system_prompt

                if user_ctx:
                    system += f"\n\n{user_ctx}\n"

                # PERF: on tronque agressivement les injections mémoire. Les
                # valeurs longues explosent le nombre de tokens sans apport
                # qualitatif significatif pour la décision de tool-calling.
                # Le LLM dispose déjà de l'historique conversationnel complet.
                if constraints:
                    system += "\n\nCONTRAINTES DE SECURITE PERMANENTES :\n"
                    system += "\n".join(f"- {c[:200]}" for c in constraints[:5])
                if memories:
                    system += "\n\nCONTEXTE MEMORISE :\n"
                    system += "\n".join(f"- {m[:150]}" for m in memories[:5])
                if past_interactions:
                    system += "\n\nINTERACTIONS PASSEES :\n"
                    for p in past_interactions[:3]:
                        system += (
                            f"- Q: {p.get('user_message', '')[:80]} "
                            f"-> R: {p.get('assistant_message', '')[:80]}\n"
                        )

                # Date en DERNIER — c'est la partie la plus volatile (change
                # de minute). En la plaçant après le contenu stable, on limite
                # l'invalidation du cache aux ~30 derniers tokens au lieu de
                # tout le prompt.
                system += f"\n\nDate et heure : {date_str} (Europe/Paris)\n"

            from app.services.qwen_no_think import (
                inject_no_think, is_qwen_llm, strip_no_think, strip_think_block,
            )
            _invoke_msgs = (
                [{"role": "system", "content": system}]
                + _sanitize_messages_for_mistral(messages)
            )
            # Only Qwen understands /no_think; non-Qwen models would echo it
            # (e.g. « email de X /no_think » leaked back into the reply).
            if is_qwen_llm(llm):
                _invoke_msgs = inject_no_think(_invoke_msgs)
            _model_name = getattr(llm, 'model', None) or getattr(llm, 'model_name', '?')
            _prep_time = _t.monotonic() - _t_start
            logger.warning("⏱ TIMING[%s.prep] %.2fs — model=%s, tools=%d, msgs=%d", cfg.name, _prep_time, _model_name, len(agent_tools), len(messages))
            _infer_start = _t.monotonic()
            try:
                response = await llm_with_tools.ainvoke(_invoke_msgs)
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)
                _n_tc = len(getattr(response, 'tool_calls', []) or [])
                logger.warning("⏱ TIMING[%s.infer] %.2fs — tool_calls=%d", cfg.name, _t.monotonic() - _infer_start, _n_tc)

                # If we forced tool_choice="any" but the LLM emitted zero tool
                # calls, it means qwen2.5/small models / Gemma MLX ignored the
                # constraint and returned text. Historically we always fell
                # back to a cloud LLM (Claude Haiku / Gemini Flash) which
                # reliably respects tool_choice.
                #
                # PERF/OBSERVABILITY (2026-04-23) : ce fallback est désormais
                # conditionné au flag `fallback_enabled` du tier. Quand l'user
                # a explicitement désactivé le fallback (ex. pour tester une
                # config 100 % locale Gemma), on respecte son choix et on
                # remonte la réponse texte telle quelle. Le log reste très
                # visible pour qu'on repère le problème vite en prod.
                if _force_tools and _n_tc == 0:
                    from app.services.llm_provider import (
                        classify_complexity, get_fallback_llms, get_tier_config,
                    )
                    # Determine tier of current user query to fetch its fallback flag
                    _cur_tier = classify_complexity(user_query).value
                    _tier_cfg = get_tier_config().get(_cur_tier, {})
                    _fallback_allowed = _tier_cfg.get("fallback_enabled", True)

                    logger.warning(
                        "⚠️  [%s.infer] tool_choice=any ignored by %s (0 tool_calls) "
                        "— tier=%s fallback_enabled=%s",
                        cfg.name, _model_name, _cur_tier, _fallback_allowed,
                    )

                    if not _fallback_allowed:
                        logger.warning(
                            "🚫 [%s.infer] fallback disabled by tier config — "
                            "keeping local model's text response (tool_calls=0)",
                            cfg.name,
                        )
                        # Response garde son contenu texte tel quel
                    else:
                        # Fallback LLMs are non-Qwen — strip the /no_think marker
                        # so it doesn't leak into their replies.
                        _fb_msgs = strip_no_think(_invoke_msgs)
                        for _fb_label, _fb_llm in get_fallback_llms():
                            try:
                                _fb_bound = _fb_llm.bind_tools(agent_tools, tool_choice="any")
                            except Exception:
                                _fb_bound = _fb_llm.bind_tools(agent_tools)
                            try:
                                _fb_t = _t.monotonic()
                                response = await _fb_bound.ainvoke(_fb_msgs)
                                _n_tc2 = len(getattr(response, 'tool_calls', []) or [])
                                logger.warning(
                                    "🔁 [%s.fallback] %.2fs — %s, tool_calls=%d",
                                    cfg.name, _t.monotonic() - _fb_t, _fb_label, _n_tc2,
                                )
                                if _n_tc2 > 0:
                                    break
                            except Exception as _fb_exc:
                                logger.warning("Fallback %s also failed: %s", _fb_label, _fb_exc)
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
                # Fallback LLMs are non-Qwen — strip /no_think.
                _fb_msgs2 = strip_no_think(_invoke_msgs)
                for _fb_label, _fb_llm in get_fallback_llms():
                    try:
                        _fb_with_tools = _fb_llm.bind_tools(agent_tools)
                        response = await _fb_with_tools.ainvoke(_fb_msgs2)
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

            # Persist memory cache updates (if any) so subsequent tool calls
            # in the same turn reuse the blocks instead of re-fetching.
            _ret = {"messages": [response]}
            if _cache_updates:
                _ret.update(_cache_updates)
            return _ret

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

                # ── De-anonymize PII placeholders in args ──────────────────
                # The LLM sees [EMAIL_0]/[IBAN_0]/etc. (anonymized by SecurityFilter
                # before prompt). If the LLM uses those placeholders as tool args,
                # we must restore the real values BEFORE calling external APIs,
                # otherwise Gmail/Calendar/etc. receive literal "[EMAIL_0]" and fail.
                _conv_id = state.get("conversation_id")
                if _conv_id:
                    try:
                        from app.routers.chat import _filters as _chat_filters
                        _sf = _chat_filters.get(_conv_id)
                        if _sf is not None:
                            for _k, _v in list(args.items()):
                                if isinstance(_v, str) and "[" in _v and "]" in _v:
                                    args[_k] = _sf.deanonymize(_v)
                    except Exception:
                        pass

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
                    import time as _tt
                    _ts = _tt.monotonic()
                    try:
                        result = await tool.ainvoke(args)
                        # Log args too when result indicates an error — critical for debugging
                        _result_str = str(result)
                        _is_error = "Erreur" in _result_str or "Error" in _result_str or "HttpError" in _result_str
                        if _is_error:
                            # Log args (redacting credentials) to understand what the LLM passed
                            _safe_args = {k: ("<redacted>" if k == "user_google_credentials_json" else v) for k, v in args.items()}
                            logger.warning(
                                "⏱ TIMING[%s.tool:%s] %.2fs — ARGS=%s — ERROR=%.400s",
                                cfg.name, tool_name, _tt.monotonic() - _ts, _safe_args, _result_str,
                            )
                        else:
                            logger.warning(
                                "⏱ TIMING[%s.tool:%s] %.2fs — result=%.120s",
                                cfg.name, tool_name, _tt.monotonic() - _ts, _result_str,
                            )
                        results.append(_tool_result(_result_str, tc_id))
                    except Exception as exc:
                        logger.warning(
                            "⏱ TIMING[%s.tool:%s] %.2fs — ERROR: %s",
                            cfg.name, tool_name, _tt.monotonic() - _ts, exc,
                        )
                        results.append(_tool_result(f"Erreur d'execution: {exc}", tc_id))
                else:
                    logger.warning("⏱ TIMING[%s.tool:%s] UNAVAILABLE for this agent", cfg.name, tool_name)
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
