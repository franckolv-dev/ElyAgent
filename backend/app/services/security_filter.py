# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/security_filter.py
# @brief      Tool call security filter
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Longueur maximale de texte soumis aux regex.
# Protège contre les attaques ReDoS : une chaîne très longue et mal formée
# peut faire exploser le backtracking sur les patterns ci-dessous.
_MAX_REGEX_INPUT = 50_000   # caractères

# Patterns for sensitive data detection.
# Notes ReDoS :
#   EMAIL  — quantificateurs imbriqués sur [a-zA-Z0-9_.+-]+ → vulnérable sur entrées
#             très longues (e.g. 50 000×'a' + '@'). Mitigé par _MAX_REGEX_INPUT.
#   IBAN   — alternances d'espaces optionnels → risque faible mais garde ajoutée.
#   Tous les patterns utilisent re.compile() pour bénéficier du cache NFA.
_PATTERNS: dict[str, re.Pattern] = {
    # CARD: possessive-style via atomic boundaries — no nested quantifiers
    "CARD":  re.compile(r"\b\d(?:[ -]?\d){12,15}\b"),
    # EMAIL: explicit character classes, bounded lengths, no ambiguous overlap
    "EMAIL": re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,62}[a-zA-Z0-9]@[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]\.[a-zA-Z]{2,10}\b"),
    # TOKEN: non-greedy match on keyword, fixed-width value range
    "TOKEN": re.compile(r"(?:api[_-]?key|token|auth|password|secret|bearer)[:\s=]+([a-zA-Z0-9\-_.]{16,256})", re.IGNORECASE),
    # IBAN: no optional spaces to avoid alternation backtracking — strip spaces first
    "IBAN":  re.compile(r"\b[A-Z]{2}\d{2}(?:\d{4}){4}\d{2,}\b"),
    # PHONE: no optional separator inside repeating group
    "PHONE": re.compile(r"\b(?:\+33|0)[1-9](?:\d{2}){4}\b"),
}

# Tool names that always require human validation.
#
# HITL philosophy (2026-04-17): minimiser la friction. L'agent doit être
# fluide pour les actions courantes non-dangereuses (créer un RDV, bouger
# un mail dans un dossier, modifier un doc). HITL uniquement pour :
#   1. Suppressions (destructives, irréversibles)
#   2. Envois de mail (relecture avant envoi externe)
#   3. SSH (commandes serveur)
#   4. Config système / API brute (modifications silencieuses)
#   5. Contrôle OS (sécurité du système local)
#   6. Communications externes (WhatsApp) + partage externe (Drive share)
#
# Les actions NON-HITL :
#   - calendar_* create/update : c'est SON calendrier
#   - docs/sheets_batch_update : SES documents
#   - gmail_move/batch_modify : déplacement, pas envoi
#   - drive_move_file : dans SON drive
ALWAYS_CRITICAL_TOOLS: frozenset[str] = frozenset({
    # ── 1. Suppressions ──
    "desktop_delete_file",
    "drive_delete_file",
    "tasks_delete",
    "gmail_trash_emails",
    "gmail_trash_by_category",
    "gmail_trash_by_query",
    "gmail_empty_trash",            # PERMANENT delete of trash contents — irreversible
    "contacts_delete",
    "calendar_delete_event",
    # ── 2. Envois de mail (relecture obligatoire) ──
    "gmail_send_email",
    "gmail_reply_email",
    "gmail_send_with_attachment",
    # ── 3. SSH ──
    "ssh_execute",
    # ── 4. Config / API brute (mutations silencieuses potentielles) ──
    "gmail_update_settings",
    "gmail_raw_api_call",
    "calendar_raw_api_call",
    "drive_raw_api_call",
    "docs_raw_api_call",
    "sheets_raw_api_call",
    "tasks_raw_api_call",
    "contacts_raw_api_call",
    "mcp_validate_and_deploy",
    # ── 5. Contrôle OS (dangereux pour la machine locale) ──
    "os_click",
    "os_type_text",
    "os_hotkey",
    "os_mouse_move",
    "desktop_write_file",
    "desktop_move_file",
    "desktop_create_dir",
    # ── 6. Communications externes + partage ──
    "whatsapp_send",
    "whatsapp_send_template",
    "drive_share_file",
})


# Tools that an AUTONOMOUS mission must NEVER auto-approve (the "security
# floor"). Even with the mission's `autonomous` flag on, these still require
# a human: they are irreversible, leave the building (3rd-party), or touch
# security/system state. In an autonomous run they are SKIPPED (the step
# fails, the mission keeps going) rather than executed blind at 3 a.m.
# Non-floor HITL-gated tools (labels, Drive/Sheets writes, self-mail) ARE
# auto-approved. Note: an explicit user pre-approval (Toujours autoriser /
# Pour cette tâche) still lets a floor tool through — it's checked first.
NEVER_AUTONOMOUS_TOOLS: frozenset[str] = frozenset({
    # Irreversible / mass-destructive
    "gmail_empty_trash", "gmail_trash_emails", "gmail_trash_by_query",
    "gmail_trash_by_category", "gmail_batch_modify",
    "drive_delete_file", "desktop_delete_file",
    "calendar_delete_event", "tasks_delete",
    "contacts_delete", "contacts_batch_operations",
    # Leaves the building / third party
    "gmail_send_email", "gmail_reply_email", "gmail_send_with_attachment",
    "whatsapp_send", "whatsapp_send_template", "drive_share_file",
    # Security / system / unrestricted escape hatches
    "ssh_execute", "vault_unlock", "vault_set_secret", "save_constraint",
    "mcp_validate_and_deploy", "gmail_update_settings",
    "gmail_raw_api_call", "calendar_raw_api_call", "drive_raw_api_call",
    "docs_raw_api_call", "sheets_raw_api_call", "tasks_raw_api_call",
    "contacts_raw_api_call",
    "os_click", "os_type_text", "os_hotkey", "os_mouse_move",
})

# Keywords in TOOL ARGUMENTS (not tool name) that flag an action as needing validation
# These are checked against the display_args JSON, not the tool name.
# Kept minimal — "remove" removed (too broad), added financial transfer terms.
_CRITICAL_KEYWORDS: frozenset[str] = frozenset({
    # Destructive operations
    "delete", "drop", "purge", "wipe", "truncate",
    "supprimer", "effacer",
    "rm -rf", "format", "mkfs",
    "chmod 777", "chown root",
    # Financial — payments, transfers, purchases
    "pay", "payment", "virement", "buy", "purchase",
    "payer", "achat", "transfer", "transférer",
    "send money", "envoyer de l'argent",
    # Browser purchase flows (when browser_click/fill is the tool)
    "paypal.com", "checkout", "panier", "cart",
    "amazon.", "cdiscount.", "fnac.", "leboncoin.",
})


@dataclass
class SecurityFilter:
    """Per-conversation security filter.

    Anonymizes sensitive data before it leaves to the cloud LLM, and
    restores it in the response. Also flags critical actions so the
    HITL manager can request human validation.
    """
    _vault: dict[str, str] = field(default_factory=dict)
    _counter: int = field(default=0)

    # ------------------------------------------------------------------ #
    # Anonymization                                                         #
    # ------------------------------------------------------------------ #

    def anonymize(self, text: str) -> str:
        """Replace sensitive values with opaque placeholders.

        Each unique sensitive value is mapped to exactly one placeholder.
        Substitutions are performed using match positions (start/end offsets)
        rather than str.replace, which avoids incorrect replacements when a
        PII value happens to be a substring of a common word or another match.

        Algorithm:
        1. Run all patterns on the original text and collect (start, end, label, value).
        2. Sort by start position; discard overlapping matches (first match wins).
        3. Process matches right-to-left so that earlier offsets stay valid.

        Guard anti-ReDoS : le texte est tronqué à _MAX_REGEX_INPUT caractères
        avant d'être soumis aux expressions régulières.
        """
        # ── Guard anti-ReDoS ─────────────────────────────────────────────
        if len(text) > _MAX_REGEX_INPUT:
            logger.warning("Text exceeds ReDoS guard (%d > %d). Data beyond limit NOT anonymized.", len(text), _MAX_REGEX_INPUT)
            text = text[:_MAX_REGEX_INPUT]

        # Build a reverse lookup: real-value → existing placeholder, so the
        # same value seen again in a new message reuses the same token.
        _seen: dict[str, str] = {v: k for k, v in self._vault.items()}

        # ── Collect all matches with positions ───────────────────────────
        # list of (start, end, label, original_value)
        all_matches: list[tuple[int, int, str, str]] = []
        for label, pattern in _PATTERNS.items():
            for m in pattern.finditer(text):
                all_matches.append((m.start(), m.end(), label, m.group(0)))

        # Sort ascending by start position; remove overlapping spans (keep first)
        all_matches.sort(key=lambda x: x[0])
        non_overlapping: list[tuple[int, int, str, str]] = []
        last_end = -1
        for start, end, label, original in all_matches:
            if start >= last_end:
                non_overlapping.append((start, end, label, original))
                last_end = end

        # ── Apply substitutions right-to-left (preserves earlier offsets) ─
        result = text
        for start, end, label, original in reversed(non_overlapping):
            if original in _seen:
                placeholder = _seen[original]
            else:
                placeholder = f"[{label}_{self._counter}]"
                self._vault[placeholder] = original
                _seen[original] = placeholder
                self._counter += 1
            result = result[:start] + placeholder + result[end:]

        return result

    def deanonymize(self, text: str) -> str:
        """Restore real values from placeholders in LLM output."""
        for placeholder, real in self._vault.items():
            text = text.replace(placeholder, real)
        return text

    # ------------------------------------------------------------------ #
    # Criticality check                                                    #
    # ------------------------------------------------------------------ #

    def is_critical(self, text: str) -> bool:
        """Return True if the text contains a keyword or sensitive placeholder
        that requires human validation before execution.

        Matching is done on WORD BOUNDARIES, not substrings — otherwise
        `notes_delete` (a safe local-only operation) would match "delete"
        and trigger unnecessary HITL prompts. ALWAYS_CRITICAL_TOOLS
        already covers the truly destructive cases in the HITL manager.
        """
        import re as _re
        lower = text.lower()
        # Whole-word (or whole-phrase) match — anchor on \b for single
        # words, let multi-token keywords like "rm -rf" match literally.
        for kw in _CRITICAL_KEYWORDS:
            pattern = (
                r"\b" + _re.escape(kw) + r"\b"
                if kw.isalpha() and " " not in kw
                else _re.escape(kw)
            )
            if _re.search(pattern, lower):
                return True
        # Any placeholder for card / token / IBAN in an action description
        if any(f"[{t}_" in text for t in ("CARD", "TOKEN", "IBAN")):
            return True
        return False

    def reset(self) -> None:
        self._vault.clear()
        self._counter = 0
