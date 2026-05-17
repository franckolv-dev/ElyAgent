# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/completion_guard.py
# @brief      Anti-hallucination completion guard — detects when the LLM
#             claims a destructive action was performed without actually
#             calling the corresponding tool in the current turn.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.1.0
# =============================================================================
"""Detects "claim of completion" without corresponding tool execution.

Origin of this guard (2026-05-17 incident)
-------------------------------------------
After 4-5 cycles of:

    user: "supprime ces 50 mails"
    assistant: tool_call(gmail_trash_by_query) → tool_result → "supprimé"

every LLM (DeepSeek v4-flash after ~3 cycles, Mistral Small 4 after ~5-6
cycles) starts shortcutting the pattern: it outputs the final "supprimé"
text directly, **without** the tool_call. This is documented as
"in-context completion shortcutting" — recent turns get
disproportionate attention vs the system prompt (RÈGLE 0 included).

The user sees "supprimé" in the UI, no HITL prompt appeared, no tool ran.
Nothing was actually deleted. This is the worst-class bug for ELY because
it silently breaks the core promise: HITL before irreversible action.

How this guard works
--------------------
A pure detection function that takes:
  - the assistant's text response (after deanonymization & filters)
  - the list of tool names invoked in this turn
  - (optionally) the user's last message, for finer detection

…and returns a verdict object that the caller can use to:
  - replace the response with an honest warning
  - emit a frontend event so the UI shows a red badge
  - log a structured audit line for post-mortem
  - count it in metrics

It does NOT re-prompt the LLM. That's a V2 enhancement — V1 just blocks
the lie and tells the user honestly.

Design constraints
------------------
- LLM-agnostic (works regardless of provider)
- Language-agnostic (catches FR + EN completion markers)
- Zero false-negative on the patterns Franck saw (deletion, email send)
- Tolerable false-positive rate (better to flag a real success once than
  to silently confirm a fake one)
- < 1ms per call (string regex only, no LLM call)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Critical tools — kept here as a local snapshot of the destructive
# subset, to avoid a hard import on security_filter at call time. Mirror
# of ``app.services.security_filter.ALWAYS_CRITICAL_TOOLS`` (destructive
# subset only — we don't guard ``ssh_execute`` etc. because those don't
# typically trigger "voilà supprimé" assistant responses).
# ──────────────────────────────────────────────────────────────────────

DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
    # Email destructive ops
    "gmail_trash_emails",
    "gmail_trash_by_category",
    "gmail_trash_by_query",
    "gmail_send_email",
    "gmail_reply_email",
    "gmail_send_with_attachment",
    "gmail_send_with_local_attachment",
    "gmail_send_with_drive_attachment",
    "gmail_empty_trash",
    "gmail_update_settings",
    # Calendar destructive ops
    "calendar_create_event",
    "calendar_delete_event",
    "calendar_update_event",
    # Drive destructive ops
    "drive_delete_file",
    "drive_create_file",
    "drive_move_file",
    "drive_rename_file",
    "drive_share_file",
    # Tasks destructive ops
    "tasks_create",
    "tasks_delete",
    "tasks_complete",
    # Contacts destructive ops
    "contacts_create",
    "contacts_delete",
    "contacts_update",
    # Desktop destructive ops
    "desktop_delete_file",
    "desktop_write_file",
    "desktop_move_file",
    # WhatsApp / Telegram / Discord / Slack send
    "whatsapp_send_message",
    "telegram_send_message",
    "discord_send_message",
    "slack_send_message",
    # Notes / Docs / Sheets
    "notes_create",
    "notes_delete",
    "docs_create",
    "docs_update",
    "sheets_create",
    "sheets_append_row",
    # Scheduler
    "scheduler_create_task",
    "scheduler_delete_task",
    "scheduler_update_task",
    # Memory & knowledge state-changing tools.
    # FIX 2026-05-17 evening : initially the guard only knew about
    # *destructive* tools (delete email, etc.). But « j'ai enregistré
    # dans ma mémoire » is ALSO a state-change claim that should be
    # backed by a real tool call. Without these, the agent saying
    # « j'ai enregistré le Dr Untel » without calling memory_archive
    # was correctly flagged as hallucination — but if the agent DID
    # call memory_archive, the guard wouldn't recognise it as backing.
    # Added so both cases (hallucinated AND real archive) are handled
    # correctly.
    "memory_archive",
    "save_user_preference",
    "save_constraint",
    "knowledge_save",
    "notes_update",
    "notes_delete",
})


# ──────────────────────────────────────────────────────────────────────
# Completion-claim regex patterns
# ──────────────────────────────────────────────────────────────────────
#
# Each entry is (regex, label) — label is for audit logging.
# Patterns must match WORD BOUNDARIES to avoid catching innocent strings
# like "supprimerait" (conditional, not assertion of past completion).
# Patterns are case-insensitive and tolerate optional accents/punctuation.

# Past-tense completion markers (assertion that an action just happened)
_FR_COMPLETION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "ont été supprimés", "a été supprimé", "ont été envoyés"
    (re.compile(
        r"\b(ont|a|sont|est|été)\s+été\s+"
        r"(supprim|envoy|cré|enregistr|déplacé|déplaces?|sauveg|"
        r"vidés?|vidée?|effacés?|effacée?|archivés?|archivée?|"
        r"plani|programm|modifi|mis\s+à\s+jour|transfér)",
        re.IGNORECASE,
    ), "fr.passive_past"),
    # "j'ai supprimé", "j'ai envoyé", "je viens de supprimer"
    (re.compile(
        r"\b(j['']ai|je\s+viens\s+de|nous\s+avons)\s+"
        r"(supprim|envoy|cré|enregistr|déplacé|sauveg|vidé|effacé|"
        r"archivé|plani|programm|modifi|transfér|appel)",
        re.IGNORECASE,
    ), "fr.first_person_past"),
    # "voilà, c'est fait" / "c'est fait" / "c'est bon, c'est supprimé"
    (re.compile(
        r"\b(c['']est\s+fait|voilà[,\s]+c['']est\s+(fait|supprim|envoy)|"
        r"c['']est\s+bon[,\s]+c['']est\s+(supprim|envoy|fait))",
        re.IGNORECASE,
    ), "fr.colloquial_done"),
    # "la corbeille a été vidée", "X mails supprimés"
    (re.compile(
        r"\b(la\s+corbeille\s+(a\s+été\s+)?vidée|"
        r"\d+\s+(emails?|mails?|messages?|fichiers?|événements?|"
        r"contacts?|tâches?|notes?)\s+(supprimés?|envoyés?|"
        r"créés?|effacés?|sauvegardés?|déplacés?))",
        re.IGNORECASE,
    ), "fr.quantified_done"),
    # "voilà, tout est supprimé"
    (re.compile(
        r"\btout\s+(est|a\s+été)\s+(supprim|envoy|fait|cré|effac)",
        re.IGNORECASE,
    ), "fr.all_done"),
]

_EN_COMPLETION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "I've deleted", "I have sent", "I just deleted"
    (re.compile(
        r"\b(i['']ve|i\s+have|i\s+just|we['']ve|we\s+have)\s+"
        r"(deleted|sent|created|saved|moved|removed|emptied|"
        r"archived|scheduled|updated|transferred|cancelled?)",
        re.IGNORECASE,
    ), "en.first_person_past"),
    # "X emails have been deleted", "the trash has been emptied"
    (re.compile(
        r"\b\d+\s+(emails?|messages?|files?|events?|contacts?|"
        r"tasks?|notes?)\s+(have\s+been|were)\s+"
        r"(deleted|sent|created|saved|moved|removed|archived)",
        re.IGNORECASE,
    ), "en.quantified_done"),
    # "done", "all done", "all set"
    (re.compile(
        r"\b(all\s+done|all\s+set|it['']s\s+done)\b",
        re.IGNORECASE,
    ), "en.colloquial_done"),
    # "the trash has been emptied"
    (re.compile(
        r"\b(the\s+trash|the\s+folder)\s+(has\s+been|was)\s+"
        r"(emptied|cleared|deleted)",
        re.IGNORECASE,
    ), "en.passive_done"),
]

_ALL_PATTERNS = _FR_COMPLETION_PATTERNS + _EN_COMPLETION_PATTERNS


# ──────────────────────────────────────────────────────────────────────
# Verdict
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GuardVerdict:
    """Result of a guard check on one assistant response.

    Attributes:
        is_hallucination: True if the assistant claims completion but no
            destructive tool was actually invoked in this turn.
        matched_patterns: List of pattern labels that fired on the
            content. Empty if no completion claim was detected.
        tools_invoked: List of tool names invoked in this turn (snapshot
            of the caller's tracking).
        destructive_tools_invoked: Subset of tools_invoked that are in
            ``DESTRUCTIVE_TOOLS``. If non-empty, no hallucination —
            even if completion language is present, the action was real.
        reason: Human-readable one-line explanation, suitable for logs
            and for the audit trail.
    """

    is_hallucination: bool
    matched_patterns: list[str] = field(default_factory=list)
    tools_invoked: list[str] = field(default_factory=list)
    destructive_tools_invoked: list[str] = field(default_factory=list)
    reason: str = ""


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def detect_unbacked_completion_claim(
    ai_content: str,
    tools_invoked_in_turn: list[str],
    *,
    destructive_tools: frozenset[str] = DESTRUCTIVE_TOOLS,
) -> GuardVerdict:
    """Return a verdict on whether *ai_content* hallucinates a completion.

    Args:
        ai_content: The final assistant text being delivered to the user
            (after deanonymization, response_filter, anti_self_dialogue,
            media_router — i.e. the exact text the user will see).
        tools_invoked_in_turn: List of LangChain tool names invoked since
            the user's last message. Caller is responsible for resetting
            the list at the start of each user turn.
        destructive_tools: Frozenset of tool names considered
            "destructive". Defaults to the module-level ``DESTRUCTIVE_TOOLS``.

    Returns:
        A ``GuardVerdict``. Check ``.is_hallucination`` to gate behaviour.

    Decision logic:
        1. Scan *ai_content* against all completion-claim patterns.
        2. If no pattern fires → no claim, no hallucination, return clean.
        3. If pattern fires, intersect *tools_invoked_in_turn* with
           *destructive_tools*. If at least one destructive tool was
           actually invoked → claim is backed → no hallucination.
        4. If pattern fires AND no destructive tool was invoked →
           HALLUCINATION. Return verdict with details for logging/UI.

    The function is pure: no I/O, no LLM call, no DB access. Side effects
    (logging, user notification, response rewriting) are the caller's
    responsibility.
    """
    if not ai_content or not ai_content.strip():
        # No content → nothing to claim about. Not a hallucination,
        # just an empty turn (which is its own bug but not THIS one).
        return GuardVerdict(
            is_hallucination=False,
            tools_invoked=list(tools_invoked_in_turn),
            reason="empty_content",
        )

    matched: list[str] = []
    for pattern, label in _ALL_PATTERNS:
        if pattern.search(ai_content):
            matched.append(label)

    if not matched:
        return GuardVerdict(
            is_hallucination=False,
            tools_invoked=list(tools_invoked_in_turn),
            reason="no_completion_claim_in_text",
        )

    # A completion claim was made. Now check: did the agent actually
    # call a destructive tool in this turn?
    destructive_called = [
        t for t in tools_invoked_in_turn if t in destructive_tools
    ]

    if destructive_called:
        # Real success — the assistant said "supprimé" AND a delete tool
        # was invoked. No hallucination.
        return GuardVerdict(
            is_hallucination=False,
            matched_patterns=matched,
            tools_invoked=list(tools_invoked_in_turn),
            destructive_tools_invoked=destructive_called,
            reason=(
                f"completion_claim_backed_by_tools "
                f"(patterns={matched}, tools={destructive_called})"
            ),
        )

    # HALLUCINATION DETECTED. Completion language without any
    # destructive tool invocation in this turn.
    return GuardVerdict(
        is_hallucination=True,
        matched_patterns=matched,
        tools_invoked=list(tools_invoked_in_turn),
        destructive_tools_invoked=[],
        reason=(
            f"completion_claim_without_destructive_tool_call "
            f"(patterns={matched}, all_tools={tools_invoked_in_turn})"
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Helper: build a user-visible warning when a hallucination is caught
# ──────────────────────────────────────────────────────────────────────


def build_warning_replacement(
    original_content: str,
    verdict: GuardVerdict,
    *,
    locale: str = "fr",
) -> str:
    """Build the user-visible warning that replaces a hallucinated response.

    The original (suspect) content is wrapped in a quote block so the user
    can still see what the agent *intended* to say, but the warning
    makes the situation unambiguous.

    Args:
        original_content: The suspect assistant text.
        verdict: The ``GuardVerdict`` from ``detect_unbacked_completion_claim``.
        locale: "fr" or "en". Defaults to French (primary user base).

    Returns:
        A string ready to be persisted and sent to the user.
    """
    if locale.startswith("en"):
        return (
            "⚠️ **Hallucination intercepted by ELY's safety guard.**\n\n"
            "The agent claimed an action was completed but did NOT invoke "
            "any destructive tool in this turn. **Nothing was actually "
            "deleted, sent or modified.** This is a model-side issue "
            "(in-context pattern shortcutting) that gets worse as the "
            "conversation gets longer.\n\n"
            "**What to do:** rephrase your request, ideally in a fresh "
            "conversation, or switch the assistant to a larger tier.\n\n"
            "<details><summary>The model wanted to say (do NOT trust it):</summary>\n\n"
            f"> {original_content.strip()}\n\n"
            "</details>"
        )
    # Default: FR
    return (
        "⚠️ **Hallucination interceptée par le garde-fou ELY.**\n\n"
        "L'agent a annoncé qu'une action était faite mais **n'a appelé "
        "aucun outil de modification dans ce tour**. **Rien n'a été "
        "réellement supprimé, envoyé ou modifié.** C'est un problème "
        "modèle (raccourci de pattern en contexte long) qui s'aggrave "
        "au fil de la conversation.\n\n"
        "**À faire :** reformule ta demande, idéalement dans une "
        "nouvelle conversation, ou bascule l'assistant sur un tier "
        "plus capable.\n\n"
        "<details><summary>Ce que le modèle voulait dire (à NE PAS croire) :</summary>\n\n"
        f"> {original_content.strip()}\n\n"
        "</details>"
    )
