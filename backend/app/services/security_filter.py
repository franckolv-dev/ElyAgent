# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
import re
from dataclasses import dataclass, field

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
    "CARD":  re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "EMAIL": re.compile(r"[a-zA-Z0-9_.+-]{1,64}@[a-zA-Z0-9-]{1,63}\.[a-zA-Z0-9-.]{1,63}"),
    "TOKEN": re.compile(r"(?:api[_-]?key|token|auth|password|secret|bearer)[:\s=]+([a-zA-Z0-9\-_.]{16,256})", re.IGNORECASE),
    "IBAN":  re.compile(r"\b[A-Z]{2}\d{2}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{2,}\b"),
    "PHONE": re.compile(r"\b(?:\+33|0)[1-9](?:[\s.\-]?\d{2}){4}\b"),
}

# Tool names that always require human validation
# Only truly destructive or irreversible actions belong here
ALWAYS_CRITICAL_TOOLS: frozenset[str] = frozenset({
    "ssh_execute",
    "gmail_send_email",
    "whatsapp_send",
    "whatsapp_send_template",
    # Browser actions that modify state on external websites
    "browser_click",
    "browser_fill",
    # OS control — desktop automation (Interactive Trainer)
    "os_mouse_move",
    "os_click",
    "os_type_text",
    "os_hotkey",
    # MCP dynamic generation — executes generated code
    "mcp_validate_and_deploy",
    # ELY Desktop — destructive filesystem operations on user's local machine
    "desktop_write_file",
    "desktop_move_file",
    "desktop_delete_file",
    # Google Workspace — actions critiques
    "gmail_reply_email",
    "gmail_send_with_attachment",
    "gmail_move_emails",
    "gmail_trash_emails",
    "calendar_create_event",
    "calendar_delete_event",
    "drive_move_file",
    "drive_delete_file",
    "contacts_delete",
    "tasks_delete",
})

# Keywords in TOOL ARGUMENTS (not tool name) that flag an action as needing validation
# These are checked against the display_args JSON, not the tool name
_CRITICAL_KEYWORDS: frozenset[str] = frozenset({
    # Destructive operations
    "delete", "remove", "drop", "purge", "wipe", "truncate",
    "supprimer", "effacer",
    "rm -rf", "format", "mkfs",
    "chmod 777", "chown root",
    # Financial
    "pay", "payment", "virement", "buy", "purchase",
    "payer", "achat",
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
        that requires human validation before execution."""
        lower = text.lower()
        if any(kw in lower for kw in _CRITICAL_KEYWORDS):
            return True
        # Any placeholder for card / token / IBAN in an action description
        if any(f"[{t}_" in text for t in ("CARD", "TOKEN", "IBAN")):
            return True
        return False

    def reset(self) -> None:
        self._vault.clear()
        self._counter = 0
