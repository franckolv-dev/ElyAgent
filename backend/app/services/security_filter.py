import re
from dataclasses import dataclass, field


# Patterns for sensitive data detection
_PATTERNS: dict[str, str] = {
    "CARD":  r"\b(?:\d[ -]*?){13,16}\b",
    "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "TOKEN": r"(?:api[_-]?key|token|auth|password|secret|bearer)[:\s=]+([a-zA-Z0-9\-_.]{16,})",
    "IBAN":  r"\b[A-Z]{2}\d{2}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{2,}\b",
    "PHONE": r"\b(?:\+33|0)[1-9](?:[\s.\-]?\d{2}){4}\b",
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
        re.finditer is called on the *current* result string so that already-
        substituted tokens are not matched again by subsequent iterations.
        A reverse set (_seen) provides O(1) duplicate detection.
        """
        result = text
        # Build a reverse lookup from real-value → existing placeholder so
        # the same value seen again in a new message reuses the same token.
        _seen: dict[str, str] = {v: k for k, v in self._vault.items()}

        for label, pattern in _PATTERNS.items():
            # Collect all unique matches first, then replace, to avoid
            # mutating `result` mid-iteration over positions.
            found: list[str] = []
            for match in re.finditer(pattern, result, re.IGNORECASE):
                original = match.group(0)
                if original not in found:
                    found.append(original)

            for original in found:
                if original in _seen:
                    # Already have a placeholder; ensure it is substituted
                    result = result.replace(original, _seen[original])
                    continue
                placeholder = f"[{label}_{self._counter}]"
                self._vault[placeholder] = original
                _seen[original] = placeholder
                self._counter += 1
                result = result.replace(original, placeholder)
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
