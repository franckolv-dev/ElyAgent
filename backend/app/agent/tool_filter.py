# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_filter.py
# @brief      Shared keyword-based tool filtering — used by both the general
#             agent_node and sub-agent factories to avoid binding all 160 tools
#             at every turn.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Shared tool filter (audit H-5, fixed 2026-05-06).

Problem
-------
The general ``agent_node`` in ``app/agent/nodes.py`` was calling
``bind_tools(registry.all_tools)`` — sending all 160 tool definitions
(~15 000 tokens) at every turn. On a local Qwen 8B with 32k context,
99 % of the request body was tool descriptions, blowing prompt
processing to 5+ minutes.

The sub-agent factory already had a keyword-based filter that worked,
but the general agent path did not. This module extracts the filter
into a reusable function so both code paths use the same logic.

Heuristic
---------
For each user-query keyword pattern, declare which tool name prefixes
to keep. ``ALWAYS_KEEP`` tools (memory, preferences, knowledge) are
always included so the agent can persist context across turns.

If no keywords match, return the full list (better to be slow than to
miss a tool the LLM genuinely needs).
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)


# Keyword → tool prefix mapping. Order does not matter; multiple patterns
# can match (matches are unioned). Each pattern is matched against the
# lowercased user query.
_KW_FILTERS: list[tuple[re.Pattern, tuple[str, ...]]] = [
    # Mail / contacts
    (re.compile(r"\b(mails?|mai|emails?|e.?mail|courriels?|inbox|gmail|courrier|messagerie|boîte (mail|courrier)|brouillons?|drafts?|envoie|envoy|reply|réponds|forward)\b"),
     ("gmail_", "contacts_")),
    # Calendar — punctual events
    (re.compile(r"\b(calendar|calendrier|agenda|planning|événements?|réunions?|meetings?|rendez.?vous)\b"),
     ("calendar_",)),
    # Drive / files
    (re.compile(r"\b(drive|fichiers?(?!.*local)|dossiers?(?!.*local))\b"),
     ("drive_",)),
    # Docs
    (re.compile(r"\b(docs?|documents?|google doc|gdoc)\b"),
     ("docs_",)),
    # Sheets
    (re.compile(r"\b(sheets?|tableurs?|spreadsheets?|excel)\b"),
     ("sheets_",)),
    # Tasks
    (re.compile(r"\b(tâches?|taches?|to.?do|todo)\b"),
     ("tasks_",)),
    # Contacts
    (re.compile(r"\b(contacts?|annuaires?|carnet d'adresse)\b"),
     ("contacts_",)),
    # Recurring schedule
    (re.compile(r"\b(cron|tâche planifiée|planifie|programme|hebdo|quotidien|récurrent|toutes les|tous les|chaque (jour|matin|soir|semaine|mois))\b"),
     ("scheduler_",)),
    # Generic reminder — could be calendar OR scheduler
    (re.compile(r"\brappels?\b"),
     ("calendar_", "scheduler_")),
    # SSH
    (re.compile(r"\b(ssh|serveurs?|servers?)\b"),
     ("ssh_",)),
    # Watchdog
    (re.compile(r"\b(watchdog|surveille|veilles?|monitoring)\b"),
     ("watchdog_",)),
    # Briefing
    (re.compile(r"\b(briefings?|matin|résumé|debrief)\b"),
     ("briefing_",)),
    # Weather
    (re.compile(r"\b(météo|meteo|weather|temps|climat|temp[ée]rature|pluie|soleil|neige)\b"),
     ("weather_",)),
    # News
    (re.compile(r"\b(news|actualit[ée]s?|infos?|articles?|presse|titres?|headlines?)\b"),
     ("news_",)),
    # Web search / browse — includes social network keywords because most
    # social-media tasks ("regarde mes notifs LinkedIn", "vérifie mes profils
    # réseaux sociaux", "va voir sur Mastodon") need the Chrome extension
    # to act in the user's authenticated session, which lives in browser_*.
    (re.compile(
        r"\b("
        r"web|internet|cherche|recherche|googl|sites?|urls?|pages?|navig|browse|catalogmaker|http"
        r"|onglets?|tab|tabs"
        r"|profils?|réseau(x)?\s*sociau(x)?|reseau(x)?\s*sociau(x)?|social[\s-]*media"
        r"|linkedin|mastodon|twitter|x\.com|instagram|facebook|threads|bluesky|tiktok"
        r"|doctolib|sncf|booking|amazon\.fr|leboncoin"
        r")\b"),
     ("web_", "browser_")),
    # Translation
    (re.compile(r"\b(traduis|traduit|traduction|translate|translator)\b"),
     ("translate_",)),
    # Image / vision / screenshots
    (re.compile(r"\b(images?|photos?|pictures?|screenshots?|captur|photographie|generate.*image|génère.*image)\b"),
     ("image_", "vision_", "browser_screenshot", "os_screenshot", "trainer_screenshot",
      "pdf_analyze_with_vision", "generate_image")),
    # PDF
    (re.compile(r"\b(pdf|fichier pdf)\b"),
     ("pdf_",)),
    # YouTube
    (re.compile(r"\b(youtube|vidéos?|videos?|chaînes?)\b"),
     ("youtube_",)),
    # Maps / location
    (re.compile(r"\b(maps?|cartes?|itinéraires?|trajets?|directions?|adresse|gps|géoloc|position|près de|autour|nearby|restaurants?|cafés?|hôtels?|stations?)\b"),
     ("maps_",)),
    # WhatsApp
    (re.compile(r"\b(whatsapp|whats|wa)\b"),
     ("whatsapp_",)),
    # Telegram
    (re.compile(r"\b(telegram|tg)\b"),
     ("telegram_",)),
    # QR code
    (re.compile(r"\b(qr.?codes?|flashcode)\b"),
     ("qrcode_",)),
    # Notes
    (re.compile(r"\b(notes?|notepad|carnet|memos?)\b"),
     ("notes_",)),
    # Python / code execution
    (re.compile(r"\b(python|exécute|execute|code|script|calcul)\b"),
     ("python_",)),
    # Mission management
    (re.compile(r"\b(missions?|objectifs?|goals?|tâches? complexes?)\b"),
     ("system_list_missions",)),
    # Self-diagnostic
    (re.compile(
        r"\b("
        r"logs?|journal|debug|diagnostic|"
        r"santé|sante|health|status|statut|"
        r"état|etat|scheduled|"
        r"canaux|channels?|"
        r"fonctionne|marche|tourne|"
        r"pourquoi.*pas|pourquoi.*marche|"
        r"llm|llms|modèles?|modeles?|model|models|"
        r"provider|providers|fournisseur|"
        r"utilises?|utilise[sz]|"
        r"configur|réglag|reglag|setting|"
        r"actif|actifs|active|inactive|connecté|connecte|"
        r"version|uptime|"
        r"ram|disk|disque|"
        r"porte[sz]|vas[\s-]?tu|comment.*va|"
        r"échou|echou|échec|echec|erreur|crashé|cassé|panne|bug"
        r")\b"
    ),
     ("system_",)),
    # Desktop / OS automation
    (re.compile(r"\b(bureau|desktop|écran(?!.*site)|fenêtre|cliqu|souris|clavier|raccourci)\b"),
     ("os_", "desktop_", "trainer_")),
    # Fichiers LOCAUX (machine de l'utilisateur via ELY Desktop) — chemin
    # absolu ou mention explicite « local / sur mon mac ». Sans cette règle,
    # « ouvre le fichier /Users/.../x.rtf » ne bindait que drive_ (cloud) ;
    # les outils desktop_read_file/desktop_write_file manquaient → l'agent ne
    # pouvait NI lire NI écrire les fichiers du Mac (bug terrain 13/06, tâche
    # Prospection : RTF/CSV jamais modifiés). Le chemin absolu est le signal
    # fort ; « fichier » seul reste mappé sur drive_ (cas cloud le + courant).
    (re.compile(
        r"(/users/|/home/|(?:^|\s)~/"
        r"|fichiers?\s+locaux?|sur (?:mon|ton|le|votre) (?:mac|disque|ordinateur|poste)"
        r"|disque (?:dur )?local)",
        re.I,
    ),
     ("desktop_",)),
    # MCP
    (re.compile(r"\b(mcp|model context protocol)\b"),
     ("mcp_",)),
    # Knowledge base
    (re.compile(r"\b(connaissances?|knowledge|base.*connaissances?|wiki|documentation)\b"),
     ("knowledge_", "smart_knowledge_query")),
]

# Tools that MUST always be available regardless of query keywords —
# they let the agent persist context across turns and access universal
# memory.
ALWAYS_KEEP: tuple[str, ...] = (
    "save_user_preference",
    "save_constraint",
    "memory_archive",
    "memory_search",
    "memory_recent",
    "memory_view_profile",
    "knowledge_search",
    "knowledge_list",
    "smart_knowledge_query",
)


def tools_named_in_text(tools: Sequence, text: str) -> list:
    """Return every tool whose *exact* name appears as a token in ``text``.

    Motivation (2026-05-31, scheduled-task multi-domain bug)
    -------------------------------------------------------
    ``filter_tools_by_query`` is keyword-based and tuned to keep local-model
    prompts short. It is accent- and word-boundary-fragile: on the prod
    « Briefing quotidien 9h » prompt it bound ``gmail_list_emails`` (matched
    via "mails") but silently dropped ``calendar_list_events`` (``\\bcalendar\\b``
    never matches inside ``calendar_list_events``, and "événements" ≠ the
    accent-less "evenements" the prompt used) and ``system_list_scheduled_tasks``.

    Automated/scheduled prompts are fixed and routinely name the exact tools
    they want called. Matching those literal names guarantees a multi-domain
    prompt binds every tool it explicitly asks for, regardless of accents or
    phrasing. Tool names contain underscores, so a normal ``\\b`` boundary is
    wrong (``_`` is a word char) — we use a custom ``[a-z0-9_]`` boundary so
    ``calendar_list_events`` does not also match a hypothetical
    ``calendar_list`` prefix.

    Returns an empty list when ``text`` is falsy or names nothing.
    """
    if not text:
        return []
    low = text.lower()
    matched = []
    for t in tools:
        name = getattr(t, "name", "") or ""
        if not name:
            continue
        if re.search(
            r"(?<![a-z0-9_])" + re.escape(name.lower()) + r"(?![a-z0-9_])",
            low,
        ):
            matched.append(t)
    return matched


def filter_tools_by_query(
    tools: Sequence,
    user_query: str,
    *,
    threshold: int = 20,
    debug_label: str = "agent",
) -> list:
    """Filter `tools` based on keywords detected in `user_query`.

    Parameters
    ----------
    tools
        Sequence of LangChain tool objects with a `.name` attribute.
    user_query
        The user's message (raw, will be lowercased).
    threshold
        If ``len(tools) <= threshold``, no filtering is performed (the
        tool list is already short enough). Default 20.
    debug_label
        Label included in the timing log for traceability.

    Returns
    -------
    list
        Filtered tools list. If no keyword matched, the original list
        is returned unchanged (better to over-bind than miss a tool).
    """
    if len(tools) <= threshold:
        return list(tools)

    query = (user_query or "").lower()
    matched_prefixes: set[str] = set()
    matched_exact: set[str] = set()

    for pattern, prefixes in _KW_FILTERS:
        if pattern.search(query):
            for p in prefixes:
                # Distinguish prefixes (end with _) from exact tool names
                if p.endswith("_"):
                    matched_prefixes.add(p)
                else:
                    matched_exact.add(p)

    if not matched_prefixes and not matched_exact:
        # No keyword matched — keep everything (safety: avoid breaking
        # queries that don't fit our categories)
        logger.debug(
            "[tool_filter:%s] no keyword match — keeping all %d tools",
            debug_label, len(tools),
        )
        return list(tools)

    filtered = [
        t for t in tools
        if any(t.name.startswith(p) for p in matched_prefixes)
        or t.name in matched_exact
        or t.name in ALWAYS_KEEP
    ]

    if not filtered:
        # Safety: don't end up with zero tools
        logger.warning(
            "[tool_filter:%s] filter produced 0 tools, falling back to all %d",
            debug_label, len(tools),
        )
        return list(tools)

    logger.warning(
        "[tool_filter:%s] %d → %d tools (kw_prefixes=%s, kw_exact=%s)",
        debug_label, len(tools), len(filtered),
        sorted(matched_prefixes), sorted(matched_exact),
    )
    return filtered
