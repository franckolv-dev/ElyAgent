# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/completion_guard.py
# @brief      Anti-hallucination completion guard — detects when the LLM
#             claims a destructive action was performed without actually
#             calling the corresponding tool in the current turn.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
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
# Negation guard (2026-05-30 fix — false-positive on negated claims)
# ──────────────────────────────────────────────────────────────────────
#
# The completion patterns above match the VERB of a state-change
# ("a été créé", "supprimé"…) but are blind to a leading negation.
#
# Real incident : a perfectly correct read-only answer
#     « Le projet a 0 fork. Aucun fork n'a été créé pour l'instant. »
# tripped `fr.passive_past` on "a été créé" (inside "n'a été créé") and
# got BLOCKED as a hallucinated completion — even though the sentence
# asserts the OPPOSITE (nothing was created) and called no destructive
# tool (it's a github_repo_stats read).
#
# Fix : for every pattern hit, scan a short window BEFORE the match for
# a negation marker. A negated completion phrase is not a "I did X"
# assertion — it's a "X did not happen / there is no X" report, which is
# legitimate and tool-backing-agnostic. Negated hits are skipped.
#
# Per-match (not per-response) so a mixed sentence like
#     « Je n'ai pas supprimé les mails, mais j'ai envoyé le rapport. »
# still flags the real "j'ai envoyé" claim while ignoring the negated
# "supprimé".

# How many characters before a match to inspect for a negation marker.
# 48 covers "aucun <noun> n'a été …" / "rien n'a été …" / "ne … pas …".
_NEGATION_WINDOW = 48

_FR_NEGATION_RE = re.compile(
    r"(?:\bne\s|\bn['']|\baucun(?:e)?\b|\brien\b|\bpas\s+(?:de|d['']|encore)\b|"
    r"\bjamais\b|\bplus\s+(?:de|d['']|aucun)\b|\bsans\b|\bni\b)",
    re.IGNORECASE,
)
_EN_NEGATION_RE = re.compile(
    r"(?:\bno\b|\bnot\b|\bn['']t\b|\bnone\b|\bnothing\b|\bnever\b|"
    r"\bwithout\b|\bno\s+longer\b|\bdidn['']?t\b|\bhaven['']?t\b|\bhasn['']?t\b)",
    re.IGNORECASE,
)


# Clause boundaries — a negation only scopes the clause it lives in.
# Without this, "je n'ai pas supprimé, mais j'ai envoyé" would let the
# first clause's "n'" suppress the genuine "j'ai envoyé" claim.
_CLAUSE_BREAK_RE = re.compile(
    r"[.;,!?]|\bmais\b|\bpuis\b|\bensuite\b|\bbut\b|\bhowever\b|\bthen\b",
    re.IGNORECASE,
)


def _is_negated_match(text: str, match_start: int, window: int = _NEGATION_WINDOW) -> bool:
    """True if a negation marker scopes the completion-claim match —
    meaning the claim is denied, not asserted.

    Only the clause immediately preceding the match is considered: we
    cut the look-back window at the last clause boundary so a negation
    belonging to an earlier clause doesn't bleed over the match.
    """
    prefix = text[max(0, match_start - window):match_start]
    last_break = 0
    for m in _CLAUSE_BREAK_RE.finditer(prefix):
        last_break = m.end()
    clause = prefix[last_break:]
    return bool(_FR_NEGATION_RE.search(clause) or _EN_NEGATION_RE.search(clause))


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


# ──────────────────────────────────────────────────────────────────────
# Memory-recall question patterns (added 2026-05-23)
# ──────────────────────────────────────────────────────────────────────
#
# When the user asks the assistant to RECALL what it has memorised
# ("qu'as-tu enregistré sur mon compte amazon ?"), the honest answer
# starts with "voici ce que j'ai noté…" or "j'ai retrouvé que…". These
# phrases match the `fr.first_person_past` regex above and trigger a
# false positive — even though the facts come from auto-injected
# user_profile in the system prompt, with no tool call needed.
#
# Fix : when the user's last message clearly asks for a memory recall
# (these patterns), we BYPASS the guard for that turn's response.
# Conservative scope : only memory-recall verbs explicitly addressed
# to the assistant ("qu'as-TU", "te souviens-TU"), not generic past
# tense or third-person questions.

# Verbs covering "memorisation" actions (FR roots, prefix-matchable)
_FR_RECALL_VERB_ROOTS = (
    r"(enregistr|not|reten|mémoris|stock|sauveg|gard|appri|conserv|"
    r"trouv|recueill|collect|retrouv)"
)

_FR_MEMORY_RECALL_QUESTION_PATTERNS: list[re.Pattern] = [
    # "qu'as-tu enregistré/noté/retenu/mémorisé/stocké/sauvegardé/gardé"
    re.compile(
        r"\b(qu['']as[-\s]?tu|que\s+m['']?as[-\s]?tu)\s+"
        r"(.+?\s+)?"
        + _FR_RECALL_VERB_ROOTS,
        re.IGNORECASE,
    ),
    # "qu'est-ce que tu as <verbe de mémoire>" — variante très répandue
    re.compile(
        r"\bqu['']est[-\s]?ce\s+que\s+tu\s+as\s+"
        r"(.+?\s+)?"
        + _FR_RECALL_VERB_ROOTS,
        re.IGNORECASE,
    ),
    # "te souviens-tu de" / "tu te souviens de" / "te rappelles-tu"
    re.compile(
        r"\b(te\s+souviens[-\s]?tu|tu\s+te\s+souviens|"
        r"te\s+rappelles[-\s]?tu|tu\s+te\s+rappelles)",
        re.IGNORECASE,
    ),
    # "que sais-tu sur" / "que connais-tu sur" / "qu'est-ce que tu sais sur"
    re.compile(
        r"\b(que\s+sais[-\s]?tu|que\s+connais[-\s]?tu|"
        r"qu['']est[-\s]?ce\s+que\s+tu\s+sais|"
        r"qu['']as[-\s]?tu\s+en\s+mémoire)",
        re.IGNORECASE,
    ),
    # "liste/montre-moi/donne-moi ce que tu as noté/enregistré/en mémoire"
    re.compile(
        r"\b(liste[-\s]?moi|liste|montre[-\s]?moi|donne[-\s]?moi|affiche|"
        r"rappelle[-\s]?moi)\s+"
        r"(.+?\s+)?"
        r"(ce\s+que\s+tu\s+(as|sais)\s+"
        + _FR_RECALL_VERB_ROOTS + r"|"
        r"tout\s+ce\s+que\s+tu\s+sais|ta\s+mémoire|"
        r"mes\s+(préférences|infos|données|facts))",
        re.IGNORECASE,
    ),
    # Standalone "rappelle-moi <quelque chose>" — explicit recall imperative
    re.compile(r"\brappelle[-\s]?moi\b", re.IGNORECASE),
]

# English verbs (covering "note"/"noted", "save"/"saved", etc.)
_EN_RECALL_VERB_ROOTS = (
    r"(save|sav|note|stor|memoriz|memoris|learn|kept|keep|"
    r"record|recall|remembered?)"
)

_EN_MEMORY_RECALL_QUESTION_PATTERNS: list[re.Pattern] = [
    # "what have/did/do you save/note/store/remember about"
    re.compile(
        r"\bwhat\s+(have\s+you|did\s+you|do\s+you)\s+"
        r"(.+?\s+)?"
        + _EN_RECALL_VERB_ROOTS,
        re.IGNORECASE,
    ),
    # "do you remember" / "do you recall" / "do you know about"
    re.compile(r"\bdo\s+you\s+(remember|recall|know\s+about)\b", re.IGNORECASE),
    # "tell me/show me what you know/have noted"
    re.compile(
        r"\b(tell\s+me|show\s+me|list)\s+"
        r"(.+?\s+)?"
        r"(what\s+you\s+(know|have|noted|remember)|"
        r"everything\s+you\s+(know|remember))",
        re.IGNORECASE,
    ),
]

_ALL_MEMORY_RECALL_PATTERNS = (
    _FR_MEMORY_RECALL_QUESTION_PATTERNS + _EN_MEMORY_RECALL_QUESTION_PATTERNS
)


def is_memory_recall_question(user_message: str) -> bool:
    """True if the user is explicitly asking the assistant to recall
    facts from its own memory ("qu'as-tu enregistré sur…", "te souviens-
    tu de…", etc.). The assistant's honest answer to these questions
    legitimately contains past-tense verbs ("j'ai noté…") that would
    otherwise trip the completion-claim guard.

    Conservative — only matches second-person, recall-specific verbs.
    """
    if not user_message or not user_message.strip():
        return False
    for pattern in _ALL_MEMORY_RECALL_PATTERNS:
        if pattern.search(user_message):
            return True
    return False


def detect_unbacked_completion_claim(
    ai_content: str,
    tools_invoked_in_turn: list[str],
    *,
    destructive_tools: frozenset[str] = DESTRUCTIVE_TOOLS,
    user_message: str | None = None,
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

    # 2026-05-23 — Memory-recall question bypass.
    # The user explicitly asked the assistant to recite what it has
    # memorised ("qu'as-tu enregistré sur mon compte amazon ?"). An
    # honest reply contains past-tense verbs ("voici ce que j'ai noté")
    # that would otherwise trip `fr.first_person_past`. The facts come
    # from auto-injected user_profile (see nodes.py:756-776) — no tool
    # call needed. Bypass the guard for this turn.
    if user_message and is_memory_recall_question(user_message):
        return GuardVerdict(
            is_hallucination=False,
            tools_invoked=list(tools_invoked_in_turn),
            reason="memory_recall_question_bypass",
        )

    matched: list[str] = []
    for pattern, label in _ALL_PATTERNS:
        # Per-match negation check : a hit inside "aucun X n'a été créé"
        # or "I didn't send …" is a DENIAL, not a completion assertion.
        # Skip negated hits ; keep scanning so a mixed sentence still
        # surfaces a genuine non-negated claim elsewhere.
        for m in pattern.finditer(ai_content):
            if _is_negated_match(ai_content, m.start()):
                continue
            matched.append(label)
            break  # one genuine hit per pattern is enough

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
