# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/nodes.py
# @brief      Persistence-loop nodes — real Plan / Act / Eval / Replan logic
# =============================================================================
"""Persistence-loop nodes — real Plan / Act / Eval / Replan logic.

Each node :
  1. Reads the current state.
  2. Calls the LLM (or dispatches a tool) to do its part.
  3. Persists a `MissionStep` audit row via `mission_service.add_step`.
  4. Returns a state delta that LangGraph merges.

Design :
  - One iteration of the graph = one "tick" = exactly ONE pass through
    plan→act→eval (skipping plan if already built, optionally branching
    to replan). The graph EXITS at the end of each tick — the heartbeat
    re-invokes for the next tick. This keeps budget guards tight and the
    kill switch instant.
  - Plan / Eval / Replan use the MEDIUM tier (Gemma 4 21B REAP locally).
    Act uses the same tier with `bind_tools` for function-calling.
  - HITL requests run inline before tool dispatch — same code path as
    the chat-mode `tool_node` so the user gets a unified experience.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)

from app.agent.missions.state import MissionState
from app.services import mission_service

logger = logging.getLogger(__name__)


def _extract_provider_model(llm: Any) -> tuple[str, str]:
    """Best-effort extraction of (provider, model) from a LangChain LLM.

    LangChain's BaseChatModel doesn't expose a uniform "provider" attribute —
    we sniff the class name + common model attributes. Used only for usage
    analytics tagging, so a "unknown" fallback is acceptable.
    """
    cls_name = type(llm).__name__.lower()
    if "anthropic" in cls_name:
        provider = "anthropic"
    elif "google" in cls_name or "genai" in cls_name or "gemini" in cls_name:
        provider = "gemini"
    elif "ollama" in cls_name:
        provider = "ollama"
    elif "openai" in cls_name:
        # Could be real OpenAI, LM Studio, OpenRouter, Qwen API, vLLM…
        # Use base_url to disambiguate.
        base = getattr(llm, "openai_api_base", "") or getattr(llm, "base_url", "") or ""
        base_low = str(base).lower()
        if (
            "lmstudio" in base_low
            or "127.0.0.1:1234" in base_low
            or "localhost:1234" in base_low
            or "host.docker.internal:1234" in base_low
            or ":1234/v1" in base_low
        ):
            provider = "lm_studio"
        elif "openrouter" in base_low:
            provider = "openrouter"
        elif "dashscope" in base_low or "qwen" in base_low:
            provider = "qwen_api"
        elif "deepseek" in base_low:
            provider = "deepseek"
        else:
            provider = "openai"
    else:
        provider = cls_name.replace("chat", "") or "unknown"
    model = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or "unknown"
    )
    return provider, str(model)


async def _log_mission_llm_usage(
    response: BaseMessage,
    user_id: str,
    mission_id: str,
    phase: str,
    llm: Any,
) -> None:
    """Log token usage for a mission-graph LLM invocation.

    Called fire-and-forget after every `await llm.ainvoke(...)` in this
    module. Reads `response.usage_metadata` (LangChain's normalized
    usage shape — works across Anthropic, OpenAI, Gemini, Qwen, LM Studio,
    Ollama). Falls back to a 4-chars-per-token heuristic when the provider
    doesn't ship usage_metadata (some streaming local models).

    Pre-launch fix #13 : the dashboard was empty because mission ticks
    NEVER called log_usage. With ~3 LLM calls per tick × multiple ticks
    per mission × many missions per day, this represents the bulk of
    LLM activity.
    """
    try:
        from app.services.analytics_service import log_usage

        usage = getattr(response, "usage_metadata", None) or {}
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)

        # Heuristic fallback when usage_metadata is empty (LM Studio streaming)
        if in_tok == 0 and out_tok == 0:
            content = getattr(response, "content", "") or ""
            out_tok = max(1, len(str(content)) // 4)
            # Approximate input by adding a fixed slack — not perfect but
            # better than 0 for cost graphs (and most local models cost $0
            # anyway so the imprecision doesn't matter financially).
            in_tok = max(1, len(str(content)) // 4)

        provider, model = _extract_provider_model(llm)

        import asyncio
        asyncio.create_task(log_usage(
            user_id=user_id,
            model=model,
            provider=provider,
            input_tokens=in_tok,
            output_tokens=out_tok,
            skill_used=f"mission_{phase}",
            channel="mission",
        ))
    except Exception as exc:
        # Non-critical — analytics must never break a mission.
        logger.debug("log_mission_llm_usage failed for mission %s phase %s: %s",
                     mission_id, phase, exc)


# ── Tool dispatch helper (factored from agent/nodes.py:tool_node) ────────────

async def dispatch_tool(
    tool_name: str,
    tool_args: dict,
    tool_call_id: str,
    user_id: str,
    user_request: str = "",
) -> tuple[str, bool]:
    """Run a single tool call with HITL + vault + credential injection.

    Returns (output_text, success_bool). On HITL deny / ban / vault locked,
    success=False with an explanatory output string.

    Mirrors the logic of `app.agent.nodes.tool_node` but for a single call
    instead of a batch — missions execute one tool per iteration so the
    bookkeeping is simpler.
    """
    from app.skills import get_skill_registry
    from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS
    from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter
    from app.services.hitl_manager import get_hitl_manager
    from app.services.memory_manager import get_memory_manager

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    tool = tool_map.get(tool_name)
    if not tool:
        return f"Outil inconnu : {tool_name!r}", False

    # Injected args (never visible in logs/UI)
    args = dict(tool_args)
    if tool_name in GOOGLE_TOOLS:
        from app.services.credential_store import get_credential_store
        _store = get_credential_store()
        _creds = _store.get(user_id) or ""
        # Fallback to DB if the in-memory store is empty — happens for
        # mission heartbeats / scheduled tasks / cron jobs that don't
        # go through chat.py to populate the store (and after every
        # backend restart that wipes the in-memory store). Without this
        # fallback, all Google tools fail with "Google non connecté"
        # even though credentials exist in DB. April 2026 mission #19/15
        # spam-delete loop was caused by exactly this.
        if not _creds and user_id:
            try:
                from app.database import async_session as _async_session
                from app.models.google_account import GoogleAccount as _GA
                from app.models.user import User as _U
                from sqlalchemy import select as _select
                async with _async_session() as _db:
                    # 1. Prefer the default GoogleAccount row
                    _row = await _db.execute(
                        _select(_GA.credentials_json).where(
                            _GA.user_id == user_id,
                            _GA.is_default == True,  # noqa: E712
                        )
                    )
                    _creds = _row.scalar_one_or_none() or ""
                    # 2. Legacy fallback : User.google_credentials column
                    if not _creds:
                        _u = await _db.get(_U, user_id)
                        if _u and _u.google_credentials:
                            _creds = _u.google_credentials
                if _creds:
                    _store.set(user_id, _creds)
                    logger.info(
                        "Mission credential store re-populated from DB for user %s",
                        user_id[:8] + "…",
                    )
            except Exception as _exc:
                logger.warning(
                    "Mission credential DB fallback failed for %s: %s",
                    user_id[:8] + "…", _exc,
                )
        args["user_google_credentials_json"] = _creds
    if tool_name in USER_ID_TOOLS:
        args["user_id"] = user_id

    _hidden = {"user_google_credentials_json", "user_id"}
    display_args = {k: v for k, v in args.items() if k not in _hidden}
    action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"

    # Vault refs resolution
    if any(isinstance(v, str) and v.startswith("vault://") for v in args.values()):
        from app.services.vault_service import get_vault_service
        vault = get_vault_service()
        if vault.is_locked(user_id):
            return "⛔ Vault verrouillé — déverrouillez-le dans Paramètres → Vault.", False
        try:
            args, _resolved = await vault.resolve_vault_refs(user_id, args)
            if _resolved:
                logger.info("Mission: resolved vault refs %s for tool %s", _resolved, tool_name)
        except KeyError as exc:
            return f"⛔ Secret introuvable dans le Vault : {exc}", False

    # HITL gate for sensitive tools
    sf = SecurityFilter()
    needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(action_desc)

    # ── Self-mail auto-approve ────────────────────────────────────────
    # Sending an email to the calling user's own address carries near-zero
    # risk (no data leak to oneself) but used to trigger HITL — impossible
    # to satisfy when the user is offline (e.g. scheduled task at 6 a.m.
    # sends a daily AI digest to franck@gmail.com → HITL prompt nobody
    # answers → email never sent).
    # Mirror of the same logic in app/agent/sub_agents/factory.py used by
    # chat-mode dispatch. April 2026 mission « météo + résumé mails » :
    # self-mail HITL was blocking unattended runs from the heartbeat —
    # missions don't have a UI handler standing by.
    if needs_hitl and tool_name in {
        "gmail_send_email", "gmail_reply_email", "gmail_send_with_attachment",
    }:
        try:
            _to = (args.get("to") or "").strip().lower()
            from app.database import async_session as _async_session
            from app.models.user import User as _U
            from app.models.google_account import GoogleAccount as _GA
            from sqlalchemy import select as _sel
            async with _async_session() as _db:
                _u = await _db.get(_U, user_id) if user_id else None
                _self_emails: set[str] = set()
                if _u and _u.email:
                    _self_emails.add(_u.email.strip().lower())
                if user_id:
                    _rows = await _db.execute(
                        _sel(_GA.email).where(_GA.user_id == user_id)
                    )
                    for (_em,) in _rows.all():
                        if _em:
                            _self_emails.add(str(_em).strip().lower())
            if any(em and em in _to for em in _self_emails):
                logger.info(
                    "Mission HITL skipped (self-mail) — to=%s matches user own address",
                    _to[:80],
                )
                needs_hitl = False
        except Exception as _exc:
            logger.debug("Mission self-mail check failed: %s", _exc)

    if needs_hitl:
        # Replace the technical action_desc with a human-readable version
        # that includes pre-count, the user's original request, and any
        # detected mismatches (May 2026 fix #21 — Temu incident :
        # validating a JSON blob without context = blind approval).
        try:
            from app.services.hitl_descriptions import build_human_hitl_description
            humanized = await build_human_hitl_description(
                tool_name=tool_name,
                args=args,
                user_request=user_request,
                user_credentials_json=args.get("user_google_credentials_json", ""),
            )
        except Exception as _e:
            humanized = action_desc  # fallback to technical
            logger.debug("HITL humanizer failed: %s", _e)
        logger.info("Mission HITL required: %s", action_desc)
        hitl = get_hitl_manager()
        decision, reason = await hitl.request_validation(description=humanized, user_id=user_id)
        if decision == "ban":
            rule = f"INTERDICTION PERMANENTE: {action_desc}"
            if reason:
                rule += f" — Raison: {reason}"
            await get_memory_manager().store_constraint(rule, user_id)
            return "Action interdite définitivement et règle de sécurité enregistrée.", False
        if decision != "allow":
            return "Action refusée par l'utilisateur pour cette occurrence.", False

    # Actually run the tool
    try:
        t0 = time.monotonic()
        result = await tool.ainvoke(args)
        elapsed = time.monotonic() - t0
        logger.warning("⏱ TIMING[mission_tool:%s] %.2fs", tool_name, elapsed)
        return str(result), True
    except Exception as exc:
        logger.warning("Mission tool %s failed: %s", tool_name, exc)
        return f"Erreur d'exécution: {exc}", False


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _get_planner_llm():
    """LLM used for plan / replan — needs reasoning, not tool-calling."""
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier
    return get_llm_for_tier(ComplexityTier.MEDIUM)


# ──────────────────────────────────────────────────────────────────────────────
# ACTION_KEYWORDS — biaise le tool selection par INTENTION (pas par DOMAINE).
#
# FAMILY_KEYWORDS plus bas répond à « le user parle de mail » → expose les 18
# tools gmail_*. ACTION_KEYWORDS répond à « le user veut SUPPRIMER des mails »
# → boost gmail_trash_by_category en tête, plutôt que de noyer le LLM dans
# 18 candidats équivalents. Plus le verbe est précis, plus le boost est utile.
#
# Maintenu manuellement : ajouter une entrée ici quand un tool est mal choisi
# de façon répétée. Mots-clés en FR-first (l'UI est francophone) avec quelques
# équivalents EN pour tenir compte du switch de langue côté user.
# ──────────────────────────────────────────────────────────────────────────────
ACTION_KEYWORDS: dict[str, list[str]] = {
    # Gmail — suppressions / nettoyage (le bug de la session pré-launch)
    "gmail_trash_by_category": [
        "supprime", "supprimer", "vide", "vider", "videz",
        "nettoie", "nettoyer", "purge", "purger", "ménage",
        "débarrasse", "debarrasse",
        "fais le ménage", "fais le menage", "fais place nette",
        "delete", "empty", "clean up", "cleanup", "purge", "remove",
        "spam", "spams", "indesirables", "indésirables",
        "newsletter", "newsletters", "mailing", "mailings",
        "promotions", "promos",
    ],
    # Gmail — suppressions par query custom (sender, subject, date, OR, label
    # custom, etc.). Boost ce tool quand la demande contient un FILTRE en plus
    # d'une catégorie — sinon le LLM choisirait gmail_trash_by_category sans
    # le filtre et viderait toute la catégorie (incident mai 2026 « supprime
    # achats Temu » → 100+ mails non-Temu purgés).
    "gmail_trash_by_query": [
        "expéditeur", "expediteur", "envoyé par", "envoye par",
        "dont le sujet", "qui contient", "avec sujet", "objet",
        "from:", "subject:", "label:",
        "avant le", "après le", "apres le", "datant de",
        "before:", "after:", "older_than", "newer_than",
        # Common combinations of sender + verb that strongly suggest filtering
        "de temu", "de amazon", "de facebook", "de linkedin",
        "from temu", "from amazon",
    ],
    # Gmail — envois
    "gmail_send_email": [
        "envoie un mail", "envoie un email", "envoyer un mail", "envoie un courriel",
        "écris à", "ecris a", "rédige un mail", "redige un mail",
        "compose un mail", "send email", "send a mail", "write to",
    ],
    # Gmail — réponses
    "gmail_reply_email": [
        "réponds à", "reponds a", "répondre à", "repondre a", "réponds au mail",
        "reply to", "answer the email",
    ],
    # Calendar
    "calendar_create_event": [
        "planifie", "planifier", "ajoute au calendrier", "crée un rendez-vous",
        "cree un rdv", "ajoute un événement", "schedule", "add to calendar",
        "book a meeting", "create appointment",
    ],
    "calendar_check_availability": [
        "es-tu libre", "es tu libre", "suis-je libre", "disponibilité",
        "disponibilites", "free time", "availability", "am i free",
    ],
    # Drive
    "drive_share_file": [
        "partage", "partager", "donne accès", "donne acces", "envoie le lien",
        "share with", "share file",
    ],
    "drive_create_folder": [
        "crée un dossier", "cree un dossier", "nouveau dossier",
        "create folder", "new folder",
    ],
    # Knowledge / RAG
    "smart_knowledge_query": [
        "dans mes documents", "dans mes fichiers", "dans ma base",
        "que dit le document", "que dit le contrat", "résume le rapport",
        "in my documents", "in my files", "in my knowledge base",
    ],
    # Web
    "web_search": [
        "cherche sur internet", "cherche en ligne", "recherche web",
        "search the web", "google", "look online",
    ],
}


def _boost_by_action_keywords(text: str, all_tools: list) -> list:
    """Return tools whose registered action keywords match the goal/step text.

    Uses simple lowercase substring matching. The boosted tools are placed
    at the head of the candidate list passed to the LLM, which biases it
    strongly towards them (position #1 in the function-calling list is the
    most likely choice at low temperature).
    """
    text_low = (text or "").lower()
    boosted_names: list[str] = []
    for tool_name, kws in ACTION_KEYWORDS.items():
        if any(kw in text_low for kw in kws):
            boosted_names.append(tool_name)
    if not boosted_names:
        return []
    by_name = {t.name: t for t in all_tools}
    return [by_name[n] for n in boosted_names if n in by_name]


def _filter_tools_for_step(all_tools: list, tool_hint: Optional[str], goal: str, current_step_desc: str = "") -> list:
    """Reduce the tool inventory to a manageable subset for this iteration.

    With 76 tools binded simultaneously, smaller models (xLAM-2-8B,
    Gemini-flash) hit payload-size limits or get confused. We pre-filter
    to ~10-15 tools using THREE signals (in priority order) :

    1. `ACTION_KEYWORDS` boost from goal+step text (most precise) — matches
       INTENTION verbs to specific tools. Ex: "supprime spam" boosts
       `gmail_trash_by_category` to position #1.
    2. `tool_hint` from the plan step — strict match by prefix/family.
       Ex: hint="weather_get" → all tools starting with "weather_".
    3. `FAMILY_KEYWORDS` from goal text (broader fallback) — match tool
       families against significant words in the goal.

    If none yield enough candidates, we top up with a few "generic"
    tools (web_search, web_browse) so the model always has something
    to fall back to.
    """
    if not all_tools:
        return all_tools

    candidates: list = []
    seen: set[str] = set()

    def _add(t):
        if t.name not in seen:
            candidates.append(t)
            seen.add(t.name)

    # ── 1. ACTION_KEYWORDS boost (highest priority — adds in head) ──
    boost_text = f"{goal} {current_step_desc}".strip()
    for t in _boost_by_action_keywords(boost_text, all_tools):
        _add(t)
    if candidates:
        logger.info("act: ACTION_KEYWORDS boosted %d tools: %s",
                    len(candidates), [t.name for t in candidates])

    if tool_hint:
        hint_low = tool_hint.lower()
        # Try exact match first
        for t in all_tools:
            if t.name == tool_hint:
                _add(t)
        # Then prefix match (e.g. weather_ → weather_get, weather_forecast)
        prefix = hint_low.split("_")[0] if "_" in hint_low else hint_low
        for t in all_tools:
            if t.name.lower().startswith(prefix):
                _add(t)
        # Then substring match (broader)
        if prefix and len(prefix) >= 4:
            for t in all_tools:
                if prefix in t.name.lower() or prefix in (t.description or "").lower()[:200]:
                    _add(t)

    # Keyword extraction from goal — pick significant nouns
    if len(candidates) < 10:
        goal_low = goal.lower()
        # Common ELY tool families to keyword-match
        FAMILY_KEYWORDS = {
            "weather":  ["météo", "meteo", "weather", "temperature", "pluie", "soleil"],
            "news":     ["news", "actualité", "actualites", "info", "article"],
            "gmail":    ["mail", "email", "courrier", "boîte"],
            "calendar": ["agenda", "calendrier", "rendez-vous", "rdv", "réunion", "événement"],
            "drive":    ["drive", "fichier", "document", "doc", "dossier"],
            "tasks":    ["tâche", "tache", "todo", "task"],
            "web":      ["web", "internet", "site", "url", "page"],
            "ssh":      ["ssh", "serveur", "vps", "shell", "commande"],
            "translate":["traduis", "traduction", "translate"],
            "image":    ["image", "photo", "picture", "imagen", "dessin"],
        }
        for family, kws in FAMILY_KEYWORDS.items():
            if any(kw in goal_low for kw in kws):
                for t in all_tools:
                    if family in t.name.lower():
                        _add(t)

    # Top up with generic must-haves so we always have a safety net
    GENERIC = {"web_search", "web_browse", "smart_knowledge_query"}
    for t in all_tools:
        if t.name in GENERIC:
            _add(t)

    # Cap to avoid payload bloat (~15 tools handles 99% of cases)
    return candidates[:15] if candidates else all_tools[:15]


def _get_actor_llms(tool_hint: Optional[str] = None, goal: str = "", current_step_desc: str = "") -> tuple[Any, list[tuple[str, Any]], list[Any]]:
    """Return (primary_llm_bound, [(label, fallback_llm_bound)], raw_tools).

    `primary` is the local model (xLAM-2-8B or Gemma 4 21B REAP) — fast
    and free but smaller models choke on too many tool schemas in the
    bind payload. We pre-filter via `_filter_tools_for_step` so the
    model only sees ≤15 tools relevant to the current step.

    `fallbacks` are cloud LLMs (Gemini, Claude Haiku) — handle larger
    tool sets reliably but cost API credits.

    We DON'T pass `tool_choice="any"` at bind-time because Gemini's
    bind_tools handles it as a sticky kwarg that interferes with
    serialization (raises "tool_choice but no formatted_tools" at invoke
    time on some provider versions). The prompt instead instructs the
    model to emit a tool_call.
    """
    from app.services.llm_provider import get_llm_for_tier, get_fallback_llms, ComplexityTier
    from app.skills import get_skill_registry

    all_tools = get_skill_registry().all_tools
    tools = _filter_tools_for_step(all_tools, tool_hint, goal, current_step_desc)
    logger.info("act: filtered %d → %d tools (hint=%s, step=%r)",
                len(all_tools), len(tools), tool_hint, current_step_desc[:60])

    primary = get_llm_for_tier(ComplexityTier.MEDIUM)
    primary_bound = primary.bind_tools(tools)

    fallbacks_bound = [(label, fb.bind_tools(tools)) for label, fb in get_fallback_llms()]
    return primary_bound, fallbacks_bound, tools


def _get_evaluator_llm():
    """LLM used for eval — judgment, no tools."""
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier
    return get_llm_for_tier(ComplexityTier.MEDIUM)


def _strip_json_fence(raw: str) -> str:
    """LLMs often wrap JSON in ```json …``` blocks. Strip them."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Drop the opening fence and any "json" tag
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


# ── plan_node ────────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """Tu es un planificateur d'agent IA. L'utilisateur te confie un objectif (goal) à atteindre.
Décompose-le en une suite d'étapes ATOMIQUES, chacune réalisable par UN seul appel d'outil.

Réponds STRICTEMENT en JSON, sans texte autour, au format suivant :
{
  "steps": [
    {"id": "1", "description": "...", "tool_hint": "<nom_outil_pressenti_ou_null>"},
    {"id": "2", "description": "...", "tool_hint": "..."}
  ],
  "estimated_iterations": <int>
}

Règles :
- Chaque "description" doit être ce que l'agent doit FAIRE à cette étape (pas ce qu'il doit savoir).
- "tool_hint" peut être null si tu ne sais pas quel outil utiliser.
- Maximum 8 étapes. Si le goal demande plus, regroupe.
- Les étapes seront exécutées en ORDRE séquentiel.
- N'invente pas d'outils — si tu ne connais pas un outil, mets null."""


async def plan_node(state: MissionState) -> dict:
    """Build (or refresh) the plan for the mission.

    First iteration → builds plan v1 from the goal.
    Subsequent iterations → no-op (plan was built in v1; replan_node updates it).
    """
    mission_id = state["mission_id"]
    user_id = state["user_id"]
    goal = state["goal"]
    iteration = state.get("iteration", 0) + 1
    plan_version = state.get("plan_version", 0)

    # Already planned → just bump iteration counter
    if plan_version > 0:
        logger.info("[mission %s] plan: existing v%d, skipping (iter=%d)", mission_id, plan_version, iteration)
        return {"iteration": iteration}

    # Generate v1 plan
    t0 = time.monotonic()
    llm = _get_planner_llm()
    messages: list[BaseMessage] = [
        SystemMessage(content=_PLAN_SYSTEM),
        HumanMessage(content=f"Goal de l'utilisateur :\n\n{goal}"),
    ]
    response = await llm.ainvoke(messages)
    await _log_mission_llm_usage(response, state["user_id"], mission_id, "plan", llm)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    # Parse JSON
    try:
        plan_json = json.loads(_strip_json_fence(raw))
        steps = plan_json.get("steps", [])
    except Exception as exc:
        logger.warning("[mission %s] plan: JSON parse failed (%s) — using fallback", mission_id, exc)
        plan_json = {"steps": [{"id": "1", "description": goal[:200], "tool_hint": None}]}
        steps = plan_json["steps"]

    # Render markdown for human readability
    plan_text = "# Plan v1\n\n" + "\n".join(
        f"- [ ] **{s.get('id','?')}** {s.get('description','?')}"
        + (f"  *(outil envisagé : `{s.get('tool_hint')}`)*" if s.get("tool_hint") else "")
        for s in steps
    )

    # Persist
    await mission_service.add_plan(mission_id, plan_text=plan_text, plan_json=plan_json)
    await mission_service.add_step(
        mission_id, phase="plan",
        thought=raw[:2000],
        evaluation=f"Plan v1 généré ({len(steps)} étapes)",
        success=True,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )
    logger.info("[mission %s] plan: v1 with %d steps (%.1fs)", mission_id, len(steps), elapsed_ms / 1000)

    return {
        "iteration": iteration,
        "plan_version": 1,
        "plan_text": plan_text,
        "plan_json": plan_json,
        "consecutive_failures": 0,
    }


# ── act_node ─────────────────────────────────────────────────────────────────

_ACT_SYSTEM = """Tu es l'agent ELY exécutant une mission. Voici le plan en cours :

{plan_text}

Étape courante à exécuter : « {current_step_desc} »

Choisis UN outil disponible dans ton inventaire pour avancer sur cette étape.
Émets UN SEUL appel d'outil. Tu ne dois pas répondre en texte — uniquement émettre un tool_call.
Si aucun outil ne semble adapté, choisis l'outil qui s'en rapproche le plus.

⚠️ RÈGLE CRITIQUE — REMPLISSAGE DES PARAMÈTRES :
Si l'étape consiste à COMBINER, ENVOYER, RÉSUMER ou TRANSMETTRE des données
issues des étapes précédentes, tu DOIS utiliser les VRAIES VALEURS retournées
par les tools précédents (visibles dans le contexte ci-dessous).
N'écris JAMAIS de placeholders comme [meteo_data], [email_summary],
[INSERT_X_HERE], <data>, {{value}}, etc. dans les arguments du tool.
Lis le contexte « OUTPUTS DES ÉTAPES PRÉCÉDENTES » et copie/résume les vraies
données dedans avant de remplir les arguments."""


async def _load_recent_step_outputs(mission_id: str, max_steps: int = 8, max_chars: int = 1200) -> str:
    """Render the last N successful tool outputs as a context block.

    Used to give the actor LLM access to the data produced by previous
    steps so it can fill `telegram_send_message(text=...)` with the real
    weather string, email list, etc. — instead of hallucinating placeholders.

    Caps each output at `max_chars` to keep the prompt tight (some tool
    outputs are huge, e.g. RAG queries with 10 chunks).
    """
    from app.database import async_session
    from app.models.mission import MissionStep
    from sqlalchemy import select, desc as _desc

    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(MissionStep)
                .where(
                    MissionStep.mission_id == mission_id,
                    MissionStep.phase == "act",
                    MissionStep.success == True,  # noqa: E712
                    MissionStep.tool_output.isnot(None),
                )
                .order_by(_desc(MissionStep.iteration))
                .limit(max_steps)
            )).scalars().all()
    except Exception as exc:
        logger.debug("Could not load recent step outputs: %s", exc)
        return ""

    if not rows:
        return ""

    # Reverse so we present them in chronological order (most recent last,
    # matching how a human would think of "the data so far").
    rows_chrono = list(reversed(rows))
    blocks: list[str] = []
    for s in rows_chrono:
        out = (s.tool_output or "").strip()
        if not out:
            continue
        if len(out) > max_chars:
            out = out[:max_chars] + " […tronqué]"
        thought = (s.thought or "").strip()
        # Strip the leading "Étape « ... »" prefix from the thought to
        # avoid duplication with the iter header.
        if thought.startswith("Étape «"):
            thought = ""
        header = f"[iter={s.iteration}] {s.tool_name or '?'}"
        blocks.append(f"{header}\n{out}")

    if not blocks:
        return ""
    return (
        "OUTPUTS DES ÉTAPES PRÉCÉDENTES (à utiliser tels quels pour remplir "
        "les arguments du prochain tool — JAMAIS de placeholder) :\n\n"
        + "\n\n---\n\n".join(blocks)
    )


def _next_pending_step(plan_json: Optional[dict]) -> Optional[dict]:
    """Return the first step with status != 'done' (or no status)."""
    if not plan_json:
        return None
    for s in plan_json.get("steps", []):
        if s.get("status") not in {"done", "skipped"}:
            return s
    return None


async def act_node(state: MissionState) -> dict:
    """Pick a tool via LLM, dispatch it, capture the result."""
    mission_id = state["mission_id"]
    user_id = state["user_id"]
    plan_json = state.get("plan_json") or {}
    plan_text = state.get("plan_text", "")

    current_step = _next_pending_step(plan_json)
    if not current_step:
        # No pending steps → nothing to do, treat as done
        logger.info("[mission %s] act: no pending step — marking done", mission_id)
        return {
            "last_eval_success": True,
            "done": True,
            "final_summary": "Toutes les étapes du plan sont terminées.",
        }

    current_step_id = current_step.get("id", "?")
    current_step_desc = current_step.get("description", "?")
    current_tool_hint = current_step.get("tool_hint")

    # Build prompt and invoke primary tool-bound LLM, with fallback.
    # Tool list is pre-filtered to ~15 tools max (smaller models choke on
    # 76 simultaneous tool schemas — payload too big for LM Studio etc.)
    primary_llm, fallbacks, _tools = _get_actor_llms(
        tool_hint=current_tool_hint,
        goal=state.get("goal", ""),
        current_step_desc=current_step_desc,
    )

    # Load outputs of previous successful tool invocations so the LLM can
    # fill arguments with REAL values (fix #19, May 2026 — agent was sending
    # "[meteo_data]" placeholders to telegram_send_message because it had no
    # context window into what weather_get had returned earlier in the run).
    prev_context = await _load_recent_step_outputs(mission_id)

    messages: list[BaseMessage] = [
        SystemMessage(content=_ACT_SYSTEM.format(plan_text=plan_text, current_step_desc=current_step_desc)),
        HumanMessage(content=f"Goal : {state.get('goal','?')}"),
    ]
    if prev_context:
        messages.append(HumanMessage(content=prev_context))

    t0 = time.monotonic()
    response = None
    tool_calls = []
    model_used = "medium-tier (primary)"
    try:
        response = await primary_llm.ainvoke(messages)
        await _log_mission_llm_usage(response, state["user_id"], mission_id, "act", primary_llm)
        tool_calls = getattr(response, "tool_calls", []) or []
    except Exception as exc:
        # Known MLX limitation : Gemma 4 21B REAP-4bit + 76 tools bound
        # → "RotatingKVCache Quantization NYI". Fallthrough to Gemini.
        logger.warning("[mission %s] act: primary LLM raised %s — falling back", mission_id, type(exc).__name__)
        response = None

    # Fallback if primary didn't emit a tool_call OR raised. Typical for
    # Gemma 4 21B REAP : either crashes on tool binding (MLX bug) or
    # silently returns text (tool_choice ignored). Try each fallback
    # until one returns ≥1 tool_call. Mirrors chat-mode pattern in
    # app/agent/sub_agents/factory.py.
    if not tool_calls:
        logger.warning(
            "[mission %s] act: primary LLM emitted 0 tool_calls — falling back",
            mission_id,
        )
        for label, fb_llm in fallbacks:
            try:
                t_fb = time.monotonic()
                response = await fb_llm.ainvoke(messages)
                await _log_mission_llm_usage(response, state["user_id"], mission_id, "act_fallback", fb_llm)
                tool_calls = getattr(response, "tool_calls", []) or []
                logger.warning(
                    "[mission %s] act.fallback %.1fs %s → tool_calls=%d",
                    mission_id, time.monotonic() - t_fb, label, len(tool_calls),
                )
                if tool_calls:
                    model_used = f"medium-tier (fallback {label})"
                    break
            except Exception as exc:
                logger.warning("[mission %s] act.fallback %s failed: %s", mission_id, label, exc)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if not tool_calls:
        # All providers refused to emit a tool call — count as iteration failure
        thought_txt = ""
        if response is not None:
            thought_txt = getattr(response, "content", "") or "(no content)"
        await mission_service.add_step(
            mission_id, phase="act",
            thought=thought_txt or "(primary crashed, fallbacks exhausted)",
            evaluation="Aucun LLM n'a émis de tool_call (primary + fallbacks épuisés)",
            success=False,
            duration_ms=elapsed_ms,
            model_used=model_used,
        )
        return {
            "current_step_id": current_step_id,
            "last_eval_success": False,
            "last_eval_reason": "Aucun outil sélectionné — tous les LLM ont retourné du texte.",
            "consecutive_failures": state.get("consecutive_failures", 0) + 1,
        }

    # Take only the first tool call (one action per tick)
    call = tool_calls[0]
    tool_name = call["name"]
    tool_args = dict(call.get("args") or {})
    tool_id = call.get("id", "act-" + mission_id[:6])

    output, ok = await dispatch_tool(
        tool_name, tool_args, tool_id, user_id,
        user_request=state.get("goal", ""),
    )

    # Persist audit row
    await mission_service.add_step(
        mission_id, phase="act",
        thought=f"Étape « {current_step_desc} »",
        tool_name=tool_name,
        tool_input={k: v for k, v in tool_args.items() if k not in {"user_google_credentials_json", "user_id"}},
        tool_output=output[:5000],
        success=ok,
        duration_ms=elapsed_ms,
        model_used=model_used,
    )
    logger.info(
        "[mission %s] act: tool=%s ok=%s (%.1fs) step=%s",
        mission_id, tool_name, ok, elapsed_ms / 1000, current_step_id,
    )

    return {
        "current_step_id": current_step_id,
        "last_tool_name": tool_name,
        "last_tool_input": tool_args,
        "last_tool_output": output,
        # IMPORTANT : clear stale eval flags from the previous tick so
        # `eval_node` runs fresh on this iteration. Without this, the
        # checkpointer-restored `last_eval_success=False` would short-circuit
        # eval and `consecutive_failures` would never bump → replan dead.
        "last_eval_success": None,
        "last_eval_reason": None,
    }


# ── eval_node ────────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """Tu es l'évaluateur strict de l'agent ELY. Voici le contexte d'une étape qui vient d'être exécutée :

Goal global de la mission : {goal}
Étape exécutée : « {step_desc} »
Outil utilisé : {tool_name}
Résultat brut de l'outil :
---
{tool_output}
---

Tu réponds STRICTEMENT en JSON :
{{
  "success": true|false,
  "reason": "<une phrase max>",
  "all_done": true|false
}}

DÉFINITIONS PRÉCISES (lis-les avant de répondre) :

- "success" = l'étape qui vient de tourner s'est techniquement bien passée
  (pas d'erreur, pas d'exception, le tool a renvoyé un résultat plausible)
  ET l'outil utilisé est COMPATIBLE avec le type d'étape.

  La cohérence outil ↔ étape dépend du TYPE de l'étape. On distingue 3 types :

  1️⃣ ÉTAPE MUTATIVE (modifie le système — verbes : SUPPRIMER, ENVOYER, CRÉER,
     PARTAGER, EFFACER, MODIFIER, DÉPLACER, ENVOIE, POSTE, PUBLIE, etc.)
     → STRICT : l'outil DOIT être un outil mutatif correspondant.
       - étape "Supprime les spams" + tool gmail_trash_by_category → success=true ✅
       - étape "Supprime les spams" + tool gmail_search           → success=FALSE ❌
         (search ne supprime pas — il faut replan vers gmail_trash_emails)
       - étape "Envoie le résumé"   + tool gmail_send_email       → success=true ✅
       - étape "Envoie le résumé"   + tool gmail_list_emails      → success=FALSE ❌

  2️⃣ ÉTAPE DE LECTURE (récupère de l'info — verbes : LISTER, CHERCHER, RÉCUPÉRER,
     LIRE, CONSULTER, OBTENIR, FETCH, GET, VOIR)
     → SOUPLE : un outil list/search/read/get est cohérent.
       - étape "Liste mes emails non lus" + tool gmail_list_emails → success=true ✅
       - étape "Récupère la météo"        + tool weather_get        → success=true ✅

  3️⃣ ÉTAPE DE SYNTHÈSE / ANALYSE (le LLM raisonne sur les données — verbes :
     RÉSUMER, ANALYSER, COMPARER, CONCLURE, FORMATER, REFORMULER, IDENTIFIER,
     EXTRAIRE, DÉCRIRE, EXPLIQUER, FAIRE UN RÉSUMÉ, FAIRE LE BILAN)
     → TRÈS SOUPLE : l'outil n'a pas à matcher le verbe de synthèse, parce
       qu'il N'EXISTE PAS d'outil "résume" ou "analyse" dédié — le LLM
       produit la synthèse directement à partir du contexte (output du step
       précédent ou raisonnement interne).
       - étape "Résume les emails listés" + tool gmail_list_emails → success=true ✅
         (le LLM a relu la liste et est censé produire le résumé en sortie)
       - étape "Résume les emails listés" + AUCUN tool appelé      → success=true ✅
         (le LLM a tout fait dans son raisonnement, c'est OK)
       - étape "Analyse mon agenda"       + tool calendar_list_events → success=true ✅
       - étape "Compare A et B"           + tool web_search           → success=true ✅
       NE JAMAIS retourner FALSE pour « l'outil ne fait pas de résumé/analyse » :
       cette analyse incombe au LLM, pas au tool.

  Règle simple : ne mets success=FALSE QUE si l'étape est MUTATIVE (catégorie 1)
  et que l'outil ne change PAS l'état du système. Les étapes de lecture et de
  synthèse sont toujours validées tant que le tool a réussi techniquement.

- "all_done" = ⚠️ TRÈS STRICT ⚠️ — vrai UNIQUEMENT si l'EFFET RÉEL ATTENDU
  par le goal global est CONCRÈTEMENT réalisé sur le système cible.
  PAS « toutes les étapes du plan sont done ». PAS « j'ai préparé / identifié /
  listé les IDs ». MAIS « l'état du système a changé conformément au goal ».

  Test mental obligatoire :
    1. Relis le goal global au mot près.
    2. Pose-toi : « si je vérifiais le système maintenant, le résultat
       observable correspondrait-il à ce que demande le goal ? »
    3. Si OUI → all_done=true. Si NON, ou si tu n'es pas SÛR → all_done=false.

  Exemples qui ÉCLAIRENT :

  Goal : « Supprime tous les emails du dossier SPAM »
  - Étape : gmail_search retourne 50 IDs SPAM
    → success=true, all_done=FALSE (les emails ne sont pas encore supprimés)
  - Étape suivante : gmail_trash_emails(ids=[...50...]) retourne « 50 trashed »
    → success=true, all_done=TRUE (la corbeille est faite)

  Goal : « Envoie chaque matin un résumé IA à mon adresse »
  - Étape : web_search_news retourne 10 articles
    → success=true, all_done=FALSE (le mail n'est pas envoyé)
  - Étape suivante : gmail_send_email retourne un message_id
    → success=true, all_done=TRUE

  Goal : « Crée un dossier Q3-budget dans Drive et partage-le avec alice »
  - Étape : drive_create_folder retourne un folder_id
    → success=true, all_done=FALSE (pas encore partagé)
  - Étape suivante : drive_share_file(role=writer) retourne success
    → success=true, all_done=TRUE

  En cas de DOUTE : all_done=false. Une mission marquée « accomplie » alors
  que rien n'a été fait sur le système est un BUG GRAVE — on préfère
  toujours laisser le planner replan une étape de plus."""


async def eval_node(state: MissionState) -> dict:
    """Judge the last action's success and update step status in plan."""
    mission_id = state["mission_id"]
    plan_json = state.get("plan_json") or {}
    current_step_id = state.get("current_step_id")

    # If act_node already concluded (mission done or unrecoverable in-tick failure)
    if state.get("done"):
        return {}
    # If act_node concluded a failure in THIS tick (e.g. no tool_call),
    # `last_tool_name` will be None but `last_eval_reason` will be set.
    # Note : act_node clears stale eval flags at entry so checkpointed
    # values from past ticks don't trigger this branch.
    if state.get("last_eval_success") is False and state.get("last_eval_reason") and not state.get("last_tool_name"):
        return {}

    # No action was taken — nothing to evaluate
    if not state.get("last_tool_name"):
        return {"last_eval_success": True, "last_eval_reason": "no-op iteration"}

    t0 = time.monotonic()
    llm = _get_evaluator_llm()
    current_step = next(
        (s for s in plan_json.get("steps", []) if s.get("id") == current_step_id),
        {"description": "?"},
    )

    prompt = _EVAL_SYSTEM.format(
        goal=state.get("goal", "?"),
        step_desc=current_step.get("description", "?"),
        tool_name=state.get("last_tool_name", "?"),
        tool_output=(state.get("last_tool_output", "") or "")[:2000],
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    await _log_mission_llm_usage(response, state["user_id"], mission_id, "eval", llm)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    try:
        verdict = json.loads(_strip_json_fence(raw))
        success = bool(verdict.get("success", False))
        reason = str(verdict.get("reason", ""))[:500]
        all_done = bool(verdict.get("all_done", False))
    except Exception as exc:
        logger.warning("[mission %s] eval: JSON parse failed (%s) — assuming success", mission_id, exc)
        success, reason, all_done = True, "Parse failed, assumed success", False

    # Mutate plan_json to mark step done/failed
    new_plan_json = dict(plan_json)
    new_steps = []
    for s in new_plan_json.get("steps", []):
        if s.get("id") == current_step_id:
            s = dict(s)
            s["status"] = "done" if success else "failed"
        new_steps.append(s)
    new_plan_json["steps"] = new_steps

    # Persist
    await mission_service.add_step(
        mission_id, phase="eval",
        evaluation=reason,
        success=success,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )

    failures = state.get("consecutive_failures", 0)
    new_failures = 0 if success else failures + 1

    # CRITICAL : we now ONLY trust the LLM's `all_done` verdict, not "no
    # pending steps left". Reason : the planner can produce an incomplete
    # plan (e.g. "list IDs" without the matching "delete IDs" step), and
    # the legacy heuristic (success && no pending) would mark the mission
    # complete even though the goal wasn't reached. The hardened evaluator
    # prompt above pushes the LLM to compare the SYSTEM EFFECT to the
    # GOAL, not just the step list.
    # If `all_done=false` but the plan has no pending step, the next
    # iteration falls into replan_node which will add the missing steps.
    is_done = all_done

    out: dict = {
        "last_eval_success": success,
        "last_eval_reason": reason,
        "consecutive_failures": new_failures,
        "plan_json": new_plan_json,
    }
    if is_done:
        out["done"] = True
        out["final_summary"] = f"Mission accomplie. Dernière étape : {reason}"

    logger.info(
        "[mission %s] eval: success=%s done=%s consec_failures=%d",
        mission_id, success, is_done, new_failures,
    )
    return out


# ── replan_node ──────────────────────────────────────────────────────────────

_REPLAN_SYSTEM = """Tu es le replanificateur de l'agent ELY. La stratégie actuelle a échoué plusieurs fois.

Goal initial : {goal}

Plan actuel (qui ne fonctionne pas) :
{plan_text}

Dernière tentative qui a échoué :
- Outil : {last_tool}
- Sortie : {last_output}
- Raison de l'échec : {last_reason}

Produis un NOUVEAU plan, différent du précédent, qui contourne ce blocage.
Réponds STRICTEMENT en JSON :
{{
  "reason_for_replan": "<une phrase>",
  "steps": [
    {{"id": "1", "description": "...", "tool_hint": "..."}},
    ...
  ]
}}"""


async def replan_node(state: MissionState) -> dict:
    """Build a new plan version after consecutive failures."""
    mission_id = state["mission_id"]
    new_version = state.get("plan_version", 1) + 1

    t0 = time.monotonic()
    llm = _get_planner_llm()
    prompt = _REPLAN_SYSTEM.format(
        goal=state.get("goal", "?"),
        plan_text=state.get("plan_text", "(plan vide)"),
        last_tool=state.get("last_tool_name", "(aucun)"),
        last_output=(state.get("last_tool_output", "") or "")[:1000],
        last_reason=state.get("last_eval_reason", "(non spécifié)"),
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    await _log_mission_llm_usage(response, state["user_id"], mission_id, "replan", llm)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = getattr(response, "content", "") or ""

    try:
        new_plan = json.loads(_strip_json_fence(raw))
        steps = new_plan.get("steps", [])
        reason = new_plan.get("reason_for_replan", "Plan révisé suite à échecs répétés")
    except Exception as exc:
        logger.warning("[mission %s] replan: JSON parse failed (%s)", mission_id, exc)
        steps = state.get("plan_json", {}).get("steps", [])
        reason = f"Replan parsing failed: {exc}"

    plan_text = f"# Plan v{new_version}\n\n*Raison du replan :* {reason}\n\n" + "\n".join(
        f"- [ ] **{s.get('id','?')}** {s.get('description','?')}"
        + (f"  *(outil envisagé : `{s.get('tool_hint')}`)*" if s.get("tool_hint") else "")
        for s in steps
    )

    plan_json = {"steps": steps, "estimated_iterations": new_plan.get("estimated_iterations", len(steps))}

    await mission_service.add_plan(
        mission_id, plan_text=plan_text, plan_json=plan_json, reason_for_replan=reason,
    )
    await mission_service.add_step(
        mission_id, phase="replan",
        thought=raw[:2000],
        evaluation=reason,
        success=True,
        duration_ms=elapsed_ms,
        model_used="medium-tier",
    )
    logger.info("[mission %s] replan: v%d with %d steps (%.1fs)", mission_id, new_version, len(steps), elapsed_ms / 1000)

    return {
        "plan_version": new_version,
        "plan_text": plan_text,
        "plan_json": plan_json,
        "consecutive_failures": 0,
    }
