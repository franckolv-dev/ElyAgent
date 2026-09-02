# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_tool_families.py
# @brief      Missions autonomes J2 — mapping outil → famille de mandat.
# @license    Elastic License 2.0
# =============================================================================
"""Rattache un nom d'outil à une famille de mandat (cadrage D1).

Le mandat autorise des FAMILLES (``email``, ``drive``…), pas des outils un
par un. Ce module traduit ``gmail_send_email`` → ``email`` etc., par
PRÉFIXE (les noms d'outils sont disciplinés : ``<famille>_<verbe>``). Une
famille inconnue renvoie ``None`` → le gate escalade (fail-closed).

Fermé À DESSEIN, aligné sur ``MANDATE_TOOL_FAMILIES`` /
``MANDATE_FORBIDDEN_FAMILIES`` (mission_spec, J1). Ajouter un préfixe = une
ligne.
"""
from __future__ import annotations

from typing import Final

# Préfixe de nom d'outil → famille. Couvre le catalogue réel (toolset_profiles
# + gmail/drive/calendar/... tools). Les familles cibles sont celles du
# contrat J1 (autorisables OU interdites).
_PREFIX_TO_FAMILY: Final[dict[str, str]] = {
    # ── Familles autorisables ──
    "gmail": "email",
    "calendar": "calendar",
    "contacts": "contacts",
    "tasks": "tasks",
    "drive": "drive",
    "docs": "docs",
    "sheets": "sheets",
    "browser": "web",
    "web": "web",
    "weather": "web",
    "translate": "web",
    "desktop": "files",
    "vision": "vision",
    "generate": "media",       # generate_image
    "maps": "maps",
    "youtube": "youtube",
    "github": "github",
    "pdf": "pdf",
    "notes": "notes",
    "memory": "memory",
    "knowledge": "knowledge",
    "smart": "knowledge",      # smart_knowledge_query
    "telegram": "messaging",
    "scheduler": "scheduler",
    # ── Noyau interdit (mappé pour être refusé sec par le gate) ──
    "ssh": "ssh",
    "vault": "vault",
    "mcp": "mcp",
    "os": "system",
    "admin": "admin",
}

# Substrat de l'agent : outils de découverte / lecture pure, sans effet sur
# les données de l'utilisateur ni le monde extérieur. TOUJOURS autorisés sous
# mandat (sinon une mission autonome ne peut même pas découvrir ses outils ni
# consulter sa mémoire pour décider). N'inclut AUCUN write ni action externe.
MANDATE_UNIVERSAL_TOOLS: Final[frozenset[str]] = frozenset({
    "find_tool",                       # filet de sécurité : tirer un outil du catalogue
    "skill_view",                      # lire un playbook appris
    "memory_search", "memory_view_profile", "memory_recall",
    "knowledge_search", "knowledge_list", "smart_knowledge_query",
    "notes_search", "notes_list",
    "search_past_conversations_tool",
})

# Escape-hatches SANS annulation possible (pas de compensation au journal
# réversible) : escaladent TOUJOURS au HITL humain, même si leur famille est
# autorisée. `*_raw_api_call` = appel d'API arbitraire (contourne le HITL
# outil) ; `gmail_empty_trash` = purge définitive (aucune API ne restaure).
MANDATE_ESCALATE_ALWAYS: Final[frozenset[str]] = frozenset({
    "gmail_empty_trash",
    "gmail_raw_api_call",
    "calendar_raw_api_call",
    "drive_raw_api_call",
    "docs_raw_api_call",
    "sheets_raw_api_call",
    "tasks_raw_api_call",
    "contacts_raw_api_call",
})


def tool_family(tool_name: str) -> str | None:
    """Famille de mandat d'un outil, ou ``None`` si non rattaché.

    ``None`` couvre les outils méta/universels (find_tool,
    skill_view, save_*) et tout outil futur non mappé — le gate les
    ESCALADE (fail-closed) plutôt que de les autoriser implicitement."""
    if not tool_name:
        return None
    prefix = tool_name.split("_", 1)[0]
    return _PREFIX_TO_FAMILY.get(prefix)
