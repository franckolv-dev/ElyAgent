# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/sub_agents/factory.py
# @brief      Factory module
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
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
from app.services.llm_deadline import ainvoke_with_deadline
from app.services.routing_trace import note as routing_note

if TYPE_CHECKING:
    from app.agent.sub_agents.config import SubAgentConfig

logger = logging.getLogger(__name__)

# Strong refs to fire-and-forget background tasks (memory extraction,
# fallback inference, etc.). Without this set, asyncio's GC may cancel
# the task mid-execution because its only reference is the local one
# created via `asyncio.create_task(...)`. Tasks self-remove via
# `add_done_callback(_bg_tasks.discard)`.
_bg_tasks: set = set()


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

def _tool_result(content: str, tool_call_id: str, sf=None) -> dict:
    """Message outil pour l'historique du spécialiste.

    Si un filtre PII partagé est fourni (C0, audit 16/07 P0), le contenu est
    RÉ-ANONYMISÉ — même contrat que le nœud central (tool_node.py) : la PII
    récupérée par l'outil (corps de mail, contact, événement, document…) ne
    repart jamais en clair vers le LLM spécialiste, cloud sur tiers B/C.
    ``ner_detection=False`` : contenu machine, regex + vault seulement.
    """
    if sf is not None:
        try:
            content = sf.anonymize(content, ner_detection=False)
        except Exception:
            logger.warning(
                "PII: ré-anonymisation d'un résultat d'outil spécialiste "
                "échouée — résultat transmis masqué par prudence", exc_info=True,
            )
            content = "[résultat retenu : échec de l'anonymisation PII]"
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


def _deanonymize_args(sf, args: dict) -> dict:
    """Restaure récursivement les placeholders PII ([EMAIL_0]…) dans les
    arguments d'outil — même contrat que le nœud central, sinon Gmail/
    Calendar/Drive reçoivent le placeholder littéral et échouent."""
    def _walk(v):
        if isinstance(v, str):
            return sf.deanonymize(v)
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v
    return {k: _walk(v) for k, v in args.items()}


# Canonical tool sets — imported from the single source of truth.
from app.agent.tool_sets import GOOGLE_TOOLS as _GOOGLE_TOOLS  # noqa: E402
from app.agent.tool_sets import USER_ID_TOOLS as _USER_ID_TOOLS  # noqa: E402


def _last_human_query(messages) -> str:
    """Dernier message UTILISATEUR de l'historique, aplati en texte plat.

    Après un appel d'outil, ``messages[-1]`` est un ToolMessage : classer la
    complexité (ou keyer le cache mémoire) sur le RÉSULTAT d'outil escaladait
    la synthèse vers le tier C à chaque tour outillé, quel que soit le routage
    tier B choisi (bug prod 18/07/2026, canaux muets). Même règle de remontée
    que le bloc ``tool_choice`` plus bas dans ce fichier.
    """
    from langchain_core.messages import HumanMessage

    from app.agent.helpers.message_content import content_to_text

    for _m in reversed(messages or []):
        if isinstance(_m, HumanMessage):
            return content_to_text(_m.content)
    return content_to_text(messages[-1].content) if messages else ""


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
            user_query = _last_human_query(messages)

            registry = get_skill_registry()
            memory = get_memory_manager()

            # Filter tools to this sub-agent's declared subset.
            # PERF: tri alphabétique par nom → ordre déterministe entre appels,
            # nécessaire pour que le prompt cache LM Studio puisse matcher les
            # tool schemas d'un turn à l'autre. Sans ce tri, l'ordre dépend de
            # l'enregistrement des skills (peut varier sur restart) et casse
            # le cache même quand les memories sont stables.
            _allowed_tool_names = cfg.resolve_tool_names()
            agent_tools = sorted(
                [t for t in registry.all_tools if t.name in _allowed_tool_names],
                key=lambda t: t.name,
            )

            # ── Dynamic tool sub-filtering (FIX 2026-05-06 audit H-5) ─────────
            # Délégué au module partagé `app.agent.tool_filter` pour avoir
            # une seule source de vérité avec le general agent_node.
            _last_user = ""
            for _m in reversed(messages):
                if hasattr(_m, "content") and getattr(_m, "type", None) == "human":
                    _raw = _m.content or ""
                    if isinstance(_raw, list):
                        _raw = " ".join(
                            (b.get("text", "") if isinstance(b, dict) else str(b))
                            for b in _raw
                        )
                    _last_user = str(_raw)
                    break
            from app.agent.tool_filter import filter_tools_by_query
            agent_tools = filter_tools_by_query(
                agent_tools,
                _last_user,
                threshold=20,
                debug_label=f"sub.{cfg.name}",
            )

            # Complexity routing: classify last user message and select LLM accordingly.
            # If the sub-agent has a fixed provider, use it; otherwise route by complexity.
            # workspace and infra do multi-step tool sequences. They used to be
            # forced to COMPLEX tier to work around Mistral's tool-calling quirks
            # (langchain_mistralai produces AIMessage content=None with tool_calls,
            # which Mistral rejects). That constraint doesn't apply to Ollama/Qwen3/
            # Gemma/Claude — so we fall back to MEDIUM tier minimum for these agents,
            # which is the best trade-off between speed and reliability for tool calls.
            #
            # `diag` is added because self-introspection questions ("What LLM are
            # you using?") MUST trigger a tool call before answering — picking a
            # SIMPLE-tier model that struggles with function calling defeats the
            # whole point and lets the LLM hallucinate model names from training.
            # MEDIUM tier ensures a reliable tool-caller (typically Qwen 3.6 Plus,
            # Claude Haiku, or whatever the user picked in Settings → Routage).
            _TOOL_HEAVY_AGENTS = {"workspace", "infra", "diag"}
            tier = None  # C3d-2 : borne l'échéance murale (None → MEDIUM)
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
                user_language = state.get("_mem_user_language", "fr") or "fr"
                logger.debug("[%s] memory cache HIT for turn (query=%.30s...)", cfg.name, user_query)
                _cache_updates = {}
            else:
                # Miss — fetch en parallèle puis stocke pour les tool calls suivants
                from app.services.memory_service import get_user_context as _get_user_ctx

                async def _fetch_user_language(uid: str) -> str:
                    """Resolve the calling user's preferred language.

                    Returns "fr" by default if uid is empty, the user no
                    longer exists, or the DB query fails — Éli was designed
                    in French so it's the safest fallback. Logs at INFO only.
                    """
                    if not uid:
                        return "fr"
                    try:
                        from app.models.user import User as _U
                        from app.database import async_session as _async_session
                        from sqlalchemy import select as _select
                        async with _async_session() as _db:
                            _row = await _db.execute(
                                _select(_U.language).where(_U.id == uid)
                            )
                            return (_row.scalar_one_or_none() or "fr")
                    except Exception as exc:
                        # Log so we don't repeat the silent NameError bug of
                        # April 2026 — but at INFO level so it doesn't spam.
                        logger.info("language fetch failed for %s: %s — fallback fr", uid, exc)
                        return "fr"

                _uc_task = _get_user_ctx(user_id) if user_id else None
                constraints, memories, past_interactions, user_ctx, user_language = await asyncio.gather(
                    memory.get_relevant_constraints(user_query, user_id),
                    memory.get_relevant_memories(user_query, user_id),
                    memory.get_relevant_interactions(user_query, user_id, limit=3),
                    _uc_task if _uc_task is not None else asyncio.sleep(0, result=""),
                    _fetch_user_language(user_id),
                )
                logger.debug("[%s] memory cache MISS — fetched for new turn (lang=%s)", cfg.name, user_language)
                _cache_updates = {
                    "_mem_constraints": constraints or [],
                    "_mem_memories": memories or [],
                    "_mem_interactions": past_interactions or [],
                    "_mem_user_ctx": user_ctx or "",
                    "_mem_user_language": user_language,
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

            # Per-user language directive — kept SHORT (~10 tokens × 2) so it
            # doesn't bloat the prompt for small local LLMs (xLAM 8B starts
            # hallucinating beyond ~3000 tokens of context). Sandwich head+tail
            # is enough to anchor reply language without further reinforcement.
            if user_language == "en":
                _lang_directive = "REPLY LANGUAGE = English. Translate any tool output.\n\n"
            else:
                _lang_directive = "LANGUE DE RÉPONSE = Français. Traduis si besoin.\n\n"

            # Quiet trace — keep one line per turn at INFO level so future
            # debugging is easy if the language flow regresses again.
            logger.info(
                "[%s] lang=%s user=%s",
                cfg.name,
                user_language,
                (user_id[:8] + "…") if user_id else "(none)",
            )

            # Short reminder at end (recency anchor) — same idea, kept tiny.
            if user_language == "en":
                _lang_reminder = "\n\n[reply in English]"
            else:
                _lang_reminder = "\n\n[réponds en français]"

            if _use_compact:
                from app.agent.compact_prompt import build_compact_system_prompt
                system = build_compact_system_prompt(
                    agent_name=cfg.name,
                    date_str=date_str,
                    user_ctx=user_ctx or "",
                    memories=memories,
                    constraints=constraints,
                )
                # Sandwich: directive at start (primacy) + reminder at end (recency)
                system = _lang_directive + system + _lang_reminder
                logger.info("[%s] compact prompt mode active (%d chars, lang=%s)", cfg.name, len(system), user_language)
            else:
                # FULL mode — sandwich directive around cfg.system_prompt.
                # Adding to the end means LM Studio prefix cache invalidates
                # only the trailing reminder, not the bulk of cfg.system_prompt.
                system = _lang_directive + cfg.system_prompt + _lang_reminder

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

                # Personal vocabulary (onboarding) — added BEFORE the
                # date because it's stable per-user (cache-friendly).
                # Empty string if user hasn't done onboarding yet.
                try:
                    from app.services.onboarding import get_vocabulary_for_prompt
                    _vocab = await get_vocabulary_for_prompt(user_id)
                    if _vocab:
                        system += f"\n\n{_vocab}\n"
                except Exception as _exc:
                    logger.debug("Vocabulary injection failed: %s", _exc)

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
            # C3d-4 — modèle/tier résolus PAR CYCLE (leçon #210 : la sélection
            # peut changer en plein tour — elle doit être visible à chaque fois).
            routing_note(
                state.get("conversation_id", ""), "subagent",
                user_id=state.get("user_id", ""),
                decision=str(_model_name),
                agent=cfg.name,
                tier=getattr(tier, "value", None) or "agent-config",
                msgs=len(messages),
            )
            _infer_start = _t.monotonic()
            try:
                response = await ainvoke_with_deadline(
                    llm_with_tools, _invoke_msgs, tier=tier,
                    surface=f"sub-agent:{cfg.name}")
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)

                # FIX 2026-05-06 (Option A): recover tool calls emitted as
                # TEXT (e.g. Kimi K2 outputs `<tool_call>...</tool_call>`,
                # Qwen 3.6 Flash outputs raw JSON) and fix hallucinated
                # names (e.g. `send_email` → `gmail_send_email`) before
                # the graph sees `tool_calls=[]` and stalls.
                from app.agent.tool_call_recovery import recover_tool_calls_into_response
                from app.skills.registry import get_skill_registry as _gsr
                _registry = _gsr()
                _recovered_n = recover_tool_calls_into_response(
                    response,
                    real_tool_names={t.name for t in _registry.all_tools},
                )
                if _recovered_n:
                    logger.warning(
                        "[recovery:%s] recovered %d tool_call(s) from text content",
                        cfg.name, _recovered_n,
                    )

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
                                response = await ainvoke_with_deadline(
                                    _fb_bound, _fb_msgs, tier=tier,
                                    surface=f"sub-agent:{cfg.name}:fb-toolchoice")
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
                # C3d-3 : classification UNIFIÉE (même mapping que la rotation
                # chantier4 du nœud général). L'ancienne liste inline divergeait
                # — pas de timeout/codex/context-length : un dépassement
                # d'échéance murale (C3d-2) tuait le sous-agent au lieu de
                # tourner sur ses fallbacks. None = vrai bug → propagé.
                from app.services.fallback_manager import classify_exception
                from app.services.llm_provider import get_fallback_llms
                _fail_reason = classify_exception(_primary_exc)
                if _fail_reason is None:
                    raise
                logger.warning(
                    "Sub-agent '%s' primary LLM failed (%s: %s) — trying fallbacks",
                    cfg.name, _fail_reason.value, _primary_exc,
                )
                # C3d-4 — rotation locale du sous-agent tracée.
                routing_note(
                    state.get("conversation_id", ""), "subagent_fallback",
                    user_id=state.get("user_id", ""),
                    decision=_fail_reason.value,
                    agent=cfg.name,
                )
                response = None
                # Fallback LLMs are non-Qwen — strip /no_think.
                _fb_msgs2 = strip_no_think(_invoke_msgs)
                for _fb_label, _fb_llm in get_fallback_llms():
                    try:
                        _fb_with_tools = _fb_llm.bind_tools(agent_tools)
                        response = await ainvoke_with_deadline(
                            _fb_with_tools, _fb_msgs2, tier=tier,
                            surface=f"sub-agent:{cfg.name}:fb-exc")
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

                # Hold a reference to the background task — Python's GC may
                # cancel asyncio tasks that have no strong reference, per
                # the docs (see asyncio.create_task warning). _bg_tasks is
                # a module-level WeakSet that lets the task auto-remove
                # itself when done while keeping a strong ref while alive.
                _t = _asyncio.create_task(
                    _safe_memory_extract(user_id, messages + [response])
                )
                _bg_tasks.add(_t)
                _t.add_done_callback(_bg_tasks.discard)

            # Persist memory cache updates (if any) so subsequent tool calls
            # in the same turn reuse the blocks instead of re-fetching.
            _ret = {"messages": [response]}
            if _cache_updates:
                _ret.update(_cache_updates)
            # Analytics : expose the actual provider/model used so the outer
            # supervisor graph (and ultimately chat.py:log_usage) records
            # something meaningful instead of "unknown/tier-medium".
            try:
                from app.services.llm_provider import describe_llm
                _p, _m = describe_llm(llm)
                _ret["model_used"] = f"llm:{_p}/{_m}"
            except Exception:
                pass
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

            # Pull the last user message (HumanMessage) for HITL context.
            # Used to humanize HITL prompts and detect arg/intent mismatches
            # (May 2026 fix #21 — Temu incident).
            from langchain_core.messages import HumanMessage as _HumanMsg
            _last_user_request = ""
            for _m in reversed(state["messages"]):
                if isinstance(_m, _HumanMsg):
                    _c = _m.content
                    if isinstance(_c, str):
                        _last_user_request = _c
                    elif isinstance(_c, list):
                        # Multi-block content (text + image) → join text parts
                        _last_user_request = " ".join(
                            (b.get("text", "") if isinstance(b, dict) else str(b))
                            for b in _c
                        )
                    break

            # Only expose tools declared for this sub-agent
            _allowed_tool_names = cfg.resolve_tool_names()
            tool_map = {
                t.name: t
                for t in get_skill_registry().all_tools
                if t.name in _allowed_tool_names
            }
            sf = SecurityFilter()
            hitl = get_hitl_manager()
            memory = get_memory_manager()

            # ── Délégation à la passerelle unique (C3b) ────────────────────
            # Le pipeline complet (PII, creds Google multi-comptes, vault,
            # gates HITL — manifeste, canary io, ACL MCP/instance, task-scoped,
            # self-mail, préférences —, empreinte fail-closed, idempotence,
            # journal réversible, exécution, ré-anonymisation, événements,
            # signaux d'apprentissage) vit dans services/tool_gateway.py.
            # Les spécialistes y GAGNENT aussi les décisions « Toujours
            # autoriser » / « Autoriser pour cette tâche », que l'ancienne
            # boucle locale refusait à tort (traitées comme un deny).
            from app.services.conversation_filters import get_filter as _get_conv_filter
            from app.services.tool_gateway import GatewayContext, execute_tool_call
            _conv_id = state.get("conversation_id") or ""
            _pii_sf = None
            if _conv_id:
                try:
                    _pii_sf = _get_conv_filter(_conv_id)
                except Exception:
                    logger.warning(
                        "PII: filtre de conversation indisponible (conv=%s)",
                        _conv_id, exc_info=True,
                    )
            _gw_ctx = GatewayContext(
                user_id=user_id,
                conversation_id=_conv_id,
                pii_filter=_pii_sf,
                criticality_filter=sf,
                hitl=hitl,
                memory=memory,
                user_request=_last_user_request,
                label=cfg.name,
            )
            for tool_call in last_message.tool_calls:
                results.append(await execute_tool_call(_gw_ctx, tool_call, tool_map))

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
