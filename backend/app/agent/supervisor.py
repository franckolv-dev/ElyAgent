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

Domain = Literal["research", "workspace", "infra", "general"]

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
    "general": (
        "Requête complexe impliquant plusieurs domaines à la fois, ou ne "
        "correspondant clairement à aucune catégorie unique."
    ),
}

_ROUTER_SYSTEM = """Tu es le routeur d'ELY. Ton unique rôle est de classifier la demande de l'utilisateur
dans l'une des quatre catégories suivantes, sans l'exécuter.

Catégories disponibles :
- research   : {research}
- workspace  : {workspace}
- infra      : {infra}
- general    : {general}

Réponds UNIQUEMENT avec le nom de la catégorie en minuscules (research / workspace / infra / general).
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
        "(HITL), calendar_list_events, calendar_create_event (HITL), drive_list_files, "
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
        if domain not in ("research", "workspace", "infra", "general"):
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
# Routing conditional
# ──────────────────────────────────────────────────────────────────────────────

def route_after_router(state: AgentState) -> str:
    """Map the domain stored by router_node to the next graph node."""
    domain = state.get("domain", "general")
    return domain if domain in ("research", "workspace", "infra") else "general"


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
        router   → classifies intent
        research → specialist for web/weather/news/translate
        workspace → specialist for Google Workspace
        infra    → specialist for SSH/cron/watchdog/briefing
        general  → full-tool fallback
        tools    → shared tool execution node

    Edges:
        router → {research, workspace, infra, general}
        research/workspace/infra/general → {tools, end}
        tools → {research, workspace, infra, general}  (loop back to caller)
    """
    # AgentState needs a "domain" field for routing
    from app.agent.state import AgentState

    graph = StateGraph(AgentState)

    # ── Nodes ──
    graph.add_node("router", router_node)
    graph.add_node("research", create_specialist_node("research"))
    graph.add_node("workspace", create_specialist_node("workspace"))
    graph.add_node("infra", create_specialist_node("infra"))
    graph.add_node("general", create_agent_node())
    graph.add_node("tools", tool_node)

    # ── Entry point ──
    graph.set_entry_point("router")

    # ── Router → specialists ──
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "research": "research",
            "workspace": "workspace",
            "infra": "infra",
            "general": "general",
        },
    )

    # ── Specialists → tools or end ──
    for specialist in ("research", "workspace", "infra"):
        graph.add_conditional_edges(
            specialist,
            should_continue_specialist,
            {"tools": "tools", "end": END},
        )

    # ── General agent → tools or end (reuses existing should_continue) ──
    from app.agent.nodes import should_continue
    graph.add_conditional_edges(
        "general",
        should_continue,
        {"tools": "tools", "end": END},
    )

    # ── Tools → back to the specialist that called them ──
    # We route based on the domain stored in state
    graph.add_conditional_edges(
        "tools",
        route_after_router,  # reads state["domain"] to know which specialist to return to
        {
            "research": "research",
            "workspace": "workspace",
            "infra": "infra",
            "general": "general",
        },
    )

    return graph.compile()
