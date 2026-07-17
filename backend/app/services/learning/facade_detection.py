# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/facade_detection.py
# @brief      Boucle d'auto-diagnostic J2 — heuristiques de détection du
#             « succès de façade » (maillon 1). Logique PURE, sans DB.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""Détection de « succès de façade » — boucle d'auto-diagnostic, jalon J2.

Maillon 1 de la design note §4 : inverser la charge de la preuve. Une
exécution déclarée « réussie » est tenue pour DOUTEUSE dès qu'un signal
faible se lève. Ce module ne fait QUE produire la liste de codes de
signaux ; la persistance (verdict ``dubious``) reste dans
:func:`app.services.learning.signals.record_execution_outcome` via
:func:`classify_outcome`.

Heuristiques (composables, par tier de confiance) :
  - ``no_write_effect``       : le goal demande une mutation externe forte
                                (créer / alimenter / écrire / envoyer à un
                                tiers…) mais AUCUN outil d'écriture n'a tourné.
  - ``fallback``              : un fallback provider a eu lieu pendant
                                l'exécution (corrélé en base — voir
                                outcome_recording).
  - ``claimed_no_tool``       : le LLM a affirmé « je n'ai pas d'outil pour… »
                                — NON FIABLE (leçon : trou de binding fréquent),
                                traité comme SUSPICION, pas comme vérité.
  - ``suspicious_delegation`` : l'agent a créé une tâche planifiée alors que
                                le goal ne demandait pas de planification.
  - ``recursion_limit``       : la boucle a atteint la limite de récursion.

Tout est CONSERVATEUR (anti-pattern §8 : « crier au loup » tue l'adhésion).
En particulier l'intention d'écriture exclut le simple « envoie-moi » (la
livraison à l'utilisateur passe par le canal, pas par un outil d'écriture).
"""
from __future__ import annotations

import re
from typing import Any

# Codes de signaux faibles (alimentent ExecutionOutcome.signals).
SIGNAL_NO_WRITE_EFFECT = "no_write_effect"
SIGNAL_FALLBACK = "fallback"
SIGNAL_CLAIMED_NO_TOOL = "claimed_no_tool"
SIGNAL_SUSPICIOUS_DELEGATION = "suspicious_delegation"
SIGNAL_RECURSION_LIMIT = "recursion_limit"


# ─────────────────────────────────────────────────────────────────────────
# Outils d'écriture (effet observable). DISTINCT de
# security_filter.ALWAYS_CRITICAL_TOOLS (qui mesure la CRITICITÉ) : une
# écriture n'est pas forcément critique (drive_create_file), une suppression
# critique EST une écriture. On veut la détection d'écriture la plus GÉNÉREUSE
# possible — rater une écriture ferait FAUSSEMENT lever « no_write_effect ».
# ─────────────────────────────────────────────────────────────────────────
_WRITE_TOOLS_EXPLICIT: frozenset[str] = frozenset({
    # Gmail — envois / mutations
    "gmail_send_email", "gmail_reply_email", "gmail_send_with_attachment",
    "gmail_create_draft", "gmail_trash_emails", "gmail_trash_by_query",
    "gmail_trash_by_category", "gmail_empty_trash", "gmail_batch_modify",
    "gmail_update_settings",
    # Drive
    "drive_upload_local_file", "drive_create_file", "drive_create_folder",
    "drive_delete_file", "drive_share_file", "drive_move_file",
    "drive_rename_file", "drive_copy_file",
    # Docs / Sheets
    "docs_create", "docs_append", "docs_insert_text", "docs_replace_text",
    "sheets_create", "sheets_append_row", "sheets_update_cells",
    "sheets_write", "sheets_clear",
    # Calendar / Tasks / Contacts
    "calendar_create_event", "calendar_update_event", "calendar_delete_event",
    "tasks_create", "tasks_update", "tasks_delete",
    "contacts_create", "contacts_update", "contacts_delete",
    "contacts_batch_operations",
    # Desktop (écritures locales)
    "desktop_write_file", "desktop_move_file", "desktop_create_dir",
    "desktop_delete_file",
    # Communications externes
    "whatsapp_send", "whatsapp_send_template",
    # Planification (crée une tâche)
    "system_create_scheduled_task", "scheduler_create_task",
})

# Repli par motif de NOM : un outil dont le nom contient un de ces fragments
# est traité comme écriture même s'il n'est pas énuméré. Fragments choisis sans
# ambiguïté de mutation. Underscore sur "set_"/"add_" pour ne pas matcher
# "settings"/"address".
_WRITE_NAME_PARTS: tuple[str, ...] = (
    "send", "create", "update", "delete", "append", "upload",
    "_write", "write_", "insert", "replace", "remove", "_move", "move_",
    "rename", "share", "_save", "save_", "trash", "add_", "_add",
    "set_", "post_", "publish", "_put",
)

# Outils de PLANIFICATION (pour la délégation suspecte).
_SCHEDULING_TOOLS: frozenset[str] = frozenset({
    "system_create_scheduled_task", "scheduler_create_task",
})


def is_write_tool(name: str | None) -> bool:
    """Un outil produit-il un effet d'écriture observable ? Généreux par
    conception (minimise les fausses alertes « no_write_effect »)."""
    if not name:
        return False
    n = name.lower()
    if n in _WRITE_TOOLS_EXPLICIT:
        return True
    return any(p in n for p in _WRITE_NAME_PARTS)


# ─────────────────────────────────────────────────────────────────────────
# Intentions (détection sur le goal / le texte final)
# ─────────────────────────────────────────────────────────────────────────

# Intention d'écriture EXTERNE FORTE. Exclut volontairement le simple
# « envoie » seul : sur une tâche planifiée « envoie-moi le résumé » est
# satisfait par la LIVRAISON canal, pas par un outil d'écriture — l'inclure
# ferait crier au loup. On garde les verbes de mutation francs.
_WRITE_INTENT = re.compile(
    r"\b("
    # FR
    r"cr[ée]e?[zsr]?|cr[ée]er|"
    r"alimente?[zsr]?|alimenter|remplis|remplir|compl[èe]te?[zsr]?|compl[ée]ter|"
    r"[ée]cris|[ée]crire|r[ée]dige?[zsr]?|r[ée]diger|"
    r"ajoute?[zsr]?|ajouter|ins[èe]re?[zsr]?|ins[ée]rer|"
    r"mets?\s+[àa]\s+jour|mettre\s+[àa]\s+jour|modifie?[zsr]?|modifier|"
    r"supprime?[zsr]?|supprimer|efface?[zsr]?|effacer|"
    r"t[ée]l[ée]charge?[zsr]?|t[ée]l[ée]charger|upload[e]?[zr]?|"
    r"sauvegarde?[zsr]?|sauvegarder|enregistre?[zsr]?|enregistrer|"
    r"partage?[zsr]?|partager|publie?[zsr]?|publier|"
    # EN
    r"create|write|fill|populate|append|insert|update|modify|"
    r"delete|remove|upload|download|save|share|publish"
    r")\b",
    re.IGNORECASE,
)

# Affirmations « je n'ai pas d'outil ». NON FIABLE → suspicion de gap, jamais
# pris pour argent comptant (leçon find_tool : trou de binding fréquent).
_NO_TOOL_CLAIM = re.compile(
    r"("
    r"je\s+n['e]?\s*ai\s+pas\s+(d['e]?\s*|l['e]?\s*|les\s+)?outil|"
    r"pas\s+d['e]?\s*outil\s+(pour|disponible|adapt|qui)|"
    r"aucun\s+outil\s+(pour|disponible|ne\s+)|"
    r"je\s+ne\s+(peux|dispose)\s+pas\s+d['e]?\s*outil|"
    r"je\s+n['e]?\s*ai\s+aucun\s+(moyen|outil)|"
    r"outil\s+(non\s+disponible|manquant|indisponible)|"
    r"i\s+(don'?t|do\s+not)\s+have\s+(a\s+|the\s+|any\s+)?tool|"
    r"no\s+tool\s+(available|for|to)|"
    r"there\s+(is|'?s)\s+no\s+tool"
    r")",
    re.IGNORECASE,
)

# Le goal demandait-il EXPLICITEMENT une planification ? (sinon créer une
# tâche planifiée = délégation suspecte).
_SCHEDULE_INTENT = re.compile(
    r"\b("
    r"planifie?[zsr]?|planifier|programme?[zsr]?|programmer|"
    r"chaque\s+(jour|matin|semaine|mois|lundi|mardi|mercredi|jeudi|vendredi)|"
    r"tous\s+les\s+(jours|matins|lundis)|toutes\s+les\s+(semaines|heures)|"
    r"r[ée]current|r[ée]p[ée]te|rappelle[- ]?moi|rappel|"
    r"schedule|every\s+(day|morning|week|monday)|daily|weekly|recurring|remind\s+me"
    r")\b",
    re.IGNORECASE,
)


# Résultat explicitement VIDE (« aucun spam », « rien à traiter », « 0
# facture ») — marqueur POSITIF d'un jour sans travail pour les tâches à
# écriture CONDITIONNELLE (C1b, audit 16/07 §6.9). La négation est portée
# par le marqueur lui-même, jamais déduite : « 12 emails supprimés » ne
# matche pas ici, il reste traité comme un claim sans preuve.
_EMPTY_OUTCOME = re.compile(
    r"\b("
    r"aucun[e]?s?\s+(?:nouveau[x]?|nouvelle[s]?|e-?mail[s]?|mail[s]?|"
    r"message[s]?|facture[s]?|spam[s]?|newsletter[s]?|[ée]l[ée]ment[s]?|"
    r"r[ée]sultat[s]?|action[s]?|item[s]?|courriel[s]?)|"
    r"rien\s+(?:[àa]\s+(?:faire|traiter|nettoyer|signaler|supprimer|archiver)|"
    r"de\s+nouveau|trouv[ée]|d[ée]tect[ée])|"
    r"pas\s+de\s+(?:nouveau[x]?|nouvelle[s]?|spam[s]?|facture[s]?|"
    r"e-?mail[s]?|mail[s]?|message[s]?)|"
    r"0\s+(?:e-?mail[s]?|mail[s]?|message[s]?|facture[s]?|spam[s]?|r[ée]sultat[s]?)|"
    r"n[’']a\s+(?:rien|trouv[ée]\s+aucun)|"
    r"no\s+(?:new\s+)?(?:e-?mails?|messages?|invoices?|items?|results?|spam)|"
    r"nothing\s+(?:to\s+(?:do|clean|process|report)|found|new)"
    r")",
    re.IGNORECASE,
)


def detect_write_intent(text: str | None) -> bool:
    """Le texte exprime-t-il une intention d'écriture externe forte ?"""
    return bool(text) and bool(_WRITE_INTENT.search(text))


def detect_empty_outcome(text: str | None) -> bool:
    """Le texte final déclare-t-il explicitement un résultat vide ?"""
    return bool(text) and bool(_EMPTY_OUTCOME.search(text))


def detect_claimed_no_tool(text: str | None) -> bool:
    """Le texte affirme-t-il « je n'ai pas d'outil » ? (suspicion, pas vérité)"""
    return bool(text) and bool(_NO_TOOL_CLAIM.search(text))


def asked_to_schedule(text: str | None) -> bool:
    """Le goal demandait-il une planification ?"""
    return bool(text) and bool(_SCHEDULE_INTENT.search(text))


def tools_called_from_messages(messages: Any) -> list[str]:
    """Extrait les noms d'outils appelés depuis un historique de messages
    LangChain (AIMessage.tool_calls + ToolMessage.name). Best-effort,
    tolérant aux formes dict/objet."""
    names: list[str] = []
    for m in (messages or []):
        tcs = getattr(m, "tool_calls", None)
        if tcs:
            for tc in tcs:
                n = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if n:
                    names.append(str(n))
        # ToolMessage porte le nom de l'outil exécuté
        is_tool_msg = (
            getattr(m, "type", None) == "tool"
            or m.__class__.__name__ == "ToolMessage"
        )
        if is_tool_msg:
            n = getattr(m, "name", None)
            if n:
                names.append(str(n))
    return names


def compute_facade_signals(
    *,
    goal: str | None,
    final_text: str | None,
    tools_called: list[str] | None,
    fallback_occurred: bool = False,
    recursion_hit: bool = False,
) -> list[str]:
    """Compose la liste des signaux faibles d'une exécution déclarée réussie.

    Liste vide → l'exécution reste ``succeeded``. Au moins un signal →
    ``dubious`` (via :func:`classify_outcome`).
    """
    signals: list[str] = []
    tools = {t for t in (tools_called or []) if t}

    # 1. Réussi sans effet observable.
    #    C1b (audit 16/07 §6.9) — calibration « jour vide » : une tâche à
    #    écriture CONDITIONNELLE (« supprime le spam », « traite les
    #    factures ») qui n'a rien trouvé à muter est un succès légitime, pas
    #    une façade — 46,5 % des exécutions déclarées réussies étaient
    #    marquées douteuses, toutes via ce signal, ce qui décrédibilisait la
    #    mesure. Suppression du signal UNIQUEMENT sur preuve positive : des
    #    outils ont réellement tourné ET le texte final déclare explicitement
    #    un résultat vide. « J'ai tout nettoyé » sans outil d'écriture reste
    #    douteux (la façade d'origine) ; « aucun spam » sans avoir cherché
    #    aussi (pas regardé).
    if detect_write_intent(goal) and not any(is_write_tool(t) for t in tools):
        if not (tools and detect_empty_outcome(final_text)):
            signals.append(SIGNAL_NO_WRITE_EFFECT)

    # 2. Fallback déclenché (corrélé en amont).
    if fallback_occurred:
        signals.append(SIGNAL_FALLBACK)

    # 3. Faux « pas d'outil ».
    if detect_claimed_no_tool(final_text):
        signals.append(SIGNAL_CLAIMED_NO_TOOL)

    # 4. Délégation suspecte : a créé une tâche planifiée sans qu'on le demande.
    if (tools & _SCHEDULING_TOOLS) and not asked_to_schedule(goal):
        signals.append(SIGNAL_SUSPICIOUS_DELEGATION)

    # 5. Limite de récursion atteinte.
    if recursion_hit:
        signals.append(SIGNAL_RECURSION_LIMIT)

    return signals
