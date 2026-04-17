# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/supervisor.py
# @brief      Multi-agent supervisor for ELY
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
from app.services.llm_provider import get_llm, get_llm_for_tier, ComplexityTier

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
        "envoi d'emails, gestion des contacts. Accès complet aux APIs "
        "(batchUpdate, raw_api_call) : tri/insertion/formatage Sheets, "
        "styles Docs, partage/export Drive, Meet/récurrence Calendar, "
        "modif en lot Gmail, opérations bulk Contacts."
    ),
    "infra": (
        "Commandes SSH sur serveurs, tâches planifiées (cron), briefing matinal, "
        "surveillance de sites web (watchdog/veille), monitoring système. "
        "Aussi : informations sur la machine locale, le poste de travail, les specs "
        "matérielles, la RAM, le CPU, l'OS, l'espace disque, la version Python, "
        "l'architecture du système. Exemples : 'infos système', 'specs de la machine', "
        "'donne-moi les informations sur ce système', 'quel est l'OS', 'quelle RAM'."
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
        "envoi de messages WhatsApp, gestion de la mémoire personnelle, "
        "recherche dans la base de connaissances (documents indexés par l'utilisateur)."
    ),
    "desktop": (
        "Tout ce qui implique le bureau ou la machine locale de l'utilisateur : "
        "démonstrations interactives (montrer comment faire quelque chose, tutoriels pas-à-pas, "
        "prendre le contrôle de la souris et du clavier), captures d'écran, "
        "lancer des applications, automatisation du bureau (ELY Trainer). "
        "Aussi : accès au système de fichiers local via ELY Desktop — "
        "lister, lire, écrire, déplacer, supprimer des fichiers, créer des répertoires."
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

Emojis — RÈGLE STRICTE :
- Par défaut, aucun emoji, aucun émoticône, aucun pictogramme Unicode.
- Ni ✋ ni 🖐️ ni 👋 ni ✅ ni 🎉 ni aucun autre, au milieu ou à la fin.
- Si l'utilisateur a désactivé les emojis dans ses préférences, la règle est ABSOLUE,
  y compris dans la réponse qui accuse réception de la règle elle-même.
- Exemple CORRECT : "C'est noté, je ne le ferai plus."
- Exemple INCORRECT : "C'est noté, je ne le ferai plus. ✋"

Apprentissage des préférences — IMPÉRATIF :
- Dès que l'utilisateur exprime une préférence sur le ton, le format, le style, les émojis,
  la longueur des réponses, la langue, ou tout autre aspect de communication,
  appelle IMMÉDIATEMENT l'outil save_user_preference AVANT de répondre.
- Formule la préférence de façon claire et actionnable (ex: "Ne jamais utiliser d'émojis").
- Ensuite seulement, réponds en appliquant déjà la préférence.
- Idem pour save_constraint si l'utilisateur pose une règle ferme sur ce qu'il ne veut jamais.

Intégrité des actions — IMPÉRATIF ABSOLU :
- Ne JAMAIS prétendre qu'une action est exécutée sans avoir appelé l'outil correspondant dans ce tour.
- INTERDIT : "c'est fait", "rappel enregistré", "événement créé", "email envoyé", "tâche planifiée" sans tool_call préalable.
- AUTORISÉ sans tool_call : "je vais le faire", "je m'en occupe", "laisse-moi créer cela".
- Quand l'utilisateur confirme par "oui", "vas-y", "fais-le" : APPELLE L'OUTIL IMMÉDIATEMENT, ne repasse pas par une phrase d'annonce.
- Rappel quotidien/récurrent → scheduler_create_task avec cron.
- Événement unique dans Google Calendar → calendar_create_event.
- Si le tool échoue, reporte l'erreur précisément au lieu d'inventer un succès.

Recherche documentaire proactive — IMPÉRATIF :
- Avant de répondre à toute question factuelle susceptible d'impliquer un document
  personnel de l'utilisateur (contrat, facture, rapport, note, guide, manuel, etc.),
  appelle d'abord smart_knowledge_query avec la question telle quelle.
- Si l'outil retourne "__NO_RELEVANT_DOCS__", ignore-le et réponds normalement sans
  jamais mentionner à l'utilisateur que tu as cherché ou que tu n'as rien trouvé.
- Si l'outil retourne des extraits, base ta réponse dessus et cite les sources
  (nom du fichier et numéro de chunk) entre parenthèses à la fin.
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
        "RÈGLE ABSOLUE D'EXÉCUTION : Appelle TOUJOURS les outils directement et immédiatement "
        "sans annoncer en texte ce que tu vas faire. Ne dis JAMAIS 'je vais chercher', "
        "'je vais lancer', 'je vais effectuer' — appelle l'outil sans commentaire. "
        "Les actions critiques déclenchent automatiquement une confirmation HITL.\n\n"
        "Outils disponibles :\n"
        "Gmail : gmail_list_emails, gmail_read_email, gmail_send_email (HITL), "
        "gmail_reply_email (HITL), gmail_send_with_attachment (HITL), "
        "gmail_mark_read, gmail_mark_unread, gmail_create_draft, gmail_list_drafts, "
        "gmail_search_for_cleanup, gmail_list_labels, gmail_create_label, "
        "gmail_move_emails (HITL), gmail_trash_emails (HITL), "
        "gmail_batch_modify (modif lot jusqu'à 1000 msgs), "
        "gmail_update_settings (signature/vacation/filtre/transfert, HITL), "
        "gmail_raw_api_call (API brute, HITL).\n"
        "Calendar : calendar_list_events, calendar_create_event (HITL), "
        "calendar_get_event, calendar_update_event, calendar_delete_event (HITL), "
        "calendar_check_availability, calendar_list_calendars, "
        "calendar_quick_add (langage naturel, HITL), "
        "calendar_create_meet_event (visio Meet + participants + RRULE, HITL), "
        "calendar_raw_api_call (API brute, HITL).\n"
        "Drive : drive_list_files, drive_read_file, drive_create_folder, drive_create_file, "
        "drive_update_file, drive_move_file (HITL), drive_rename_file, drive_delete_file (HITL), "
        "drive_share_file (permissions, HITL), drive_copy_file, drive_export_file "
        "(PDF/Docx/Xlsx...), drive_raw_api_call (API brute, HITL).\n"
        "Docs : docs_create_document, docs_read_document, docs_append_text, "
        "docs_replace_text, docs_insert_table, "
        "docs_batch_update (style, titres, listes, images, liens), "
        "docs_raw_api_call (API brute, HITL).\n"
        "Sheets : sheets_create_spreadsheet, sheets_read_spreadsheet, sheets_append_rows, "
        "sheets_update_cells, sheets_delete_rows, sheets_add_sheet, sheets_list_sheets, "
        "sheets_batch_update (trier, insérer colonnes, fusionner, figer, "
        "mise en forme, validation), sheets_raw_api_call (API brute, HITL).\n"
        "Tasks : tasks_list, tasks_create, tasks_complete, tasks_update, "
        "tasks_delete (HITL), tasks_list_tasklists, tasks_create_tasklist, "
        "tasks_raw_api_call (réordonner, nettoyer, sous-tâches, HITL).\n"
        "Contacts : contacts_search, contacts_list, contacts_create, "
        "contacts_get, contacts_update, contacts_delete (HITL), "
        "contacts_batch_operations (créer/modifier/supprimer jusqu'à 200, HITL), "
        "contacts_raw_api_call (groupes, annuaire, HITL)." + _COMMON_FORMAT
    ),
    "infra": (
        _IDENTITY +
        "Tu es spécialiste de l'infrastructure et de l'automatisation.\n\n"
        "Tu maîtrises les commandes SSH sur les serveurs autorisés, la gestion des "
        "tâches planifiées (cron), le briefing matinal et la surveillance de sites "
        "web. Toutes les commandes SSH nécessitent une validation humaine (HITL).\n\n"
        "RÈGLE IMPÉRATIVE — rappels récurrents :\n"
        "Quand l'utilisateur demande un rappel/résumé/briefing récurrent "
        "(quotidien, hebdomadaire, chaque jour/matin/soir, tous les jours, "
        "à telle heure chaque jour), tu DOIS appeler l'outil "
        "scheduler_create_task avec l'expression cron appropriée. "
        "save_user_preference n'est PAS le bon outil pour ça — il sert "
        "uniquement à noter des préférences de style (emoji, ton, longueur).\n\n"
        "Exemples :\n"
        "- 'chaque soir à 18h45' → scheduler_create_task(cron_expression='45 18 * * *', ...)\n"
        "- 'tous les lundis 9h' → scheduler_create_task(cron_expression='0 9 * * 1', ...)\n"
        "- 'chaque matin' → scheduler_create_task(cron_expression='0 8 * * *', ...)\n\n"
        "Après avoir créé la tâche, confirme brièvement à l'utilisateur avec "
        "l'heure et la fréquence. Ne réponds JAMAIS 'je vais créer' sans "
        "avoir appelé l'outil.\n\n"
        "Outils disponibles : ssh_execute (HITL obligatoire), system_info, "
        "scheduler_create_task, scheduler_list_tasks, scheduler_delete_task, "
        "briefing_generate, watchdog_add, watchdog_list, watchdog_remove." + _COMMON_FORMAT
    ),
    "general": (
        _IDENTITY +
        "Tu es une assistante IA personnelle avec accès à tous les outils.\n\n"
        "Utilise les outils disponibles dès que la demande le justifie, sans demander "
        "de confirmation sauf pour les actions irréversibles (envoyer un email, "
        "supprimer, cliquer, exécuter SSH). Répondre en français par défaut.\n\n"
        "Rappel outils clés : system_info (infos machine, RAM, CPU, OS, disque), "
        "weather_get (météo), news_get_headlines (actualités)." + _COMMON_FORMAT
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# Tool subsets per specialist
# ──────────────────────────────────────────────────────────────────────────────

# Tools available in every specialist domain — user preferences and constraints
# must be saveable regardless of the current routing domain.
_MEMORY_SKILLS = {
    "save_user_preference", "save_constraint",
    "knowledge_search", "knowledge_list",
    "smart_knowledge_query",
}

_RESEARCH_SKILLS = {
    "weather_get", "news_get_headlines", "translate_text",
    "browser_navigate", "browser_search_web", "browser_get_text",
    "browser_screenshot", "browser_click", "browser_fill", "browser_close",
} | _MEMORY_SKILLS

_WORKSPACE_SKILLS = {
    # Gmail
    "gmail_list_emails", "gmail_read_email", "gmail_send_email",
    "gmail_reply_email", "gmail_send_with_attachment",
    "gmail_mark_read", "gmail_mark_unread",
    "gmail_create_draft", "gmail_list_drafts",
    "gmail_list_labels", "gmail_create_label",
    "gmail_move_emails", "gmail_trash_emails", "gmail_search_for_cleanup",
    "gmail_batch_modify", "gmail_update_settings", "gmail_raw_api_call",
    # Calendar
    "calendar_list_events", "calendar_create_event",
    "calendar_get_event", "calendar_update_event", "calendar_delete_event",
    "calendar_check_availability", "calendar_list_calendars",
    "calendar_quick_add", "calendar_create_meet_event", "calendar_raw_api_call",
    # Drive
    "drive_list_files", "drive_read_file",
    "drive_create_folder", "drive_create_file", "drive_update_file",
    "drive_move_file", "drive_rename_file", "drive_delete_file",
    "drive_share_file", "drive_copy_file", "drive_export_file", "drive_raw_api_call",
    # Docs
    "docs_create_document", "docs_read_document", "docs_append_text",
    "docs_replace_text", "docs_insert_table",
    "docs_batch_update", "docs_raw_api_call",
    # Sheets
    "sheets_create_spreadsheet", "sheets_read_spreadsheet", "sheets_append_rows",
    "sheets_update_cells", "sheets_delete_rows", "sheets_add_sheet", "sheets_list_sheets",
    "sheets_batch_update", "sheets_raw_api_call",
    # Tasks
    "tasks_list", "tasks_create", "tasks_complete",
    "tasks_update", "tasks_delete", "tasks_list_tasklists", "tasks_create_tasklist",
    "tasks_raw_api_call",
    # Contacts
    "contacts_search", "contacts_list", "contacts_create",
    "contacts_get", "contacts_update", "contacts_delete",
    "contacts_batch_operations", "contacts_raw_api_call",
} | _MEMORY_SKILLS

_INFRA_SKILLS = {
    "ssh_execute", "system_info",
    "scheduler_create_task", "scheduler_list_tasks", "scheduler_delete_task",
    "briefing_generate",
    "watchdog_add", "watchdog_list", "watchdog_remove",
} | _MEMORY_SKILLS


# ──────────────────────────────────────────────────────────────────────────────
# Router node
# ──────────────────────────────────────────────────────────────────────────────

import re as _re

# Hybrid router: keyword shortcuts first (instant), LLM fallback only if no match.
# Each domain has high-confidence patterns. Ordered by specificity.
_ROUTER_PATTERNS: list[tuple[str, _re.Pattern]] = [
    ("workspace", _re.compile(
        r"\b(gmail|emails?|mails?|courriels?|messagerie|inbox|boîte|courrier|"
        r"calendar|calendrier|agenda|rendez.?vous|événements?|réunions?|meetings?|"
        r"drive|dossiers?|fichiers?(?!.*local)|documents?(?!.*pdf)|google doc|gdoc|"
        r"sheets?|tableurs?|spreadsheets?|excel|"
        r"tasks?|tâches?|to.?do|todo|"
        r"contacts?|annuaires?|"
        r"rappel(le)?(.*) (à|le|pour|aujourd|demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)|"
        r"planifie.*aujourd|planifie.*demain)\b",
        _re.IGNORECASE)),
    ("infra", _re.compile(
        r"\b(ssh|serveurs?|servers?|docker|nginx|cron|tâche planifiée|"
        r"watchdog|veilles?|surveille|monitoring|infos? système|specs?|"
        r"tous les jours|chaque (jour|matin|soir|semaine|lundi|mardi)|"
        r"toutes les semaines|hebdomadaire|quotidien|récurrent|briefings?)\b",
        _re.IGNORECASE)),
    ("research", _re.compile(
        r"\b(météo|weather|news|actualités?|titres? du jour|"
        r"cherche sur (le )?(web|internet|google)|recherche web|"
        r"traduis|translate|traductions?|"
        r"va sur (https?:\/\/|www\.)|navigue|ouvre (le )?site|lis (la )?page)\b",
        _re.IGNORECASE)),
    ("creative", _re.compile(
        r"\b(génère? une image|crée une image|dessine|illustre|illustrations?|"
        r"qr ?codes?|youtube|vidéo youtube|"
        r"analyse (ce |le )?pdf|lis (ce |le )?pdf|"
        r"exécute (ce |du )?python|code python)\b",
        _re.IGNORECASE)),
    ("memory", _re.compile(
        r"\b(prends? une note|prends? note|mémorise|notes? personnelles?|"
        r"whatsapp|"
        r"cherche dans mes (notes?|documents?|fichiers?))\b",
        _re.IGNORECASE)),
    ("desktop", _re.compile(
        r"\b(montre.moi|démontre|tuteur|apprends.moi|fais une démo|"
        r"capture (d'|de l')écran|screenshot de l'écran|"
        r"prends le contrôle|clique|tape sur|"
        r"mes fichiers locaux|mon bureau|mon desktop)\b",
        _re.IGNORECASE)),
]


def _quick_route(msg: str) -> str | None:
    """Fast keyword-based routing. Returns None if no high-confidence match."""
    msg_lower = msg.lower().strip()
    # Pure greetings / acknowledgments
    if _re.match(
        r"^[\s\.,!?]*(bonjour|salut|hello|hey|coucou|merci|ok|oui|non|d'accord|"
        r"au revoir|bonne (journée|soirée|nuit)|bonne soirée|bonsoir)[\s\.,!?]*$",
        msg_lower,
    ):
        return "general"
    # Indirect greetings
    if _re.search(
        r"\b(dis|dire|peux.?tu (me )?dire|dis.?moi)\b.*\b(bonjour|salut|hello|coucou)\b",
        msg_lower,
    ) or _re.search(r"\bsalue.?moi\b", msg_lower):
        return "general"
    # Common quick questions → general
    if _re.search(
        r"\b(quelle heure|quel jour|quelle date|quelle année|"
        r"qu'est.ce que tu peux (faire|m'aider)|que peux.tu (faire|m'aider)|"
        r"qui es.tu|comment ça va|comment vas.tu|qui suis.je|"
        r"comment t'appelles.tu|c'est quoi ton nom|ton prénom)\b",
        msg_lower,
    ):
        return "general"

    # PRIORITY 1: recurring schedules ALWAYS go to infra
    _recurrence_kw = _re.search(
        r"\b(chaque (jour|matin|soir|semaine|mois|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)|"
        r"tous les (jours|matins|soirs|lundis|mardis|mercredis|jeudis|vendredis|samedis|dimanches)|"
        r"toutes les (semaines|heures|minutes)|"
        r"quotidien|hebdomadaire|mensuel|récurrent|récurrente|automatiquement)\b",
        msg_lower,
    )
    if _recurrence_kw:
        return "infra"

    # PRIORITY 2: references to scheduled/planned tasks → infra
    # "tâches planifiées", "mes rappels", "mes programmations", "mon briefing"
    # point to APScheduler (infra), not Google Tasks (workspace).
    if _re.search(
        r"\b(tâches? planifiées?|taches? planifiees?|mes rappels?|mes programmations?|"
        r"mon briefing|mes briefings?|mes tâches? automatiques?|mes crons?|"
        r"liste.*rappels?|afficher? (les |mes )?rappels?|mes (tâches? )?récurrentes?)\b",
        msg_lower,
    ):
        return "infra"

    for domain, pattern in _ROUTER_PATTERNS:
        if pattern.search(msg):
            return domain
    return None


async def router_node(state: AgentState) -> dict:
    """Classify the user's request and set the routing domain in state."""
    import time as _t
    _start = _t.monotonic()
    messages = state["messages"]
    last_user_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content[:500]  # truncate for speed
            break

    # ── Pass 1: fast keyword router (zero LLM call) ──────────────────────
    domain = _quick_route(last_user_msg)
    if domain is not None:
        logger.warning("⏱ TIMING[router-fast] %.3fs → domain=%s (msg=%.60s)",
                       _t.monotonic() - _start, domain, last_user_msg)
        return {"domain": domain}

    # ── Pass 2: LLM fallback for ambiguous queries ───────────────────────
    from app.services.qwen_no_think import inject_no_think, strip_think_block
    llm = get_llm_for_tier(ComplexityTier.SIMPLE)
    try:
        _msgs = inject_no_think([
            SystemMessage(content=_ROUTER_SYSTEM),
            HumanMessage(content=last_user_msg),
        ])
        response = await llm.ainvoke(_msgs)
        response.content = strip_think_block(getattr(response, 'content', '') or '')
        domain = response.content.strip().lower()
        if domain not in ("research", "workspace", "infra", "creative", "data", "memory", "desktop", "general"):
            domain = "general"
    except Exception as exc:
        logger.warning("Router LLM failed, falling back to general: %s", exc)
        domain = "general"

    logger.warning("⏱ TIMING[router-llm] %.2fs → domain=%s (msg=%.60s)",
                   _t.monotonic() - _start, domain, last_user_msg)
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
        import time as _t
        _start = _t.monotonic()
        from app.agent.sub_agents.registry import get_sub_agent_registry

        registry = get_sub_agent_registry()
        sub_graph = registry.get(domain)

        logger.warning("⏱ TIMING[dispatch→%s] starting", domain)

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
        }
        try:
            result = await sub_graph.ainvoke(
                sub_input, config={"recursion_limit": 100}
            )
            # Return only the messages produced by the sub-agent
            new_messages = result["messages"][len(state["messages"]):]
            # ── Image pass-through (QR code, Imagen, etc.) ────────────────
            # If a ToolMessage contains {"type":"image",...} JSON and the
            # final AIMessage doesn't already include it, prepend the JSON so
            # the frontend can render the image (parseImageBlock in MessageBubble).
            import json as _json
            _image_jsons: list[str] = []
            from langchain_core.messages import ToolMessage as _TM
            for _m in new_messages:
                if isinstance(_m, _TM):
                    _c = _m.content or ""
                    if isinstance(_c, str) and _c.startswith("{"):
                        try:
                            _obj = _json.loads(_c)
                            if isinstance(_obj, dict) and _obj.get("type") == "image":
                                _image_jsons.append(_c)
                        except Exception:
                            pass
            if _image_jsons:
                _last = new_messages[-1] if new_messages else None
                _last_content = (_last.content or "") if _last else ""
                if isinstance(_last, AIMessage) and not any(j in _last_content for j in _image_jsons):
                    _separator = "\n\n" if _last_content else ""
                    _combined = _last_content + _separator + "\n\n".join(_image_jsons)
                    new_messages = list(new_messages[:-1]) + [
                        _last.model_copy(update={"content": _combined})
                    ]
            # ─────────────────────────────────────────────────────────────
            logger.warning("⏱ TIMING[dispatch→%s] DONE in %.2fs (%d new msgs)", domain, _t.monotonic() - _start, len(new_messages))
            return {"messages": new_messages, "domain": domain}
        except Exception as exc:
            logger.error(
                "Sub-agent '%s' failed (%.2fs, %s) — running general agent with tools loop",
                domain, _t.monotonic() - _start, exc,
            )
            # Run a full agent+tools loop (not just one turn) so tool_calls
            # like pdf_read, search_web, etc. are actually executed and the
            # user gets a real response instead of an empty bubble.
            from app.agent.nodes import tool_node as _tool_node
            from langchain_core.messages import AIMessage as _AI, BaseMessage as _BM
            from langchain_core.messages import messages_from_dict as _mfd

            def _ensure_base_messages(msgs: list) -> list:
                """Convert any serialized dict messages to BaseMessage objects."""
                result = []
                for m in msgs:
                    if isinstance(m, _BM):
                        result.append(m)
                    elif isinstance(m, dict):
                        try:
                            result.extend(_mfd([m]))
                        except Exception:
                            pass  # skip malformed
                return result

            general = create_agent_node()
            current_state = dict(state)
            current_state["messages"] = _ensure_base_messages(current_state.get("messages", []))
            MAX_STEPS = 10
            for _ in range(MAX_STEPS):
                result = await general(current_state)
                new_msgs = result.get("messages", [])
                all_msgs = list(current_state["messages"]) + new_msgs
                current_state = {**current_state, "messages": all_msgs}
                last = all_msgs[-1] if all_msgs else None
                if not (isinstance(last, _AI) and getattr(last, "tool_calls", None)):
                    break  # No pending tool calls — final answer reached
                # Execute tools and continue the loop
                tool_result = await _tool_node(current_state)
                tool_msgs = tool_result.get("messages", [])
                all_msgs = all_msgs + tool_msgs
                current_state = {**current_state, "messages": all_msgs}

            new_messages = current_state["messages"][len(state["messages"]):]
            return {"messages": new_messages, "domain": domain}

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
