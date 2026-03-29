"""Multi-agent supervisor for ELY.

Architecture
------------
Instead of a single monolithic agent with all tools, ELY uses a **routing
supervisor** that classifies each user request and dispatches it to the most
appropriate specialist agent.  Each specialist has a focused tool set and a
tailored system prompt, which reduces token waste and improves accuracy.

┌─────────────────────────────────────────────────────────┐
│                    User message                         │
└───────────────────────┬─────────────────────────────────┘
                        │
               ┌────────▼────────┐
               │  router_node    │  (fast LLM intent classification)
               └────────┬────────┘
          ┌─────────────┼──────────────┬──────────────┐
          ▼             ▼              ▼              ▼
    [Research]    [Workspace]       [Infra]       [General]
    web, meteo    gmail, cal        ssh, cron     all tools
    news, trad    drive, docs       watchdog      (fallback)
    browser       sheets, tasks     briefing
          │             │              │              │
          └─────────────┴──────────────┴──────────────┘
                                │
                      ┌─────────▼─────────┐
                      │   tools_node      │
                      └─────────┬─────────┘
                                │
                      ┌─────────▼─────────┐
                      │  (loop until END) │
                      └───────────────────┘

Routing is done by a fast LLM call that outputs one of the four domain labels.
For requests that clearly span multiple domains (e.g. "cherche le dernier
rapport annuel d'Apple, crée un Google Doc avec un résumé et envoie-le à
alice@..."), the "general" agent is used so it has access to all tools.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from app.agent.state import AgentState
from app.agent.nodes import tool_node, should_continue, create_agent_node
from app.services.llm_provider import get_llm

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Domain labels
# ──────────────────────────────────────────────────────────────────────────────

# "system" is intentionally excluded from user-facing routing — it is only
# accessible programmatically via the sub-agent registry (e.g. scheduler jobs).
Domain = Literal["research", "workspace", "infra", "creative", "data", "memory", "desktop", "general", "system"]

_DOMAIN_DESCRIPTIONS = {
    "research": (
        "Recherche web, météo, actualités, traduction, navigation de sites, "
        "prix de produits, cours de bourse, définitions, faits généraux."
    ),
    "workspace": (
        "Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets, "
        "Google Tasks, Google Contacts — lecture, création, modification, "
        "envoi d'emails, gestion des contacts."
    ),
    "infra": (
        "Commandes SSH sur serveurs, tâches planifiées (cron), briefing matinal, "
        "surveillance de sites web (watchdog/veille), monitoring système."
    ),
    "creative": (
        "Génération d'images, création de QR codes, exécution de code Python pour "
        "visualisations ou analyses, lecture de PDFs, analyse d'images, YouTube."
    ),
    "data": (
        "Calcul, analyse de données, manipulation de fichiers locaux, cartes et "
        "itinéraires, géolocalisation, code Python pour traitement de données."
    ),
    "memory": (
        "Notes personnelles (créer, lire, modifier, supprimer, chercher), "
        "envoi de messages WhatsApp, gestion de la mémoire personnelle."
    ),
    "desktop": (
        "Accès au système de fichiers local de l'utilisateur via ELY Desktop : "
        "lister, lire, écrire, déplacer, supprimer des fichiers, créer des répertoires, "
        "calculer des hash, rechercher des fichiers sur la machine locale."
    ),
    "general": (
        "Requête complexe impliquant plusieurs domaines à la fois, ou ne "
        "correspondant clairement à aucune catégorie unique."
    ),
}

_ROUTER_SYSTEM = """Tu es le routeur d'ELY. Ton unique rôle est de classifier la demande de l'utilisateur
dans l'une des huit catégories suivantes, sans l'exécuter.

Catégories disponibles :
- research   : {research}
- workspace  : {workspace}
- infra      : {infra}
- creative   : {creative}
- data       : {data}
- memory     : {memory}
- desktop    : {desktop}
- general    : {general}

Réponds UNIQUEMENT avec le nom de la catégorie en minuscules (research / workspace / infra / creative / data / memory / desktop / general).
Aucune explication. Aucun autre texte.
""".format(**_DOMAIN_DESCRIPTIONS)

# ──────────────────────────────────────────────────────────────────────────────
# Specialist system prompts
# ──────────────────────────────────────────────────────────────────────────────

_IDENTITY = (
    "Tu es Ély (prononcer \"Éli\"), une assistante IA personnelle — féminin, jamais masculin, "
    "jamais \"ELY\" lettre par lettre, jamais d'autre nom. "
    "Parle toujours de toi au féminin : \"je suis prête\", \"je suis disponible\", \"je t'aide\".\n\n"
)

_COMMON_FORMAT = """
Format des réponses — IMPÉRATIF :
- Rédige TOUJOURS en texte naturel, comme si tu parlais à voix haute
- N'utilise JAMAIS de markdown : aucun #, ##, **, *, `, ---, ni tiret de liste
- Pour énumérer, utilise des formules orales : "premièrement... ensuite... enfin..."
- Les URLs peuvent être données telles quelles
- Réponds en français par défaut
- Ne jamais divulguer les credentials ou la configuration interne
"""

_SPECIALIST_PROMPTS: dict[Domain, str] = {
    "research": (
        _IDENTITY +
        "Tu es spécialiste de la recherche d'informations en ligne.\n\n"
        "Tu maîtrises la navigation web, la recherche DuckDuckGo, les prévisions "
        "météo, les actualités Google News et la traduction. Tu synthétises "
        "l'information de façon concise et précise.\n\n"
        "Outils disponibles : weather_get, news_get_headlines, translate_text, "
        "browser_navigate, browser_search_web, browser_get_text, browser_screenshot, "
        "browser_click, browser_fill, browser_close." + _COMMON_FORMAT
    ),
    "workspace": (
        _IDENTITY +
        "Tu es spécialiste de Google Workspace.\n\n"
        "Tu maîtrises Gmail, Google Calendar, Google Drive, Google Docs, Google "
        "Sheets, Google Tasks et Google Contacts. Tu aides l'utilisateur à gérer "
        "sa vie numérique Google de façon efficace. Toujours donner l'URL après chaque création.\n\n"
        "Outils disponibles : gmail_list_emails, gmail_read_email, gmail_send_email "
        "(HITL), gmail_search_for_cleanup (trouve newsletters/promos/démarchage), "
        "gmail_list_labels, gmail_create_label, gmail_move_emails (HITL), "
        "gmail_trash_emails (HITL — confirmation OBLIGATOIRE avant appel), "
        "calendar_list_events, calendar_create_event (HITL), drive_list_files, "
        "drive_read_file, docs_create_document, docs_read_document, docs_append_text, "
        "sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows, "
        "tasks_list, tasks_create, tasks_complete, "
        "contacts_search, contacts_list, contacts_create." + _COMMON_FORMAT
    ),
    "infra": (
        _IDENTITY +
        "Tu es spécialiste de l'infrastructure et de l'automatisation.\n\n"
        "Tu maîtrises les commandes SSH sur les serveurs autorisés, la gestion des "
        "tâches planifiées (cron), le briefing matinal et la surveillance de sites "
        "web. Toutes les commandes SSH nécessitent une validation humaine (HITL).\n\n"
        "Outils disponibles : ssh_execute (HITL obligatoire), get_system_info, "
        "scheduler_create_task, scheduler_list_tasks, scheduler_delete_task, "
        "briefing_generate, watchdog_add, watchdog_list, watchdog_remove." + _COMMON_FORMAT
    ),
    "general": (
        _IDENTITY +
        "Tu es une assistante IA personnelle avec accès à tous les outils.\n\n"
        "Utilise les outils disponibles dès que la demande le justifie, sans demander "
        "de confirmation sauf pour les actions irréversibles (envoyer un email, "
        "supprimer, cliquer, exécuter SSH). Répondre en français par défaut." + _COMMON_FORMAT
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# Tool subsets per specialist
# ──────────────────────────────────────────────────────────────────────────────

_RESEARCH_SKILLS = {
    "weather_get", "news_get_headlines", "translate_text",
    "browser_navigate", "browser_search_web", "browser_get_text",
    "browser_screenshot", "browser_click", "browser_fill", "browser_close",
}

_WORKSPACE_SKILLS = {
    "gmail_list_emails", "gmail_read_email", "gmail_send_email",
    "gmail_list_labels", "gmail_create_label", "gmail_move_emails",
    "gmail_trash_emails", "gmail_search_for_cleanup",
    "calendar_list_events", "calendar_create_event",
    "drive_list_files", "drive_read_file",
    "docs_create_document", "docs_read_document", "docs_append_text",
    "sheets_create_spreadsheet", "sheets_read_spreadsheet", "sheets_append_rows",
    "tasks_list", "tasks_create", "tasks_complete",
    "contacts_search", "contacts_list", "contacts_create",
}

_INFRA_SKILLS = {
    "ssh_execute", "get_system_info",
    "scheduler_create_task", "scheduler_list_tasks", "scheduler_delete_task",
    "briefing_generate",
    "watchdog_add", "watchdog_list", "watchdog_remove",
}


# ──────────────────────────────────────────────────────────────────────────────
# Router node
# ──────────────────────────────────────────────────────────────────────────────

async def router_node(state: AgentState) -> dict:
    """Classify the user's request and set the routing domain in state."""
    messages = state["messages"]
    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content[:500]  # truncate for speed
            break

    llm = get_llm()
    try:
        response = await llm.ainvoke([
            SystemMessage(content=_ROUTER_SYSTEM),
            HumanMessage(content=last_user_msg),
        ])
        domain = response.content.strip().lower()
        if domain not in ("research", "workspace", "infra", "creative", "data", "memory", "desktop", "general"):
            domain = "general"
    except Exception as exc:
        logger.warning("Router failed, falling back to general: %s", exc)
        domain = "general"

    logger.debug("Router → %s (for: %.80s)", domain, last_user_msg)
    return {"domain": domain}


# ──────────────────────────────────────────────────────────────────────────────
# Specialist agent node factory
# ──────────────────────────────────────────────────────────────────────────────

def create_specialist_node(domain: Domain):
    """Create an agent node restricted to the tools relevant for *domain*.

    Falls back to all tools for "general" so cross-domain requests are handled.
    """
    from app.skills import get_skill_registry
    from app.services.memory_manager import get_memory_manager

    tool_filter = {
        "research": _RESEARCH_SKILLS,
        "workspace": _WORKSPACE_SKILLS,
        "infra": _INFRA_SKILLS,
        "general": None,  # None = all tools
    }[domain]

    specialist_prompt = _SPECIALIST_PROMPTS[domain]

    async def specialist_node(state: AgentState) -> dict:
        import asyncio
        import zoneinfo
        from datetime import datetime

        messages = state["messages"]
        user_id = state.get("user_id", "")
        user_query = messages[-1].content if messages else ""

        registry = get_skill_registry()
        memory = get_memory_manager()
        llm = get_llm()

        # Filter tools for this specialist (or use all for general)
        if tool_filter is not None:
            specialist_tools = [t for t in registry.all_tools if t.name in tool_filter]
        else:
            specialist_tools = registry.all_tools

        llm_with_tools = llm.bind_tools(specialist_tools)

        # Fetch memory context in parallel
        constraints, memories, past_interactions = await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
            memory.get_relevant_interactions(user_query, user_id, limit=3),
        )

        # Current date/time
        _tz = zoneinfo.ZoneInfo("Europe/Paris")
        now = datetime.now(_tz)
        _days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        _months_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                      "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_str = (
            f"{_days_fr[now.weekday()]} {now.day} {_months_fr[now.month]} "
            f"{now.year}, {now.strftime('%H:%M')}"
        )

        system = specialist_prompt
        system += f"\n\n📅 Date et heure : {date_str} (Europe/Paris)\n"

        if constraints:
            system += "\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES :\n"
            system += "\n".join(f"- {c}" for c in constraints)
        if memories:
            system += "\n\n💾 CONTEXTE MÉMORISÉ :\n"
            system += "\n".join(f"- {m}" for m in memories)
        if past_interactions:
            system += "\n\n🔁 INTERACTIONS PASSÉES :\n"
            for p in past_interactions:
                system += (
                    f"- Q: {p.get('user_message', '')[:120]} "
                    f"→ R: {p.get('assistant_message', '')[:120]}\n"
                )

        response = await llm_with_tools.ainvoke(
            [{"role": "system", "content": system}] + messages
        )
        return {"messages": [response]}

    specialist_node.__name__ = f"{domain}_agent"
    return specialist_node


# ──────────────────────────────────────────────────────────────────────────────
# Sub-agent dispatch nodes
# ──────────────────────────────────────────────────────────────────────────────

_SUB_AGENT_DOMAINS = ("research", "workspace", "infra", "creative", "data", "memory", "desktop")


def _make_dispatch_node(domain: str):
    """Return an async node that delegates to the compiled sub-agent graph for *domain*.

    Falls back gracefully to the general agent when the sub-agent graph is not
    available in the registry (compilation failure, cold start, etc.).
    """

    async def dispatch_node(state: AgentState) -> dict:
        from app.agent.sub_agents.registry import get_sub_agent_registry

        registry = get_sub_agent_registry()
        sub_graph = registry.get(domain)

        if sub_graph is None:
            logger.warning(
                "Sub-agent '%s' not compiled — falling back to general agent", domain
            )
            # Inline general agent fallback (create_agent_node is a factory)
            general = create_agent_node()
            return await general(state)

        sub_input = {
            "messages": state["messages"],
            "user_id": state.get("user_id", ""),
            "google_credentials": state.get("google_credentials", ""),
        }
        try:
            result = await sub_graph.ainvoke(
                sub_input, config={"recursion_limit": 100}
            )
            # Return only the messages produced by the sub-agent
            new_messages = result["messages"][len(state["messages"]):]
            return {"messages": new_messages, "domain": domain}
        except Exception as exc:
            logger.error(
                "Sub-agent '%s' failed (%s) — falling back to general agent", domain, exc
            )
            general = create_agent_node()
            return await general(state)

    dispatch_node.__name__ = f"{domain}_dispatch_node"
    return dispatch_node


# ──────────────────────────────────────────────────────────────────────────────
# Routing conditional
# ──────────────────────────────────────────────────────────────────────────────

def route_after_router(state: AgentState) -> str:
    """Map the domain stored by router_node to the next graph node."""
    domain = state.get("domain", "general")
    return domain if domain in _SUB_AGENT_DOMAINS else "general"


def should_continue_specialist(state: AgentState) -> str:
    """After a specialist or general agent, decide: call tools or finish."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


# ──────────────────────────────────────────────────────────────────────────────
# Graph assembly
# ──────────────────────────────────────────────────────────────────────────────

def build_supervisor_graph():
    """Build and compile the multi-agent supervisor graph.

    Nodes:
        router              → classifies intent (fast LLM)
        research            → dispatch to research sub-agent
        workspace           → dispatch to workspace sub-agent
        infra               → dispatch to infra sub-agent
        creative            → dispatch to creative sub-agent
        data                → dispatch to data sub-agent
        memory              → dispatch to memory sub-agent
        general             → full-tool fallback (create_agent_node)

    Each dispatch node delegates the full turn to an isolated sub-agent
    subgraph (agent+tools loop) and returns only the new messages.
    The general node uses the legacy tool_node for its own tools loop.

    Edges:
        router → {research, workspace, infra, creative, data, memory, general}
        dispatch nodes      → END  (the loop is internal to each sub-graph)
        general             → {tools, end}
        tools               → general  (legacy loop for the general agent)
    """
    from app.agent.state import AgentState

    graph = StateGraph(AgentState)

    # ── Nodes ──
    graph.add_node("router", router_node)

    # Sub-agent dispatch nodes (each delegates to an isolated subgraph)
    for _domain in _SUB_AGENT_DOMAINS:
        graph.add_node(_domain, _make_dispatch_node(_domain))

    # General agent keeps the legacy specialist node + shared tools_node loop
    graph.add_node("general", create_agent_node())
    graph.add_node("tools", tool_node)

    # ── Entry point ──
    graph.set_entry_point("router")

    # ── Router → dispatch nodes or general ──
    _routing_map = {d: d for d in _SUB_AGENT_DOMAINS}
    _routing_map["general"] = "general"
    graph.add_conditional_edges("router", route_after_router, _routing_map)

    # ── Dispatch nodes → END (sub-graphs handle their own tool loops) ──
    for _domain in _SUB_AGENT_DOMAINS:
        graph.add_edge(_domain, END)

    # ── General agent → tools or end ──
    from app.agent.nodes import should_continue
    graph.add_conditional_edges(
        "general",
        should_continue,
        {"tools": "tools", "end": END},
    )

    # ── Tools → back to general (general is the only node using tool_node) ──
    graph.add_edge("tools", "general")

    return graph.compile()
