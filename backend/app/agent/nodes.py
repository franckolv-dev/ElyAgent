# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/nodes.py
# @brief      LangGraph agent node definitions
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import asyncio
import json
import logging
import os
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.state import AgentState
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_llm, get_fallback_llms
from app.services import fallback_manager as _fb
from app.services import system_prompt_cache as _spc
from app.services import frozen_memory as _frozen_mem
from app.services.intent_router import get_intent_router
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)


async def _no_interactions() -> list[dict]:
    """Cheap placeholder for get_relevant_interactions on the first turn."""
    return []


# Moved to app/agent/helpers/message_sanitizer.py (refactor 2026-05-25 Phase 1.2).
from app.agent.helpers.message_sanitizer import (  # noqa: E402,F401
    _sanitize_messages_for_mistral,
)

# ------------------------------------------------------------------ #
# System prompt                                                        #
# ------------------------------------------------------------------ #
# Constants moved to app/agent/prompts.py (refactor 2026-05-25 Phase 1.1).
# Re-exported below so external consumers (learning/ab_testing,
# learning/prompt_version, test_system_prompt_size) keep working.
from app.agent.prompts import _SYSTEM_PROMPT_BASE, _SYSTEM_PROMPT_SLM  # noqa: E402,F401


# Moved to app/agent/helpers/message_sanitizer.py (refactor 2026-05-25 Phase 1.2).
from app.agent.helpers.message_sanitizer import _tool_result  # noqa: E402,F401


# Moved to app/agent/helpers/tool_history.py (refactor 2026-05-25 Phase 1.3).
from app.agent.helpers.tool_history import (  # noqa: E402,F401
    _HEAVY_FIELDS,
    _HEAVY_FIELD_THRESHOLD,
    _sanitize_tool_result_for_history,
)


# Moved to app/agent/helpers/bind_tools.py (refactor 2026-05-25 Phase 1.4).
from app.agent.helpers.bind_tools import (  # noqa: E402,F401
    _BTS_TAG,
    _bind_tools_smart,
    _classify_model_family,
    _extract_model_name,
)


# ------------------------------------------------------------------ #
# Tools that need automatic argument injection                        #
# ------------------------------------------------------------------ #
# Canonical sets live in tool_sets.py — import from there.

from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS  # noqa: E402


# ------------------------------------------------------------------ #
# Lightweight system prompt for SLM (simple tasks, no memory needed) #
# ------------------------------------------------------------------ #
# Moved to app/agent/prompts.py (refactor 2026-05-25 Phase 1.1).
# Already imported at the top of this file alongside _SYSTEM_PROMPT_BASE.


# ------------------------------------------------------------------ #
# Memory block formatter (Hermes Chantier 2 — frozen snapshot)        #
# ------------------------------------------------------------------ #


# Moved to app/agent/helpers/memory_formatting.py (refactor 2026-05-25 Phase 1.5).
from app.agent.helpers.memory_formatting import _format_memory_block  # noqa: E402,F401


# ------------------------------------------------------------------ #
# Agent node                                                           #
# ------------------------------------------------------------------ #

def create_agent_node():
    from app.skills import get_skill_registry
    from app.config import get_settings
    from app.services.llm_provider import get_active_provider, get_active_model

    settings = get_settings()
    registry = get_skill_registry()
    memory = get_memory_manager()
    intent_router = get_intent_router()

    # Pre-build SLM if enabled — cached in closure but re-bound when tools change
    _slm_with_tools = None
    _slm_version = -1
    if settings.slm_enabled:
        try:
            from app.services.llm_provider import get_slm
            _slm_with_tools = get_slm().bind_tools(registry.all_tools)
            _slm_version = registry.tools_version
            logger.info("SLM pre-built: model=%s, threshold=%d", settings.slm_model, settings.slm_complexity_threshold)
        except Exception as exc:
            logger.warning("SLM init failed: %s — all requests will use LLM", exc)

    # Tier-based LLM cache: { tier_value → llm_with_tools }
    # Invalidated on EITHER:
    #   - tool registry version bump (new skill installed/upgraded)
    #   - tier config version bump (user changed routing in Settings → Routage)
    # Without the second check, switching a model in the UI had no runtime
    # effect — the cached client (e.g. Devstral) kept being served on every
    # agent_node call. (Audit C-4, fixed 2026-05-06.)
    _tier_llm_cache: dict = {}
    _tier_cache_version = [-1]   # tracks registry.tools_version
    _tier_cfg_version = [-1]     # tracks llm_provider.get_tier_config_version()

    async def agent_node(state: AgentState) -> dict:
        import time as _t
        _gt_start = _t.monotonic()
        logger.warning("⏱ TIMING[general] starting")
        nonlocal _slm_with_tools, _slm_version
        # _tier_llm_cache / _tier_cache_version are dicts/lists mutated in-place — no nonlocal needed
        messages = state["messages"]
        user_id = state.get("user_id", "")
        # Hermes Chantier 2 / 4 — conversation id needs to be available BEFORE
        # the system prompt is built (cache key) and before the fallback state
        # is created (down in the LLM path). Hoisting it here means both
        # chantiers see the same value. Empty string disables both caches
        # for this turn — acceptable for non-conversation API callers.
        _conv_id_fb = state.get("conversation_id", "") or ""
        # Defensive: LangGraph may pass messages as dicts (serialized form)
        # when a node receives state that was built outside the graph runner.
        _last = messages[-1] if messages else None
        if isinstance(_last, dict):
            user_query = _last.get("content") or ""
            if isinstance(user_query, list):  # multi-block content
                user_query = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in user_query
                )
        else:
            _c = _last.content if _last else ""
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _c
            ) if isinstance(_c, list) else (_c or "")

        # Hot-reload: clear tier cache when tool registry OR tier routing config changes
        from app.services.llm_provider import get_tier_config_version
        current_version = registry.tools_version
        current_cfg_version = get_tier_config_version()
        if (current_version != _tier_cache_version[0]
                or current_cfg_version != _tier_cfg_version[0]):
            _tier_llm_cache.clear()
            _tier_cache_version[0] = current_version
            _tier_cfg_version[0] = current_cfg_version
            logger.info(
                "Tier LLM cache invalidated (tools_v=%d, tier_cfg_v=%d)",
                current_version, current_cfg_version,
            )

        if _slm_with_tools is not None and current_version != _slm_version:
            try:
                from app.services.llm_provider import get_slm
                _slm_with_tools = get_slm().bind_tools(registry.all_tools)
                _slm_version = current_version
            except Exception:
                pass

        # ── Route first — avoids loading memory for SLM requests ──────────
        routing_score = 100
        model_used = "llm:tier-routed"  # updated once tier is selected below
        response = None

        from app.services.intent_router import ModelTier
        use_slm = False
        decision = None
        # Scheduled / automated runs must use the reliable cloud tier — the
        # local SLM is too weak for unattended multi-tool prompts and would
        # also bypass the named-tool binding below.
        if _slm_with_tools is not None and not state.get("automated_task"):
            decision = intent_router.route(user_query, history=messages[:-1])
            routing_score = decision.score
            use_slm = (decision.tier == ModelTier.SLM)

        # Refactor 2026-05-25 Phase 4.2 — date / language / IMPORTANT note
        # builders extracted to app/agent/builders/system_prompt.py.
        from app.agent.builders.system_prompt import (
            LLM_INTROSPECTION_NOTE,
            compute_date_segment,
            extract_email_block_addendum,
            fetch_user_language,
        )
        date_str, _date_segment = compute_date_segment()
        _user_language, _lang_directive, _lang_reminder = await fetch_user_language(user_id)
        logger.info(
            "[general] lang=%s user=%s",
            _user_language,
            (user_id[:8] + "…") if user_id else "(none)",
        )

        if use_slm:
            # ── Lightweight path: minimal prompt, no memory queries ────────
            # Fetching Qdrant memory adds ~150-300ms and is useless for simple tasks.
            # SLM path is short enough that caching is not worthwhile.
            system = _SYSTEM_PROMPT_SLM.format(date_str=date_str)
            _use_compact = False  # ensure variable is defined for downstream branches
        else:
            # ── Full path: complete prompt + memory context ────────────────
            # Decide compact-vs-full once based on the active LLM family.
            # Compact path is used for small local LLMs (LM Studio, llama.cpp
            # on localhost) and stays uncached because it's already short
            # (~300 tokens) — the cache benefit is marginal there.
            from app.services.qwen_no_think import is_local_openai_llm
            from app.agent.compact_prompt import build_compact_system_prompt

            try:
                _llm_for_detect = get_llm()
            except Exception:
                _llm_for_detect = None
            _use_compact = (
                _llm_for_detect is not None
                and is_local_openai_llm(_llm_for_detect)
            )

            # Memory snapshot — cacheable per-conversation via frozen_memory.
            # On the first turn, we run the 5-way Qdrant + SQL gather; on
            # subsequent turns, the snapshot is returned from cache in O(1)
            # without re-querying Qdrant. New facts archived mid-session
            # appear in the snapshot of the NEXT conversation, not this one.
            #
            # Refactor 2026-05-25 Phase 4.1 — the business logic lives in
            # app/agent/builders/memory_snapshot.py as a pure async fn that
            # returns (snapshot_text, compact_pieces). The thin wrapper
            # below only exists to satisfy frozen_memory's `() -> str`
            # builder signature and to propagate compact_pieces via the
            # only remaining `nonlocal` in this path.
            from app.agent.builders.memory_snapshot import (
                build_memory_snapshot,
                refetch_compact_pieces,
            )

            _compact_pieces: dict | None = None

            async def _build_memory_snapshot() -> str:
                nonlocal _compact_pieces
                snapshot, pieces = await build_memory_snapshot(
                    messages=messages,
                    user_id=user_id,
                    user_query=user_query,
                    memory=memory,
                    use_compact=_use_compact,
                )
                if pieces is not None:
                    _compact_pieces = pieces
                return snapshot

            memory_snapshot = await _frozen_mem.get_or_build(
                _conv_id_fb, user_id, _build_memory_snapshot,
            )

            if _use_compact:
                # Local LLMs get a compact prompt — uncached, builds from the
                # snapshot pieces we just gathered.
                if _compact_pieces is None:
                    # Cache hit on frozen_memory means _build_memory_snapshot
                    # didn't run this turn, so _compact_pieces is empty.
                    # Re-fetch the minimal trio synchronously (rare path —
                    # only on cache hit + compact mode together).
                    _compact_pieces = await refetch_compact_pieces(
                        user_id=user_id,
                        user_query=user_query,
                        memory=memory,
                    )
                system = build_compact_system_prompt(
                    agent_name="general",
                    date_str=date_str,
                    user_ctx=_compact_pieces["user_profile"],
                    memories=_compact_pieces["memories"],
                    constraints=_compact_pieces["constraints"],
                )
                logger.info(
                    "[general] compact prompt mode active (%d chars)", len(system),
                )
            else:
                # Full path — Hermes Chantier 2 caching active.
                # Cacheable segment = lang_directive + base + IMPORTANT + snapshot.
                # Concatenated in this order so the provider's prompt cache
                # prefix can match every byte up to the dynamic date.
                # LLM_INTROSPECTION_NOTE imported from builders.system_prompt
                # at the top of agent_node.
                def _build_cacheable_prompt() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + LLM_INTROSPECTION_NOTE
                        + memory_snapshot
                    )

                cacheable_system = _spc.get_or_build(
                    _conv_id_fb, _build_cacheable_prompt,
                )
                # Final assembly: cacheable + dynamic date + lang reminder.
                # Email block + lang reminder are appended further down.
                system = cacheable_system + _date_segment

        # ── Sandwich tail: language reminder ──────────────────────────────
        # Front-load (primacy) was already applied INSIDE the cacheable
        # segment (full path) or via _SYSTEM_PROMPT_SLM/compact (other paths).
        # Tail-load (recency) goes here so the model honours the language
        # request even when the body drifts in the other language.
        if use_slm or _use_compact:
            # SLM/compact paths haven't applied the lang directive yet at the
            # head — apply both ends now for symmetry.
            system = _lang_directive + system + _lang_reminder
        else:
            # Full path already has the lang directive at the head (inside
            # the cacheable segment). Just append the reminder.
            system = system + _lang_reminder

        # ── Context fitting (prevent overflow) ────────────────────────────
        # NOTE: get_active_model is imported at create_agent_node() scope (line ~167).
        # Re-importing it here would shadow the closure and trigger UnboundLocalError
        # at the earlier usage line 271 (_model = get_active_model()).
        from app.services.context_manager import fit_messages_to_context

        _sanitized = _sanitize_messages_for_mistral(messages)

        # Email / placeholder addendum — refactor Phase 4.2 (builders.system_prompt).
        system += extract_email_block_addendum(_sanitized)

        # ── Inference ──────────────────────────────────────────────────────
        if use_slm:
            try:
                _slm_fitted = fit_messages_to_context(
                    messages=_sanitized,
                    system_prompt=system,
                    model=settings.slm_model,
                    reserve_for_response=1024,
                )
                response = await asyncio.wait_for(
                    _slm_with_tools.ainvoke(
                        [{"role": "system", "content": system}]
                        + _slm_fitted
                    ),
                    timeout=settings.slm_timeout,
                )
                model_used = f"slm:{settings.slm_model}"
                logger.info(
                    "SLM answered (score=%d, model=%s, reason=%s)",
                    decision.score, settings.slm_model, decision.reason,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "SLM timeout after %.1fs (score=%d) — falling back to LLM",
                    settings.slm_timeout, decision.score,
                )
            except Exception as exc:
                logger.warning(
                    "SLM error (score=%d): %s — falling back to LLM",
                    decision.score, exc,
                )

        if response is None:
            # LLM path (or SLM fallback) — needs full system prompt if not built yet
            if use_slm:
                # SLM failed: rebuild full system prompt for LLM fallback. We
                # reuse the Chantier 2 cache machinery so the rebuilt prompt
                # follows the same cacheable/dynamic split as the primary
                # full path. This gives the SLM-fallback flow the same prompt
                # cache hit benefit on subsequent turns.
                from app.services.memory_service import get_user_context as _guc

                async def _fb_build_snapshot() -> str:
                    constraints, memories_, past_interactions, preferences, user_profile = (
                        await asyncio.gather(
                            memory.get_relevant_constraints(user_query, user_id),
                            memory.get_relevant_memories(user_query, user_id),
                            memory.get_relevant_interactions(user_query, user_id, limit=3),
                            memory.get_user_preferences(user_id),
                            _guc(user_id),
                        )
                    )
                    return _format_memory_block(
                        user_profile or "",
                        preferences or [],
                        constraints or [],
                        memories_ or [],
                        past_interactions or [],
                    )

                _fb_snapshot = await _frozen_mem.get_or_build(
                    _conv_id_fb, user_id, _fb_build_snapshot,
                )
                # Use the same IMPORTANT note as the primary path
                # (LLM_INTROSPECTION_NOTE imported from builders.system_prompt).
                # Slight content drift between primary/fallback would have broken
                # the prompt cache prefix mid-conversation — single constant
                # avoids that whole class of bug.
                def _fb_build_cacheable() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + LLM_INTROSPECTION_NOTE
                        + _fb_snapshot
                    )

                _fb_cacheable = _spc.get_or_build(_conv_id_fb, _fb_build_cacheable)
                system = (
                    _fb_cacheable
                    + _date_segment
                    + _lang_reminder
                )

            # Tier routing: pick the right local/cloud model based on complexity.
            # CRITICAL PERF: the "general" node has access to ALL ~148 tools, which
            # makes bind_tools + the first inference extremely slow (the prompt grows
            # by ~30k tokens with 148 tool schemas). The supervisor already routes
            # tool-needing queries to sub-agents (workspace, infra…), so general is
            # mostly used for chitchat and quick facts that don't need tools. We only
            # bind tools when the query likely needs one (COMPLEX tier, or detected
            # tool keywords).
            from app.services.llm_provider import (
                classify_complexity, get_llm_for_tier, ComplexityTier,
                build_llm_for_provider, get_tier_config,
            )
            _tier = classify_complexity(user_query)

            # ── Hermes Chantier 4 — fallback chain bootstrap ─────────────
            # Capture (or recreate) the per-conversation FallbackState. The
            # chain comes from tier_config so the user only manages providers
            # in one place (Settings → Routage). If a previous turn already
            # switched to a fallback provider, ``_fb_state`` carries that
            # choice into this turn (sticky for the conversation).
            # _conv_id_fb is hoisted to the top of agent_node (used by Chantier 2 too).
            _fb_state = None
            if _conv_id_fb:
                _tier_cfg_for_fb = get_tier_config().get(_tier.value, {})
                _chain = list(_tier_cfg_for_fb.get("providers", []) or [])
                if _chain:
                    _fb_state = _fb.get_or_create(_conv_id_fb, _tier.value, _chain)
                    # Retry hotfix (audit Gemini §1.3) — if a fallback has been
                    # active long enough, give the primary a fresh chance. The
                    # call is idempotent and cheap : it only mutates state when
                    # the cool-down has elapsed AND a fallback is currently
                    # active. See ``fallback_manager.should_retry_primary``.
                    if _fb.should_retry_primary(_conv_id_fb):
                        _fb.reset_to_primary(_conv_id_fb, reason="cooldown_elapsed")
                    logger.info(
                        "[chantier4] conv=%s tier=%s chain=%s active_idx=%d (provider=%r)",
                        _conv_id_fb[:8], _tier.value, _chain,
                        _fb_state.current_index, _fb_state.current_provider,
                    )
                else:
                    logger.info(
                        "[chantier4] conv=%s tier=%s — empty chain in tier_config, "
                        "fallback manager INACTIVE (legacy path)",
                        _conv_id_fb[:8], _tier.value,
                    )
            # Bind tools only for COMPLEX queries OR when the query explicitly mentions
            # tool-related actions. SIMPLE/MEDIUM small-talk and quick facts skip binding.
            _tool_kw = re.compile(
                # Mots-clés qui déclenchent bind_tools sur les tiers
                # SIMPLE / MEDIUM (pour COMPLEX les tools sont toujours bound).
                # Cette regex doit matcher au moins UN verbe / nom de domaine
                # de la requête utilisateur pour que l'agent voie ses outils.
                #
                # Audit 2026-05-26 : enrichi avec verbes de lecture/navigation
                # (regarde / vérifie / consulte / ouvre / navigue) +
                # vocabulaire réseaux sociaux + apps grand public — sans ces
                # ajouts, « regarde mes réseaux sociaux » échappait au
                # bind_tools sur Gemma 4 et le LLM inventait qu'il ne
                # pouvait rien faire (observé en prod sur conv réseau social).
                #
                # « rdv » / « rendez-vous » / « réunion » / « meeting » ajoutés
                # (mai 2026) — sans eux, « Mes RDV cette semaine » échappait au
                # bind_tools et le LLM hallucinait un agenda inventé.
                r"\b("
                # Verbes d'action explicites
                r"envoie|envoy|crée|liste|cherche|recherche|trouve|génère|"
                r"exécute|lance|planifie|programme|enregistre|sauvegarde|"
                r"supprime|archive|copie|déplace|renomme|partage|"
                # Verbes de lecture / consultation / navigation
                r"regarde|regard|consulte|vérifie|vérific|verifie|ouvre|navigue|"
                r"affiche|montre|résume|résum|read|lis"
                # Domaines métiers
                r"|mail|email|courriel|calendrier|agenda|rendez.?vous|rdvs?|"
                r"réunions?|meetings?|drive|sheet|doc|tâche|rappel|note|"
                r"fichier|capture|screenshot|météo|news|traduis"
                # Réseaux sociaux + apps grand public
                r"|réseau(x)?\s*sociau(x)?|reseau(x)?\s*sociau(x)?|"
                r"social[\s-]*media|profil|profile|"
                r"linkedin|mastodon|twitter|x\.com|instagram|insta|"
                r"facebook|threads|bluesky|tiktok|youtube|"
                r"abonn[ée]s?|follower|followers|mention|mentions|"
                r"post|posts|tweet|tweets|publication|publications|"
                r"notif|notifs|notification|notifications|"
                # Sites de service souvent croisés
                r"doctolib|sncf|booking|amazon|leboncoin"
                # Sprint 0.7 (2026-05-26) — Chrome v2 read-only inspectors.
                # Without these, « quels sites j'ai visité ? » /
                # « cherche dans mon historique de navigation » /
                # « mes téléchargements du jour » skipped bind_tools and
                # the LLM said "I have no tool for that" while
                # browser_history_search / _bookmarks_search /
                # _downloads_search were sitting right there.
                r"|historique|navigation|visit[eéès]?|"
                r"signets?|favori|favoris|bookmark|bookmarks|"
                r"t[ée]l[ée]charg\w*|download|downloads|"
                r"chrome|navigateur|browser|"
                # "site"/"sites" alone is too generic (matches "le site
                # de la marque"). Require a navigation-y neighbour to
                # avoid bind_tools on chitchat about brands' websites.
                r"sites?\s+(visit|web|internet|consult|all[ée]s?|fr[ée]quent)"
                r")\b",
                re.IGNORECASE,
            )
            # When a sticky toolset profile is defined for the conversation,
            # ALWAYS bind that profile's tools — even for chitchat. The
            # model needs to see the same catalog every turn to learn it
            # (Hermes pattern, Chantier 1). The cost is ~3-5K tokens of
            # tool schemas per call, which is the price for stability.
            _has_profile = bool(state.get("toolset_profile") or "")
            _bind_tools_flag = (
                _has_profile or
                bool(state.get("automated_task")) or
                _tier == ComplexityTier.COMPLEX or
                bool(_tool_kw.search(user_query))
            )
            _tier_key = _tier.value
            # Cache key differentiates with/without tools bound
            # FIX 2026-05-06 (audit H-5): apply keyword-based tool filtering
            # to avoid binding all 160 tools at every turn. Sub-agents had
            # this filter; the general agent_node did not — resulting in
            # ~15 000 tokens of tool definitions per request (99 % of the
            # prompt) and 5+ minutes of prompt processing on local LLMs.
            #
            # We cache the BASE (unbound) LLM only. Tool binding is cheap
            # and runs per-call with the filtered list — the cache key now
            # encodes only the tier identity.
            # Hermes Chantier 4 — if a fallback is already active for this
            # conversation, build the LLM from the explicit provider rather
            # than re-running the tier cascade (which would land on the
            # primary again). Skip cache because fallback state is per-
            # conversation, not per-tier.
            if _fb_state is not None and _fb_state.is_active_fallback:
                _bind_start = _t.monotonic()
                _base_llm = build_llm_for_provider(_fb_state.current_provider, _tier)
                if _base_llm is None:
                    # Provider can't be instantiated (no key, etc.) — fall
                    # back to the standard tier resolution. We do NOT advance
                    # the chain here ; that's the job of the exception handler.
                    logger.warning(
                        "[fallback] conv=%s active provider %r unbuildable, "
                        "using tier resolution as last resort",
                        _conv_id_fb, _fb_state.current_provider,
                    )
                    _base_llm = get_llm_for_tier(_tier)
                logger.warning(
                    "⏱ TIMING[general.bind_base] %.2fs — tier=%s [FALLBACK active=%r]",
                    _t.monotonic() - _bind_start, _tier_key,
                    _fb_state.current_provider,
                )
            else:
                _base_cache_key = f"{_tier_key}:base"
                if _base_cache_key not in _tier_llm_cache:
                    _bind_start = _t.monotonic()
                    _base_llm = get_llm_for_tier(_tier)
                    _tier_llm_cache[_base_cache_key] = _base_llm
                    logger.warning("⏱ TIMING[general.bind_base] %.2fs — tier=%s (tools_v=%d, cfg_v=%d)",
                        _t.monotonic() - _bind_start, _tier_key, current_version, current_cfg_version)
                _base_llm = _tier_llm_cache[_base_cache_key]

            if _bind_tools_flag:
                # FIX 2026-05-07 (Hermes Chantier 1): prefer the sticky
                # toolset profile from state if defined. This binds the
                # SAME ~30-tool catalog every turn for the conversation,
                # so the model can learn it as muscle memory and the
                # prompt cache prefix stays intact. Empty profile = fall
                # back to the legacy keyword filter (graceful migration).
                _profile = state.get("toolset_profile") or ""
                if _profile:
                    from app.agent.toolset_profiles import resolve_profile_tools
                    _filtered_tools = resolve_profile_tools(
                        _profile, registry.all_tools,
                    )
                    logger.warning(
                        "[diag.bind] tier=%s profile=%r tools(%d)=%s",
                        _tier_key, _profile, len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )
                else:
                    # Legacy path — no profile set (e.g. external API caller
                    # or pre-Chantier-1 conversation row).
                    from app.agent.tool_filter import filter_tools_by_query
                    _filtered_tools = filter_tools_by_query(
                        registry.all_tools,
                        user_query,
                        threshold=20,
                        debug_label=f"general.{_tier_key}",
                    )
                    logger.warning(
                        "[diag.bind] tier=%s query=%r tools(%d)=%s [LEGACY]",
                        _tier_key,
                        user_query[:80] if user_query else "",
                        len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )

                # Automated / scheduled tasks run a FIXED, multi-domain prompt
                # with no human to clarify with. The keyword filter above —
                # tuned to keep local-model prompts short — is accent/word-
                # boundary fragile and silently drops tools the prompt
                # explicitly names (prod « Briefing quotidien 9h » lost
                # calendar_list_events + system_list_scheduled_tasks, keeping
                # only the matched gmail_ tools). Union in every registered
                # tool whose exact name appears in the prompt so the agent
                # binds the tools it was told to call. Cheap: runs once per
                # scheduled task on the cloud tier where prompt processing
                # is not the bottleneck.
                if state.get("automated_task"):
                    from app.agent.tool_filter import tools_named_in_text
                    _named = tools_named_in_text(registry.all_tools, user_query)
                    _have = {t.name for t in _filtered_tools}
                    _extra = [t for t in _named if t.name not in _have]
                    if _extra:
                        _filtered_tools = list(_filtered_tools) + _extra
                        logger.warning(
                            "[automated_task] +%d named tool(s) bound: %s",
                            len(_extra), sorted(t.name for t in _extra),
                        )

                # When the user's ELY Chrome extension is connected, hide
                # the server-side Playwright tools entirely. They live in
                # a separate, cookie-less context that always lands on
                # login pages — and the LLM tends to fall back to them
                # the second `browser_tab_*` returns less data than
                # expected. Removing them from the toolkit makes the
                # fallback impossible (belt-and-braces with the system
                # prompt rule).
                try:
                    from app.services import browser_extension_registry as _bext
                    _uid_for_bext = str(state.get("user_id") or "")
                    if _uid_for_bext and _bext.is_connected(_uid_for_bext):
                        _PLAYWRIGHT_TOOLS = {
                            "browser_navigate", "browser_screenshot",
                            "browser_get_text", "browser_search_web",
                            "browser_click", "browser_fill", "browser_close",
                        }
                        _before = len(_filtered_tools)
                        _filtered_tools = [
                            t for t in _filtered_tools if t.name not in _PLAYWRIGHT_TOOLS
                        ]
                        if len(_filtered_tools) != _before:
                            logger.warning(
                                "[diag.bind] extension connected → hiding %d Playwright tool(s); "
                                "agent now has %d tools",
                                _before - len(_filtered_tools), len(_filtered_tools),
                            )
                except Exception as _bext_err:
                    logger.debug("[diag.bind] extension-check skipped: %s", _bext_err)

                # Sprint 2.7 — hide tier_c_only tools from SIMPLE/MEDIUM
                # tiers. orchestrate is the canonical case: tier A/B models
                # can't write correct Python scripts, so exposing the tool
                # to them just burns tokens on broken sandbox runs.
                if _tier != ComplexityTier.COMPLEX:
                    from app.agent.tool_sets import TIER_C_ONLY_TOOLS
                    _before_tc = len(_filtered_tools)
                    _filtered_tools = [
                        t for t in _filtered_tools if t.name not in TIER_C_ONLY_TOOLS
                    ]
                    if len(_filtered_tools) != _before_tc:
                        logger.info(
                            "[diag.bind] tier=%s — dropped %d tier_c_only tool(s)",
                            _tier_key, _before_tc - len(_filtered_tools),
                        )

                # Mini-chantier A — apply parallel_tool_calls policy by
                # model family. Permissive models (Qwen, Mistral…) and OpenAI
                # family invent downstream args (e.g. fake local_path) when
                # they emit parallel tool_calls. Forcing one-call-per-turn
                # makes the model wait for each result before chaining.
                _llm_with_tools_req = _bind_tools_smart(_base_llm, _filtered_tools)
            else:
                _llm_with_tools_req = _base_llm
            # Resolve the actual provider+model behind the tier so analytics
            # shows "lm_studio/llama-xlam-2-8b-fc-r-mlx" instead of "tier-medium".
            # Falls back gracefully to the tier label if introspection fails.
            try:
                from app.services.llm_provider import describe_llm
                _p, _m = describe_llm(_base_llm)
                model_used = f"llm:{_p}/{_m}{'+tools' if _bind_tools_flag else ''}"
            except Exception:
                model_used = f"llm:tier-{_tier_key}{'+tools' if _bind_tools_flag else ''}"

            _fitted = fit_messages_to_context(
                messages=_sanitized,
                system_prompt=system,
                model=_tier_key,
                reserve_for_response=1024,
            )
            _invoke_msgs = (
                [{"role": "system", "content": system}]
                + _fitted
            )
            try:
                _infer_t = _t.monotonic()
                from app.services.qwen_no_think import (
                    inject_no_think, is_qwen_llm, strip_no_think, strip_think_block,
                )
                # Only Qwen understands /no_think; other models would echo it.
                if is_qwen_llm(_base_llm):
                    _invoke_msgs = inject_no_think(_invoke_msgs)
                # FIX 2026-05-06 (P1 OpenClaw-style): if a recent ToolMessage
                # carries a base64 screenshot AND the model supports vision,
                # inject the image as a HumanMessage so the model can SEE it
                # rather than just read the JSON metadata.
                try:
                    from app.agent.vision_injection import maybe_inject_screenshot
                    _invoke_msgs = maybe_inject_screenshot(_invoke_msgs, _base_llm)
                except Exception as _vis_exc:
                    logger.debug("vision_injection skipped: %s", _vis_exc)
                response = await _llm_with_tools_req.ainvoke(_invoke_msgs)
                # Strip any <think> block that slipped through
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)
                    # Note: empirically tried 3 rounds of fixes to suppress the
                    # JSON re-encoding that cloud LLMs apply to
                    # search_past_conversations_tool output (system prompt
                    # rules, tool docstring, server-side regex filter). None
                    # held on DeepSeek/Haiku/Qwen/Mistral/Kimi — only the
                    # local Ministral 3B respects the prose format. Franck
                    # decision 2026-05-16: accept the cosmetic JSON leak,
                    # don't accumulate defensive code that may have side
                    # effects elsewhere. The functional memory recall is
                    # solid; the structural-output bias is a known LLM-side
                    # behaviour that should be addressed via product design
                    # later (e.g. dedicated UI rendering, or a bypass that
                    # ships the tool output directly without LLM reformat).

                # FIX 2026-05-06 (Option A): some cloud models (Kimi K2.x,
                # Qwen 3.6 Flash via DashScope, occasionally DeepSeek) emit
                # tool calls as TEXT inside content instead of populating
                # the structured `tool_calls` field. Without recovery, the
                # graph receives `tool_calls=[]` and stalls. Also handles
                # hallucinated tool names like `send_email` →
                # `gmail_send_email` via fuzzy matching.
                from app.agent.tool_call_recovery import (
                    recover_tool_calls_into_response,
                    detect_empty_promise,
                )
                # DIAG 2026-05-06: log raw response shape BEFORE recovery
                _raw_tc = getattr(response, "tool_calls", None) or []
                _raw_content = getattr(response, "content", "") or ""
                _raw_content_str = _raw_content if isinstance(_raw_content, str) else str(_raw_content)
                logger.warning(
                    "[diag.resp] tier=%s raw_tool_calls=%d content_len=%d content_head=%r",
                    _tier_key, len(_raw_tc), len(_raw_content_str), _raw_content_str[:200],
                )
                _recovered = recover_tool_calls_into_response(
                    response,
                    real_tool_names={t.name for t in registry.all_tools},
                )
                if _recovered:
                    logger.warning(
                        "[recovery] tier=%s — recovered %d tool_call(s) from text content",
                        _tier_key, _recovered,
                    )

                # FIX 2026-05-06 (P4): empty-promise guard — if the model
                # claims delivery ("je télécharge sur ton Drive…", "sending
                # the file now…") but produced ZERO tool_calls, re-invoke
                # with a corrective system message. Limited to ONE retry
                # per turn to avoid infinite loops if the model is stubborn.
                _post_tc = getattr(response, "tool_calls", None) or []
                _post_content = getattr(response, "content", "") or ""
                _post_content_str = _post_content if isinstance(_post_content, str) else str(_post_content)
                if not _post_tc and detect_empty_promise(_post_content_str):
                    logger.warning(
                        "[empty_promise] tier=%s — model promised delivery without "
                        "calling a tool. Content head: %r. Re-prompting once.",
                        _tier_key, _post_content_str[:200],
                    )
                    _correction_msg = {
                        "role": "system",
                        "content": (
                            "⚠️ Tu viens d'écrire que tu télécharges/envoies/sauvegardes "
                            "le fichier MAIS tu n'as appelé AUCUN outil dans ton dernier "
                            "message. Cette promesse est vide — l'utilisateur ne reçoit rien.\n\n"
                            "DEUX OPTIONS :\n"
                            "1. Si tu DOIS livrer le fichier maintenant, réémets ta "
                            "réponse en appelant explicitement l'outil approprié "
                            "(gmail_send_with_local_attachment, drive_create_file, "
                            "desktop_copy_file, etc.) avec les bons paramètres.\n"
                            "2. Si tu ne peux pas (paramètre manquant), dis-le clairement "
                            "à l'utilisateur et demande-lui le paramètre manquant — sans "
                            "prétendre qu'une livraison est en cours.\n\n"
                            "NE répète PAS la phrase « en cours de téléchargement » sans "
                            "appel d'outil cette fois-ci."
                        ),
                    }
                    try:
                        _retry_msgs = list(_invoke_msgs) + [
                            {"role": "assistant", "content": _post_content_str},
                            _correction_msg,
                        ]
                        _retry_response = await _llm_with_tools_req.ainvoke(_retry_msgs)
                        _retry_tc = getattr(_retry_response, "tool_calls", None) or []
                        _retry_content = getattr(_retry_response, "content", "") or ""
                        if _retry_tc:
                            logger.warning(
                                "[empty_promise] retry produced %d tool_call(s) — "
                                "replacing original response", len(_retry_tc),
                            )
                            response = _retry_response
                        elif isinstance(_retry_content, str) and _retry_content.strip():
                            # No tool but a clearer prose without false promise — use it
                            if not detect_empty_promise(_retry_content):
                                logger.warning("[empty_promise] retry returned honest prose — using it")
                                response = _retry_response
                            else:
                                logger.warning("[empty_promise] retry STILL promises without tool — keeping original")
                    except Exception as _retry_exc:
                        logger.warning("[empty_promise] retry failed (%s)", _retry_exc)

                logger.warning("⏱ TIMING[general.infer] %.2fs — tier=%s, tool_calls=%d",
                    _t.monotonic() - _infer_t, _tier_key, len(getattr(response, 'tool_calls', []) or []))

                # ── Audit H-1 fix (2026-05-06, refined 2026-05-26): garde anti-hallu ──
                # Modèles locaux 7-14B (Qwen, Mistral, Llama small) ont
                # tendance à émettre du TEXTE en plain "je vais faire X"
                # au lieu d'un tool_call JSON, surtout sur des verbes
                # d'action explicites ("envoie", "supprime", "crée").
                # Symptôme observé en prod : Qwen 3 VL 8B refuse "envoie
                # par mail" au lieu d'appeler gmail_send_with_attachment.
                # Garde : si modèle LOCAL + 0 tool_calls + user query
                # contient un verbe d'action → fallback cloud immédiat.
                #
                # 2026-05-26 : ajout d'un log détaillé AVANT la décision,
                # suite à un faux-positif observé le 25/05 où DeepSeek-pro
                # (cloud, base_url=api.deepseek.com) a été incorrectement
                # flaggé comme local → conv stickée sur Haiku 1h+. Ce log
                # permettra de diagnostiquer la prochaine occurrence sans
                # reproduire le scénario en aveugle.
                _has_tool_calls = bool(getattr(response, 'tool_calls', None))
                from app.services.qwen_no_think import is_local_openai_llm as _is_local_oa
                _is_local = _is_local_oa(_base_llm)
                # Kill-switch (2026-05-31) : H-1 forces a cloud fallback when a
                # LOCAL model returns plain text instead of a tool_call on an
                # action query. That's the right default, but it makes
                # benchmarking a new local model painful (every tool query
                # silently escapes to DeepSeek). HALLUCINATION_GUARD_DISABLED
                # truthy = let the local response stand, no forced fallback.
                _h1_disabled = (os.getenv("HALLUCINATION_GUARD_DISABLED") or "").strip().lower() in {
                    "1", "true", "yes", "on",
                }
                _action_verbs = (
                    "envoie", "envoy", "supprime", "delete", "send",
                    "crée", "creer", "create", "écris", "ecris", "write",
                    "lance", "exécute", "execute", "run", "schedule",
                    "rappel", "remind", "ferme", "close", "ouvre", "open",
                    "télécharge", "download", "achète", "buy", "réserve",
                    "book", "réponds", "reply", "transfère", "transfer",
                    "capture", "screenshot", "photographie",
                )
                _query_has_action = any(v in user_query.lower() for v in _action_verbs)
                # Detailed log so any future false-positive is easy to debug
                _h1_base_url = (
                    getattr(_base_llm, "openai_api_base", None)
                    or getattr(_base_llm, "base_url", None)
                    or ""
                )
                _h1_model_name = (
                    getattr(_base_llm, "model_name", None)
                    or getattr(_base_llm, "model", None)
                    or ""
                )
                if _query_has_action and _bind_tools_flag:
                    logger.info(
                        "[H-1.eval] tier=%s local=%s tool_calls=%d action=%s "
                        "model=%r base_url=%r",
                        _tier_key, _is_local, len(getattr(response, "tool_calls", []) or []),
                        _query_has_action, _h1_model_name, _h1_base_url,
                    )
                if (
                    _is_local
                    and not _has_tool_calls
                    and _query_has_action
                    and _bind_tools_flag
                    and not _h1_disabled
                ):
                    logger.warning(
                        "[H-1] Local LLM (tier=%s) returned PLAIN TEXT instead of "
                        "tool_call despite action verb in user query — falling "
                        "back to cloud LLM. Response preview: %r",
                        _tier_key, (response.content or "")[:120],
                    )
                    # Force-trigger the fallback path below by raising a
                    # synthetic "recoverable" exception. The existing fallback
                    # loop will iterate through get_fallback_llms() and pick
                    # the first cloud model with a working API key.
                    raise RuntimeError("h1_fallback: local LLM hallucinated plain text")
            except Exception as primary_exc:
                # Hermes Chantier 4 — classify the exception and ask the
                # FallbackManager to advance to the next provider in the
                # conversation's chain. If the exception is unrecognised
                # (genuine programmer bug), we re-raise so it surfaces.
                _reason = _fb.classify_exception(primary_exc)
                if _reason is None:
                    raise

                logger.warning(
                    "[fallback] primary LLM failed (%s/%s): %s",
                    type(primary_exc).__name__, _reason.value, primary_exc,
                )
                response = None
                # Strip any /no_think marker (Qwen-only) before trying a
                # different provider that doesn't understand it.
                _fallback_msgs = strip_no_think(_invoke_msgs)

                # Walk forward through the chain until a provider answers or
                # the chain is exhausted. Each provider is given ONE attempt;
                # subsequent failures advance again. This loop is bounded by
                # len(chain) so it can never spin.
                if _conv_id_fb and _fb_state is not None:
                    while True:
                        # Sprint 3.7 Jalon 2 — capture the BEFORE state so the
                        # learning signal can record from→to once try_activate
                        # has advanced the chain.
                        _from_provider_before = _fb_state.current_provider
                        _new_provider_id = _fb.try_activate(_conv_id_fb, _reason)
                        if _new_provider_id:
                            try:
                                from app.services.learning import record_provider_switch
                                asyncio.create_task(record_provider_switch(
                                    user_id=user_id,
                                    conversation_id=_conv_id_fb,
                                    tier_llm=_tier.value if hasattr(_tier, "value") else str(_tier),
                                    from_provider=_from_provider_before,
                                    to_provider=_new_provider_id,
                                    reason=_reason.value if hasattr(_reason, "value") else str(_reason),
                                    position_in_chain=_fb_state.current_index + 1,
                                ))
                            except Exception as _sig_exc:
                                logger.debug("provider switch signal skipped: %s", _sig_exc)
                        if not _new_provider_id:
                            logger.warning(
                                "[fallback] chain exhausted for conv=%s",
                                _conv_id_fb,
                            )
                            break
                        _new_llm = build_llm_for_provider(_new_provider_id, _tier)
                        if _new_llm is None:
                            logger.warning(
                                "[fallback] provider %r unbuildable, advancing",
                                _new_provider_id,
                            )
                            continue  # ask manager for the next one
                        try:
                            # PRESERVE the toolset profile — the cardinal sin
                            # of the old fallback loop was rebinding all 145
                            # tools, breaking the Chantier 1 contract. Here
                            # we re-bind exactly the same _filtered_tools the
                            # primary saw.
                            if _bind_tools_flag:
                                # Apply same parallel-policy as primary,
                                # auto-detecting the new provider's family.
                                _new_with_tools = _bind_tools_smart(
                                    _new_llm, _filtered_tools,
                                )
                            else:
                                _new_with_tools = _new_llm
                            response = await _new_with_tools.ainvoke(_fallback_msgs)
                            logger.warning(
                                "[fallback] succeeded with %r", _new_provider_id,
                            )
                            # Keep model_used in sync with the active provider.
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(_new_llm)
                                model_used = f"llm:{_p}/{_m}+tools[fallback]"
                            except Exception:
                                model_used = f"llm:{_new_provider_id}+tools[fallback]"
                            break
                        except Exception as _next_exc:
                            _next_reason = _fb.classify_exception(_next_exc)
                            if _next_reason is None:
                                # Real bug in the new provider — re-raise.
                                raise
                            logger.warning(
                                "[fallback] %r also failed (%s): %s — advancing",
                                _new_provider_id, _next_reason.value, _next_exc,
                            )
                            _reason = _next_reason
                            continue

                # SAFETY NET (Chantier 4 V1.1) — if the per-tier chain didn't
                # produce a working response (single-provider tier, all
                # providers exhausted, instances unbuildable…), DO NOT raise
                # yet. Try the legacy global fallback list first (Gemini,
                # Anthropic, OpenRouter, Ollama installed system-wide). This
                # restores the pre-Chantier-4 robustness for users whose tier
                # config is minimal — better to silently bind 145 tools on a
                # cloud frontier than to surface "Erreur interne" to the user.
                if response is None:
                    logger.info(
                        "[fallback] tier-chain exhausted/unavailable, "
                        "trying legacy global helpers"
                    )
                    for fallback_label, fallback_llm in get_fallback_llms():
                        try:
                            # fallback_label is "anthropic/claude-…" or
                            # "gemini/gemini-2.5-flash" — extract model name
                            # for family classification.
                            _legacy_model_name = (
                                fallback_label.split("/", 1)[1]
                                if "/" in fallback_label
                                else fallback_label
                            )
                            _legacy_with_tools = (
                                _bind_tools_smart(
                                    fallback_llm, _filtered_tools,
                                    model_name=_legacy_model_name,
                                )
                                if _bind_tools_flag
                                else fallback_llm
                            )
                            response = await _legacy_with_tools.ainvoke(_fallback_msgs)
                            logger.info(
                                "[fallback] legacy succeeded with %s", fallback_label,
                            )
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(fallback_llm)
                                model_used = f"llm:{_p}/{_m}+tools[legacy_fallback]"
                            except Exception:
                                model_used = f"llm:{fallback_label}+tools[legacy_fallback]"
                            break
                        except Exception as fallback_exc:
                            logger.warning(
                                "[fallback] legacy %s also failed: %s",
                                fallback_label, fallback_exc,
                            )

                if response is None:
                    raise primary_exc

        # Hermes Chantier 4 — track this turn's response so the manager can
        # detect empty-streaks (≥3 empties → auto-fallback on the next turn).
        # We pass the current response's content + tool_calls flag.
        if _conv_id_fb and _fb_state is not None and response is not None:
            _resp_content = getattr(response, "content", "") or ""
            if isinstance(_resp_content, list):
                # Multi-block content — concatenate text chunks.
                _resp_content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in _resp_content
                )
            _has_tc = bool(getattr(response, "tool_calls", None))
            try:
                _fb.record_response(_conv_id_fb, str(_resp_content), _has_tc)
            except Exception as _rec_exc:
                logger.debug("fallback.record_response failed: %s", _rec_exc)

        # Fire-and-forget: extract facts from this exchange for user memory
        if user_id:
            from app.services.memory_service import extract_and_store_facts

            async def _safe_memory_extract(uid, msgs):
                try:
                    await extract_and_store_facts(uid, "", msgs)
                except Exception as exc:
                    logger.debug("Memory extraction failed: %s", exc)

            asyncio.create_task(_safe_memory_extract(user_id, messages + [response]))

        # Hermes Chantier 9 — increment the iteration counter when the
        # response carries tool_calls (i.e. the loop will bounce back here
        # for another inference). Bare-text responses don't loop, so they
        # don't burn the budget. The counter is read by ``should_continue``
        # to detect when we're approaching the recursion limit and need
        # to force a final textual summary.
        _has_tool_calls = bool(getattr(response, "tool_calls", None))
        _next_iter = state.get("iteration_count", 0) + (1 if _has_tool_calls else 0)
        return {
            "messages": [response],
            "model_used": model_used,
            "routing_score": routing_score,
            "iteration_count": _next_iter,
        }

    return agent_node


# ------------------------------------------------------------------ #
# Tool node                                                            #
# ------------------------------------------------------------------ #
# Moved to app/agent/tool_node.py (refactor 2026-05-25 Phase 3).
from app.agent.tool_node import tool_node  # noqa: E402,F401


# ------------------------------------------------------------------ #
# Router                                                               #
# ------------------------------------------------------------------ #

# Moved to app/agent/routing.py (refactor 2026-05-25 Phase 2.1).
from app.agent.routing import (  # noqa: E402,F401
    MAX_AGENT_ITERATIONS,
    should_continue,
)


# Moved to app/agent/force_summary.py (refactor 2026-05-25 Phase 2.2).
from app.agent.force_summary import force_summary_node  # noqa: E402,F401
