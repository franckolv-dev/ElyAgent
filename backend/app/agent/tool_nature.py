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
La classification des 154 outils l'a montré : les deux questions sont
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
Par le modèle cloud sur les 154 outils réels — c'est du jugement à grande
échelle, donc exactement le cas d'usage de la règle qu'elle encode. Puis relue
par croisement mécanique avec les noms d'outils, ce qui a fait apparaître les
trois ``gmail_trash_*`` (voir ``ALREADY_GUARDED``).

⚠️ Ici on échoue FERMÉ — l'inverse de la boucle de conformité
--------------------------------------------------------------
Pour la conformité, un doute laisse passer : une vérification cassée ne doit
jamais retenir la réponse de l'utilisateur. Pour l'autorisation, c'est
l'inverse. Un faux positif coûte une question ; un faux négatif envoie un
message ou supprime des données sans que l'utilisateur l'ait voulu.
L'asymétrie est trop forte pour laisser passer le doute.

Ce que ce module ne fait PAS
-----------------------------
Il ne change aucun comportement. Étendre l'autorisation aux 26 actes engageants
non protégés est le lot 3 — et ça se décide en regardant la liste que
``unguarded_engaging_tools()`` produit, pas en la subissant.
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


# Les outils placés sous autorisation AVANT ce lot, par décision de Franck.
#
# ⚠️ Cette liste PRIME sur la table. La classification a placé les trois
# ``gmail_trash_*`` en ECRITURE — raisonnement défendable, la corbeille Gmail
# est réversible — mais ils sont protégés aujourd'hui. Une table de données ne
# doit jamais pouvoir DÉPROTÉGER quelque chose : le sens de lecture est
# toujours « ajouter une garde », jamais « en retirer une ».
ALREADY_GUARDED: Final[frozenset[str]] = frozenset({
    "gmail_reply_email",
    "gmail_send_email",
    "gmail_send_with_attachment",
    "gmail_trash_by_category",
    "gmail_trash_by_query",
    "gmail_trash_emails",
})

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
    # ── agentic_rag_tool ──────────────────────────────────────────
    "smart_knowledge_query": _N("LECTURE"),
    # ── browser_extension_tool ────────────────────────────────────
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
    # ── calendar_tool ─────────────────────────────────────────────
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
    # ── contacts_tool ─────────────────────────────────────────────
    "contacts_batch_operations": _N("ENGAGEANT"),
    "contacts_create": _N("ECRITURE"),
    "contacts_delete": _N("ENGAGEANT"),
    "contacts_get": _N("LECTURE"),
    "contacts_list": _N("LECTURE"),
    "contacts_raw_api_call": _N("ENGAGEANT"),
    "contacts_search": _N("LECTURE"),
    "contacts_update": _N("ECRITURE"),
    # ── delegate_tool ─────────────────────────────────────────────
    "delegate": _N("LECTURE", arbitrates=True),
    # ── docs_tool ─────────────────────────────────────────────────
    "docs_append_text": _N("ECRITURE"),
    "docs_batch_update": _N("ECRITURE"),
    "docs_create_document": _N("ECRITURE"),
    "docs_insert_table": _N("ECRITURE"),
    "docs_raw_api_call": _N("ENGAGEANT"),
    "docs_read_document": _N("LECTURE"),
    "docs_replace_text": _N("ECRITURE"),
    # ── drive_tool ────────────────────────────────────────────────
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
    # ── fibonacci_tool ────────────────────────────────────────────
    "fibonacci": _N("LECTURE"),
    # ── file_tool ─────────────────────────────────────────────────
    "analyze_file": _N("LECTURE", arbitrates=True),
    # ── github_tool ───────────────────────────────────────────────
    "github_notifications": _N("LECTURE"),
    "github_repo_stats": _N("LECTURE"),
    "github_traffic_stats": _N("LECTURE"),
    # ── gmail_tool ────────────────────────────────────────────────
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
    # ── image_tool ────────────────────────────────────────────────
    "generate_image": _N("ECRITURE", arbitrates=True),
    # ── knowledge_tool ────────────────────────────────────────────
    "knowledge_list": _N("LECTURE"),
    "knowledge_search": _N("LECTURE"),
    # ── learned_skills_tool ───────────────────────────────────────
    "skill_view": _N("LECTURE"),
    # ── maps_tool ─────────────────────────────────────────────────
    "maps_directions": _N("LECTURE"),
    "maps_geocode": _N("LECTURE"),
    "maps_nearby": _N("LECTURE"),
    "maps_reverse_geocode": _N("LECTURE"),
    # ── memgpt_tool ───────────────────────────────────────────────
    "memory_archive": _N("ECRITURE"),
    "memory_recent": _N("LECTURE"),
    "memory_search": _N("LECTURE"),
    "memory_view_profile": _N("LECTURE"),
    # ── memory_recall_tool ────────────────────────────────────────
    "memory_recall": _N("LECTURE"),
    # ── memory_tool ───────────────────────────────────────────────
    "save_constraint": _N("ECRITURE"),
    "save_user_preference": _N("ECRITURE"),
    # ── notes_tool ────────────────────────────────────────────────
    "notes_create": _N("ECRITURE"),
    "notes_delete": _N("ENGAGEANT"),
    "notes_list": _N("LECTURE"),
    "notes_read": _N("LECTURE"),
    "notes_search": _N("LECTURE"),
    "notes_update": _N("ECRITURE"),
    # ── orchestrate_tool ──────────────────────────────────────────
    "orchestrate": _N("ECRITURE", arbitrates=True),
    # ── pdf_tool ──────────────────────────────────────────────────
    "pdf_info": _N("LECTURE"),
    "pdf_read": _N("LECTURE"),
    "pdf_to_docx": _N("ECRITURE", arbitrates=True),
    # ── python_tool ───────────────────────────────────────────────
    "python_execute": _N("ECRITURE"),
    # ── qrcode_tool ───────────────────────────────────────────────
    "qrcode_generate": _N("ECRITURE", arbitrates=True),
    "qrcode_generate_vcard": _N("ECRITURE", arbitrates=True),
    "qrcode_generate_wifi": _N("ECRITURE", arbitrates=True),
    # ── reversible_tool ───────────────────────────────────────────
    "list_revertible_actions": _N("LECTURE"),
    "revert_action": _N("ECRITURE"),
    "undo_last_action": _N("ECRITURE"),
    # ── scheduler_tool ────────────────────────────────────────────
    "scheduler_create_task": _N("ECRITURE"),
    "scheduler_delete_task": _N("ENGAGEANT"),
    "scheduler_list_tasks": _N("LECTURE"),
    "scheduler_run_task": _N("ENGAGEANT"),
    "scheduler_update_task": _N("ECRITURE"),
    # ── search_tool ───────────────────────────────────────────────
    "web_search": _N("LECTURE"),
    "web_search_news": _N("LECTURE"),
    # ── session_search_tool ───────────────────────────────────────
    "search_past_conversations_tool": _N("LECTURE", arbitrates=True),
    # ── sheets_tool ───────────────────────────────────────────────
    "sheets_add_sheet": _N("ECRITURE"),
    "sheets_append_rows": _N("ECRITURE"),
    "sheets_batch_update": _N("ENGAGEANT"),
    "sheets_create_spreadsheet": _N("ECRITURE"),
    "sheets_delete_rows": _N("ENGAGEANT"),
    "sheets_list_sheets": _N("LECTURE"),
    "sheets_raw_api_call": _N("ENGAGEANT"),
    "sheets_read_spreadsheet": _N("LECTURE"),
    "sheets_update_cells": _N("ECRITURE"),
    # ── ssh_tool ──────────────────────────────────────────────────
    "ssh_execute": _N("ENGAGEANT"),
    # ── system_diag_tool ──────────────────────────────────────────
    "system_check_channels": _N("LECTURE"),
    "system_check_llm_providers": _N("LECTURE"),
    "system_get_health": _N("LECTURE"),
    "system_get_logs": _N("LECTURE"),
    "system_list_missions": _N("LECTURE"),
    "system_list_scheduled_tasks": _N("LECTURE"),
    # ── system_tool ───────────────────────────────────────────────
    "system_info": _N("LECTURE"),
    # ── tasks_tool ────────────────────────────────────────────────
    "tasks_complete": _N("ECRITURE"),
    "tasks_create": _N("ECRITURE"),
    "tasks_create_tasklist": _N("ECRITURE"),
    "tasks_delete": _N("ENGAGEANT"),
    "tasks_list": _N("LECTURE"),
    "tasks_list_tasklists": _N("LECTURE"),
    "tasks_raw_api_call": _N("ENGAGEANT"),
    "tasks_update": _N("ECRITURE"),
    # ── telegram_tool ─────────────────────────────────────────────
    "telegram_send_message": _N("ENGAGEANT"),
    # ── whatsapp_tool ─────────────────────────────────────────────
    "whatsapp_send": _N("ENGAGEANT"),
    "whatsapp_send_template": _N("ENGAGEANT"),
    # ── youtube_tool ──────────────────────────────────────────────
    "youtube_search": _N("LECTURE"),
    "youtube_transcript": _N("LECTURE"),
    "youtube_video_info": _N("LECTURE"),}


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

    Trois sources, dans cet ordre :
        1. il est déjà protégé aujourd'hui → oui, quoi que dise la table ;
        2. il est classé ``ENGAGEANT`` → oui ;
        3. il n'est pas classé du tout → **oui**, on échoue FERMÉ.

    Le troisième cas est ce qui force à classer un nouvel outil : tant qu'il ne
    l'est pas, il est traité comme engageant. Un faux positif coûte une
    question à l'utilisateur ; un faux négatif envoie un message ou supprime
    des données sans qu'il l'ait voulu.
    """
    if tool_name in ALREADY_GUARDED:
        return True
    entry = TOOL_NATURE.get(tool_name)
    if entry is None:
        logger.info(
            "tool_nature : %r non classé — traité comme engageant", tool_name,
        )
        return True
    return entry.effect == "ENGAGEANT"


def unguarded_engaging_tools() -> list[str]:
    """Les actes engageants qu'aucune autorisation ne protège aujourd'hui.

    Mesuré le 28/07/2026 : **26 outils**, dont ``ssh_execute``,
    ``gmail_empty_trash`` (« DEFINITIVELY delete ») et sept ``*_raw_api_call``
    qui peuvent appeler n'importe quelle méthode des API Google. Plusieurs de
    ces outils portent dans leur propre docstring « ALWAYS ask user
    confirmation » — c'est une consigne au modèle, pas un garde-fou : rien ne
    l'applique si le modèle passe outre.

    Combler ce trou est le lot 3. Ce module se contente de le rendre visible.
    """
    return sorted(
        name for name, entry in TOOL_NATURE.items()
        if entry.effect == "ENGAGEANT" and name not in ALREADY_GUARDED
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
    "EFFECTS",
    "TOOL_NATURE",
    "arbitrates",
    "effect_of",
    "mute_arbitrating_tools",
    "requires_approval",
    "unguarded_engaging_tools",
]
