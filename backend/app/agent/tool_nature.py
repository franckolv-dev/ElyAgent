# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_nature.py
# @brief      Ce que chaque outil FAIT, et s'il arbitre à la place de
#             l'utilisateur.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""La donnée de référence du plan de marche — lot 1, 28/07/2026.

La contradiction, et sa résolution
-----------------------------------
    « Je te dis qu'Ely ne doit rien faire mais je t'ai demandé qu'elle nettoie
      mes mails et ajoute des rendez-vous. Je te dis un truc et son contraire. »
                                                        — Franck, 28/07/2026

Elle se dissout : **un LLM ne peut pas agir sur le monde**, il n'émet que du
texte. Toute action est donc TOUJOURS exécutée par Ely — contrainte physique,
pas choix d'architecture. Ce qui était reproché le 27/07 n'était pas qu'Ely
agisse, c'est qu'elle **arbitre à la place de l'utilisateur** avec des seuils
codés d'avance (le convertisseur PDF décidait seul de ce qu'était un titre, se
trompait, et personne ne le lui disait).

Deux axes, pas trois catégories
--------------------------------
La classification des **208 outils** l'a montré : les deux questions sont
INDÉPENDANTES. ``gmail_send_email`` est à la fois engageant (il part chez un
tiers) et arbitre (le corps du message se rédige) ; ``drive_create_folder``
n'est ni l'un ni l'autre.

- **EFFET** — ce qui se passe quand l'outil s'exécute :
    ``LECTURE``    ne modifie rien
    ``ECRITURE``   modifie quelque chose de réversible et privé
    ``ENGAGEANT``  irréversible, visible par des tiers, ou coûte de l'argent
- **ARBITRAGE** — l'outil doit-il trancher des choix de forme sur lesquels deux
  personnes compétentes pourraient différer ? Si oui, la demande de
  l'utilisateur doit pouvoir l'atteindre (cf. ``pdf_to_docx`` et #294).

Comment cette table a été établie
----------------------------------
Par le modèle cloud sur les outils réels — c'est du jugement à grande échelle,
donc exactement le cas d'usage de la règle qu'elle encode. Puis relue par
croisement mécanique avec les noms d'outils.

⚠️ Le lot 1 (#296) n'en recensait que **154** : son inventaire ne regardait que
``app/agent/tools`` et ratait les **55 outils de ``skills/builtin``** — dont
ceux qui pilotent le clavier, la souris et le système de fichiers. Corrigé au
lot 3 : le scan couvre tout ``app/``, et le pin de dérive avec lui.

⚠️ Ici on échoue FERMÉ — l'inverse de la boucle de conformité
--------------------------------------------------------------
Pour la conformité, un doute laisse passer : une vérification cassée ne doit
jamais retenir la réponse de l'utilisateur. Pour l'autorisation, c'est
l'inverse. Un faux positif coûte une question ; un faux négatif envoie un
message ou supprime des données sans que l'utilisateur l'ait voulu.
L'asymétrie est trop forte pour laisser passer le doute.

Ce que le lot 3 a fermé
------------------------
Sur le périmètre complet, **18 actes engageants** n'étaient soumis à rien. Huit
sont passés sous autorisation (``hitl_preferences.LOCKED_HITL_TOOLS``), dix en
sont explicitement dispensés avec leur raison (``APPROVAL_WAIVED``).
``unguarded_engaging_tools()`` doit donc rester vide : ce qu'elle rapporterait
désormais serait une régression, pas un état de fait.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

EFFECTS: Final[frozenset[str]] = frozenset({"LECTURE", "ECRITURE", "ENGAGEANT"})


@dataclass(frozen=True)
class _N:
    """La nature d'un outil. ``_N`` pour que la table reste lisible d'un coup
    d'œil : 154 lignes, une par outil, groupées par famille."""

    effect: str
    arbitrates: bool = False


def _real_guard() -> frozenset[str]:
    """La garde RÉELLE, lue à ses deux sources.

    ⚠️ #296 écrivait cette liste À LA MAIN depuis ``hitl_descriptions.py``, qui
    ne décrit que 6 outils. La garde effective vit ailleurs, en deux endroits :
    ``hitl_preferences.LOCKED_HITL_TOOLS`` (dangereux, ON par défaut) et
    ``security_filter.ALWAYS_CRITICAL_TOOLS`` — **38 outils**. La liste écrite
    à la main a fait annoncer 26 trous là où il y en avait 9, et surtout elle
    aurait pu faire croire protégé ce qui ne l'était pas.

    Une table de sécurité bâtie sur la mauvaise source est pire qu'une absence
    de table : elle rassure. On DÉRIVE donc, on ne paraphrase plus.

    Ne lève jamais : si une source est illisible, on rend ce qu'on a — le
    croisement avec ``TOOL_NATURE`` reprotégera les engageants de toute façon.
    """
    guard: set[str] = set()
    for module, attr in (
        ("app.services.hitl_preferences", "LOCKED_HITL_TOOLS"),
        ("app.services.security_filter", "ALWAYS_CRITICAL_TOOLS"),
    ):
        try:
            mod = __import__(module, fromlist=[attr])
            guard |= set(getattr(mod, attr, ()) or ())
        except Exception as exc:  # noqa: BLE001 — une source absente n'est pas fatale
            logger.warning("tool_nature : garde %s.%s illisible (%s)", module, attr, exc)
    return frozenset(guard)


# Les outils déjà sous autorisation. ⚠️ PRIME sur la table : la classification
# a placé les trois ``gmail_trash_*`` en ECRITURE — raisonnement défendable, la
# corbeille Gmail est réversible — mais ils sont protégés aujourd'hui. Une table
# de données ne doit jamais pouvoir DÉPROTÉGER : le sens de lecture est
# toujours « ajouter une garde », jamais « en retirer une ».
ALREADY_GUARDED: Final[frozenset[str]] = _real_guard()


# Les actes engageants explicitement DISPENSÉS de confirmation, et pourquoi.
#
# Décisions de Franck, 28/07/2026 :
#     « Je ne veux pas avoir à confirmer pour l'ouverture d'un onglet Chrome ou
#       pour déclencher une tâche que j'ai créée et encore moins pour m'envoyer
#       un message via Telegram. »
#
# ⚠️ Une dispense n'est PAS un reclassement. ``telegram_send_message`` reste
# ``ENGAGEANT`` dans la table : il envoie bien un message. Le reclasser ferait
# mentir la table sur sa nature pour obtenir un effet de politique. On sépare
# donc ce que l'outil EST de ce qui exige un accord — la nature reste vraie,
# l'arbitrage reste traçable, et il se relit dans six mois.
#
# ⚠️ Une dispense ne peut jamais s'appliquer à un outil déjà gardé : ce serait
# rouvrir par la fenêtre la porte que ``ALREADY_GUARDED`` ferme. Un pin le
# vérifie.
APPROVAL_WAIVED: Final[dict[str, str]] = {
    # Naviguer n'est pas engager : une session de navigation, c'est des dizaines
    # de clics, et confirmer chacun rendrait l'automatisation inutilisable.
    "browser_tab_click": "naviguer n'est pas engager — décision de Franck du 28/07",
    "browser_click": "naviguer n'est pas engager — décision de Franck du 28/07",
    "browser_fill": "remplir un formulaire n'est pas le soumettre — même décision",
    # La tâche a déjà été approuvée à sa création ; la relancer n'ajoute rien.
    "scheduler_run_task": "la tâche a été approuvée quand l'utilisateur l'a créée",
    # Destinataire = l'utilisateur lui-même. C'est un canal de notification vers
    # lui, pas un envoi vers un tiers — et il doit fonctionner pendant une
    # mission de nuit sans réveiller personne pour demander la permission.
    "telegram_send_message": "le destinataire est l'utilisateur lui-même, pas un tiers",
    # La session de contrôle d'écran est autorisée UNE fois, par `trainer_start`
    # qui est gardé. Confirmer ensuite chaque geste reviendrait à demander
    # l'autorisation de faire ce qu'on vient d'autoriser.
    "trainer_click": "geste dans une session déjà autorisée par trainer_start",
    "trainer_type": "geste dans une session déjà autorisée par trainer_start",
    "trainer_hotkey": "geste dans une session déjà autorisée par trainer_start",
    "trainer_move": "geste dans une session déjà autorisée par trainer_start",
    # Les serveurs MCP accessibles sont déjà filtrés par utilisateur (mcp_acl) :
    # doubler d'une confirmation ferait payer deux fois le même contrôle.
    "mcp_call_tool": "déjà filtré par l'ACL MCP propre à chaque utilisateur",
}

# Paramètres par lesquels une exigence en langage naturel peut entrer dans un
# outil. C'est ce qui manquait à ``pdf_to_docx(source, output_name)`` : l'outil
# arbitrait la structure, et la demande n'avait aucun chemin pour l'atteindre.
_INTENT_PARAMS: Final[frozenset[str]] = frozenset({
    "requirements", "instructions", "prompt", "query", "description", "style",
    "constraints", "goal", "brief", "spec", "context", "message", "content",
    "text", "task", "request", "details", "tone", "body", "subject", "note",
    "notes", "title",
})


TOOL_NATURE: Final[dict[str, _N]] = {
    # ── agent/tools/agentic_rag_tool ────────────────────────────
    "smart_knowledge_query": _N("LECTURE"),
    # ── agent/tools/browser_extension_tool ──────────────────────
    "browser_bookmarks_search": _N("LECTURE"),
    "browser_close_tab": _N("ECRITURE"),
    "browser_downloads_search": _N("LECTURE"),
    "browser_history_search": _N("LECTURE"),
    "browser_list_tabs": _N("LECTURE"),
    "browser_open_tab": _N("ECRITURE"),
    "browser_tab_click": _N("ENGAGEANT"),
    "browser_tab_fill": _N("ECRITURE"),
    "browser_tab_get_url": _N("LECTURE"),
    "browser_tab_navigate": _N("ECRITURE"),
    "browser_tab_read_html": _N("LECTURE"),
    "browser_tab_read_text": _N("LECTURE"),
    "browser_tab_screenshot": _N("LECTURE"),
    "browser_tab_wait_for_selector": _N("LECTURE"),
    "browser_tab_wait_loaded": _N("LECTURE"),
    # ── agent/tools/calendar_tool ───────────────────────────────
    "calendar_check_availability": _N("LECTURE"),
    "calendar_create_event": _N("ECRITURE"),
    "calendar_create_meet_event": _N("ENGAGEANT"),
    "calendar_delete_event": _N("ENGAGEANT"),
    "calendar_get_event": _N("LECTURE"),
    "calendar_list_calendars": _N("LECTURE"),
    "calendar_list_events": _N("LECTURE"),
    "calendar_quick_add": _N("ECRITURE", arbitrates=True),
    "calendar_raw_api_call": _N("ENGAGEANT"),
    "calendar_update_event": _N("ECRITURE"),
    # ── agent/tools/contacts_tool ───────────────────────────────
    "contacts_batch_operations": _N("ENGAGEANT"),
    "contacts_create": _N("ECRITURE"),
    "contacts_delete": _N("ENGAGEANT"),
    "contacts_get": _N("LECTURE"),
    "contacts_list": _N("LECTURE"),
    "contacts_raw_api_call": _N("ENGAGEANT"),
    "contacts_search": _N("LECTURE"),
    "contacts_update": _N("ECRITURE"),
    # ── agent/tools/delegate_tool ───────────────────────────────
    "delegate": _N("LECTURE", arbitrates=True),
    # ── agent/tools/docs_tool ───────────────────────────────────
    "docs_append_text": _N("ECRITURE"),
    "docs_batch_update": _N("ECRITURE"),
    "docs_create_document": _N("ECRITURE"),
    "docs_insert_table": _N("ECRITURE"),
    "docs_raw_api_call": _N("ENGAGEANT"),
    "docs_read_document": _N("LECTURE"),
    "docs_replace_text": _N("ECRITURE"),
    # ── agent/tools/drive_tool ──────────────────────────────────
    "drive_copy_file": _N("ECRITURE"),
    "drive_create_file": _N("ECRITURE"),
    "drive_create_folder": _N("ECRITURE"),
    "drive_delete_file": _N("ECRITURE"),
    "drive_export_file": _N("ECRITURE", arbitrates=True),
    "drive_find_duplicates": _N("LECTURE"),
    "drive_list_files": _N("LECTURE"),
    "drive_move_file": _N("ECRITURE"),
    "drive_raw_api_call": _N("ENGAGEANT"),
    "drive_read_file": _N("LECTURE"),
    "drive_rename_file": _N("ECRITURE"),
    "drive_share_file": _N("ENGAGEANT"),
    "drive_update_file": _N("ECRITURE"),
    "drive_upload_local_file": _N("ECRITURE"),
    # ── agent/tools/file_tool ───────────────────────────────────
    "analyze_file": _N("LECTURE", arbitrates=True),
    # ── agent/tools/github_tool ─────────────────────────────────
    "github_notifications": _N("LECTURE"),
    "github_repo_stats": _N("LECTURE"),
    "github_traffic_stats": _N("LECTURE"),
    # ── agent/tools/gmail_tool ──────────────────────────────────
    "gmail_batch_modify": _N("ECRITURE"),
    "gmail_create_draft": _N("ECRITURE"),
    "gmail_create_label": _N("ECRITURE"),
    "gmail_empty_trash": _N("ENGAGEANT"),
    "gmail_list_drafts": _N("LECTURE"),
    "gmail_list_emails": _N("LECTURE"),
    "gmail_list_labels": _N("LECTURE"),
    "gmail_mark_read": _N("ECRITURE"),
    "gmail_mark_unread": _N("ECRITURE"),
    "gmail_move_emails": _N("ECRITURE"),
    "gmail_raw_api_call": _N("ENGAGEANT"),
    "gmail_read_email": _N("LECTURE"),
    "gmail_reply_email": _N("ENGAGEANT"),
    "gmail_save_attachments_to_drive": _N("ECRITURE"),
    "gmail_search_for_cleanup": _N("LECTURE"),
    "gmail_send_email": _N("ENGAGEANT"),
    "gmail_send_with_attachment": _N("ENGAGEANT"),
    "gmail_send_with_local_attachment": _N("ENGAGEANT"),
    "gmail_trash_by_category": _N("ECRITURE"),
    "gmail_trash_by_query": _N("ECRITURE"),
    "gmail_trash_emails": _N("ECRITURE"),
    "gmail_update_settings": _N("ENGAGEANT"),
    # ── agent/tools/graduated/fibonacci_tool ────────────────────
    "fibonacci": _N("LECTURE"),
    # ── agent/tools/knowledge_tool ──────────────────────────────
    "knowledge_list": _N("LECTURE"),
    "knowledge_search": _N("LECTURE"),
    # ── agent/tools/learned_skills_tool ─────────────────────────
    "skill_view": _N("LECTURE"),
    # ── agent/tools/maps_tool ───────────────────────────────────
    "maps_directions": _N("LECTURE"),
    "maps_geocode": _N("LECTURE"),
    "maps_nearby": _N("LECTURE"),
    "maps_reverse_geocode": _N("LECTURE"),
    # ── agent/tools/memgpt_tool ─────────────────────────────────
    "memory_archive": _N("ECRITURE"),
    "memory_recent": _N("LECTURE"),
    "memory_search": _N("LECTURE"),
    "memory_view_profile": _N("LECTURE"),
    # ── agent/tools/memory_recall_tool ──────────────────────────
    "memory_recall": _N("LECTURE"),
    # ── agent/tools/memory_tool ─────────────────────────────────
    "save_constraint": _N("ECRITURE"),
    "save_user_preference": _N("ECRITURE"),
    # ── agent/tools/notes_tool ──────────────────────────────────
    "notes_create": _N("ECRITURE"),
    "notes_delete": _N("ENGAGEANT"),
    "notes_list": _N("LECTURE"),
    "notes_read": _N("LECTURE"),
    "notes_search": _N("LECTURE"),
    "notes_update": _N("ECRITURE"),
    # ── agent/tools/pdf_tool ────────────────────────────────────
    "pdf_info": _N("LECTURE"),
    "pdf_read": _N("LECTURE"),
    "pdf_to_docx": _N("ECRITURE", arbitrates=True),
    # ── agent/tools/python_tool ─────────────────────────────────
    "python_execute": _N("ECRITURE"),
    # ── agent/tools/qrcode_tool ─────────────────────────────────
    "qrcode_generate": _N("ECRITURE", arbitrates=True),
    "qrcode_generate_vcard": _N("ECRITURE", arbitrates=True),
    "qrcode_generate_wifi": _N("ECRITURE", arbitrates=True),
    # ── agent/tools/reversible_tool ─────────────────────────────
    "list_revertible_actions": _N("LECTURE"),
    "revert_action": _N("ECRITURE"),
    "undo_last_action": _N("ECRITURE"),
    # ── agent/tools/scheduler_tool ──────────────────────────────
    "scheduler_create_task": _N("ECRITURE"),
    "scheduler_delete_task": _N("ENGAGEANT"),
    "scheduler_list_tasks": _N("LECTURE"),
    "scheduler_run_task": _N("ENGAGEANT"),
    "scheduler_update_task": _N("ECRITURE"),
    # ── agent/tools/search_tool ─────────────────────────────────
    "web_search": _N("LECTURE"),
    "web_search_news": _N("LECTURE"),
    # ── agent/tools/session_search_tool ─────────────────────────
    "search_past_conversations_tool": _N("LECTURE", arbitrates=True),
    # ── agent/tools/sheets_tool ─────────────────────────────────
    "sheets_add_sheet": _N("ECRITURE"),
    "sheets_append_rows": _N("ECRITURE"),
    "sheets_batch_update": _N("ENGAGEANT"),
    "sheets_create_spreadsheet": _N("ECRITURE"),
    "sheets_delete_rows": _N("ENGAGEANT"),
    "sheets_list_sheets": _N("LECTURE"),
    "sheets_raw_api_call": _N("ENGAGEANT"),
    "sheets_read_spreadsheet": _N("LECTURE"),
    "sheets_update_cells": _N("ECRITURE"),
    # ── agent/tools/ssh_tool ────────────────────────────────────
    "ssh_execute": _N("ENGAGEANT"),
    # ── agent/tools/system_diag_tool ────────────────────────────
    "system_check_channels": _N("LECTURE"),
    "system_check_llm_providers": _N("LECTURE"),
    "system_get_health": _N("LECTURE"),
    "system_get_logs": _N("LECTURE"),
    "system_list_missions": _N("LECTURE"),
    "system_list_scheduled_tasks": _N("LECTURE"),
    # ── agent/tools/system_tool ─────────────────────────────────
    "system_info": _N("LECTURE"),
    # ── agent/tools/tasks_tool ──────────────────────────────────
    "tasks_complete": _N("ECRITURE"),
    "tasks_create": _N("ECRITURE"),
    "tasks_create_tasklist": _N("ECRITURE"),
    "tasks_delete": _N("ENGAGEANT"),
    "tasks_list": _N("LECTURE"),
    "tasks_list_tasklists": _N("LECTURE"),
    "tasks_raw_api_call": _N("ENGAGEANT"),
    "tasks_update": _N("ECRITURE"),
    # ── agent/tools/telegram_tool ───────────────────────────────
    "telegram_send_message": _N("ENGAGEANT"),
    # ── agent/tools/whatsapp_tool ───────────────────────────────
    "whatsapp_send": _N("ENGAGEANT"),
    "whatsapp_send_template": _N("ENGAGEANT"),
    # ── agent/tools/youtube_tool ────────────────────────────────
    "youtube_search": _N("LECTURE"),
    "youtube_transcript": _N("LECTURE"),
    "youtube_video_info": _N("LECTURE"),
    # ── skills/builtin/briefing_skill ───────────────────────────
    "briefing_generate": _N("LECTURE", arbitrates=True),
    # ── skills/builtin/browser_skill ────────────────────────────
    "browser_click": _N("ENGAGEANT"),
    "browser_close": _N("ECRITURE"),
    "browser_fill": _N("ENGAGEANT"),
    "browser_get_text": _N("LECTURE"),
    "browser_navigate": _N("LECTURE"),
    "browser_screenshot": _N("LECTURE"),
    "browser_search_images": _N("LECTURE"),
    "browser_search_web": _N("LECTURE"),
    # ── skills/builtin/desktop_skill ────────────────────────────
    "desktop_create_dir": _N("ECRITURE"),
    "desktop_delete_file": _N("ENGAGEANT"),
    "desktop_hash_file": _N("LECTURE"),
    "desktop_list_dir": _N("LECTURE"),
    "desktop_move_file": _N("ECRITURE"),
    "desktop_read_file": _N("LECTURE"),
    "desktop_search_files": _N("LECTURE"),
    "desktop_stat_file": _N("LECTURE"),
    "desktop_write_file": _N("ECRITURE"),
    # ── skills/builtin/find_tool_skill ──────────────────────────
    "find_tool": _N("LECTURE"),
    "report_missing_capability": _N("ECRITURE", arbitrates=True),
    # ── skills/builtin/image_skill ──────────────────────────────
    "generate_image": _N("ECRITURE", arbitrates=True),
    # ── skills/builtin/mcp_generator_skill ──────────────────────
    "mcp_generate_server": _N("ECRITURE", arbitrates=True),
    "mcp_list_library": _N("LECTURE"),
    "mcp_validate_and_deploy": _N("ENGAGEANT"),
    # ── skills/builtin/mcp_model_skill ──────────────────────────
    "mcp_call_tool": _N("ENGAGEANT"),
    "mcp_connect": _N("ENGAGEANT"),
    "mcp_discover_tools": _N("LECTURE"),
    "mcp_get_prompt": _N("LECTURE"),
    "mcp_list_prompts": _N("LECTURE"),
    "mcp_list_resources": _N("LECTURE"),
    "mcp_list_servers": _N("LECTURE"),
    "mcp_propose_server": _N("ECRITURE"),
    "mcp_read_resource": _N("LECTURE"),
    "mcp_search_registry": _N("LECTURE"),
    # ── skills/builtin/news_skill ───────────────────────────────
    "news_get_headlines": _N("LECTURE", arbitrates=True),
    # ── skills/builtin/os_control_skill ─────────────────────────
    "os_click": _N("ENGAGEANT"),
    "os_get_active_window": _N("LECTURE"),
    "os_hotkey": _N("ENGAGEANT", arbitrates=True),
    "os_mouse_move": _N("ENGAGEANT"),
    "os_screenshot": _N("LECTURE"),
    "os_type_text": _N("ENGAGEANT"),
    # ── skills/builtin/trainer_skill ────────────────────────────
    "trainer_click": _N("ENGAGEANT"),
    "trainer_get_screen_size": _N("LECTURE"),
    "trainer_hotkey": _N("ENGAGEANT"),
    "trainer_move": _N("ENGAGEANT"),
    "trainer_screenshot": _N("LECTURE"),
    "trainer_start": _N("ENGAGEANT", arbitrates=True),
    "trainer_type": _N("ENGAGEANT"),
    # ── skills/builtin/translate_skill ──────────────────────────
    "translate_text": _N("LECTURE", arbitrates=True),
    # ── skills/builtin/vision_skill ─────────────────────────────
    "pdf_analyze_with_vision": _N("LECTURE", arbitrates=True),
    "vision_analyze_image": _N("LECTURE", arbitrates=True),
    # ── skills/builtin/watchdog_skill ───────────────────────────
    "watchdog_add": _N("ECRITURE"),
    "watchdog_list": _N("LECTURE"),
    "watchdog_remove": _N("ECRITURE"),
    # ── skills/builtin/weather_skill ────────────────────────────
    "weather_get": _N("LECTURE"),
}
# ──────────────────────────────────────────────────────────────────────
# Lecture de la table
# ──────────────────────────────────────────────────────────────────────


def effect_of(tool_name: str) -> str | None:
    """L'effet d'un outil, ou ``None`` s'il n'est pas classé."""
    entry = TOOL_NATURE.get(tool_name)
    return entry.effect if entry else None


def arbitrates(tool_name: str) -> bool:
    """L'outil tranche-t-il des choix de forme à la place de l'utilisateur ?"""
    entry = TOOL_NATURE.get(tool_name)
    return bool(entry and entry.arbitrates)


def requires_approval(tool_name: str) -> bool:
    """Cet outil devrait-il demander l'accord de l'utilisateur ?

    Quatre sources, dans cet ordre — **l'ordre est la sécurité** :
        1. il est déjà protégé aujourd'hui → oui, quoi que disent la table
           et les dispenses ;
        2. il est explicitement dispensé, avec sa raison → non ;
        3. il est classé ``ENGAGEANT`` → oui ;
        4. il n'est pas classé du tout → **oui**, on échoue FERMÉ.

    Le premier cas passe AVANT les dispenses : sans cela, ajouter un nom à
    ``APPROVAL_WAIVED`` suffirait à retirer une protection existante, ce qui
    rouvrirait par la fenêtre la porte que ``ALREADY_GUARDED`` ferme.

    Le dernier cas est ce qui force à classer un nouvel outil : tant qu'il ne
    l'est pas, il est traité comme engageant. Un faux positif coûte une
    question à l'utilisateur ; un faux négatif envoie un message ou supprime
    des données sans qu'il l'ait voulu.
    """
    if tool_name in ALREADY_GUARDED:
        return True
    if tool_name in APPROVAL_WAIVED:
        return False
    entry = TOOL_NATURE.get(tool_name)
    if entry is None:
        logger.info(
            "tool_nature : %r non classé — traité comme engageant", tool_name,
        )
        return True
    return entry.effect == "ENGAGEANT"


def unguarded_engaging_tools() -> list[str]:
    """Les actes engageants qu'aucune autorisation ne protège aujourd'hui.

    Un outil ne compte comme trou que s'il n'est NI gardé NI dispensé : une
    dispense est une décision explicite et motivée, pas un oubli. Les confondre
    ferait crier ce contrôle en permanence, et un contrôle qui crie toujours
    finit par ne plus être lu.

    ⚠️ Au lot 1, cette fonction rendait 26 noms dont ``ssh_execute`` et
    ``gmail_empty_trash`` — sur une mesure FAUSSE : ``ALREADY_GUARDED`` était
    bâti sur ``hitl_descriptions.py`` (6 outils) au lieu de la garde réelle
    (38). Le vrai trou était de 18 sur le périmètre complet. Il est fermé
    depuis le lot 3 ; cette liste doit rester vide.
    """
    return sorted(
        name for name, entry in TOOL_NATURE.items()
        if entry.effect == "ENGAGEANT"
        and name not in ALREADY_GUARDED
        and name not in APPROVAL_WAIVED
    )


def mute_arbitrating_tools(params_by_tool: dict[str, list[str]] | None = None) -> list[str]:
    """Les outils qui arbitrent sans pouvoir recevoir d'exigence.

    C'est le défaut exact de ``pdf_to_docx(source, output_name)`` avant #294 :
    l'outil tranchait la structure du document, et ce que l'utilisateur avait
    écrit n'avait aucun chemin pour l'atteindre. Cinq essais de reformulation
    l'ont montré.

    Sans ``params_by_tool``, les paramètres sont relus à la source. Mesuré :
    **3 outils** seulement — le trou était isolé, pas systémique.
    """
    params_by_tool = params_by_tool if params_by_tool is not None else _declared_params()
    return sorted(
        name for name, entry in TOOL_NATURE.items()
        if entry.arbitrates
        and not (set(params_by_tool.get(name, ())) & _INTENT_PARAMS)
    )


def _declared_params() -> dict[str, list[str]]:
    """Les paramètres de chaque outil, relus depuis l'AST.

    On lit la source plutôt qu'on importe : importer tirerait tout le graphe de
    dépendances des outils (Google, navigateur, MCP) pour une question qui ne
    porte que sur des noms d'arguments.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).parent / "tools"
    out: dict[str, list[str]] = {}
    for f in root.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text())
        except Exception as exc:  # noqa: BLE001 — un fichier illisible n'est pas un outil
            logger.debug("tool_nature : %s illisible (%s)", f.name, exc)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(getattr(d, "id", getattr(d, "attr", None)) == "tool"
                       for d in node.decorator_list):
                continue
            out[node.name] = [a.arg for a in node.args.args] + [
                a.arg for a in node.args.kwonlyargs
            ]
    return out


__all__ = [
    "ALREADY_GUARDED",
    "APPROVAL_WAIVED",
    "EFFECTS",
    "TOOL_NATURE",
    "arbitrates",
    "effect_of",
    "mute_arbitrating_tools",
    "requires_approval",
    "unguarded_engaging_tools",
]
