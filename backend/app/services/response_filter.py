# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/response_filter.py
# @brief      Post-process LLM responses to enforce user preferences
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Post-process LLM responses to enforce user preferences.

Small/medium LLMs (7B-30B) often fail at negative constraints like
"do not use emojis" even when the rule is explicitly stated in the
system prompt. They generate token-by-token and drift back to their
trained patterns.

This module provides deterministic post-processing to enforce user
preferences as a safety net, regardless of LLM compliance.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Emoji detection
# ---------------------------------------------------------------------------

# Unicode emoji ranges covering the main emoji blocks.
# Reference: https://en.wikipedia.org/wiki/Emoji#Unicode_blocks
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"   # Misc symbols & pictographs
    "\U0001F600-\U0001F64F"   # Emoticons (smileys, hand gestures)
    "\U0001F680-\U0001F6FF"   # Transport & map symbols
    "\U0001F700-\U0001F77F"   # Alchemical symbols
    "\U0001F780-\U0001F7FF"   # Geometric shapes extended
    "\U0001F800-\U0001F8FF"   # Supplemental arrows-C
    "\U0001F900-\U0001F9FF"   # Supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"   # Chess, hearts
    "\U0001FA70-\U0001FAFF"   # Symbols & pictographs extended-A
    "\U00002600-\U000026FF"   # Misc symbols (☀, ☁, ⭐, etc.)
    "\U00002700-\U000027BF"   # Dingbats (✅, ✨, ❤, etc.)
    "\U0001F1E0-\U0001F1FF"   # Regional indicators (flags)
    "]+",
    flags=re.UNICODE,
)

# Variation selectors and zero-width joiners that often accompany emojis
_EMOJI_MODIFIERS = re.compile(r"[\U0000FE00-\U0000FE0F\U0001F3FB-\U0001F3FF\U0000200D]")


def _strip_emojis(text: str) -> str:
    """Remove all emojis and their variation selectors from a string."""
    text = _EMOJI_PATTERN.sub("", text)
    text = _EMOJI_MODIFIERS.sub("", text)
    # Collapse double spaces and trim trailing whitespace that emojis left behind
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r" +([.,!?;:])", r"\1", text)   # space before punctuation
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Markdown stripping (when user prefs say "pas de markdown")
# ---------------------------------------------------------------------------

_MARKDOWN_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Code fences
    (re.compile(r"```[\s\S]*?```"), lambda m: m.group(0).strip("`")),  # keep code content
    # Inline code
    (re.compile(r"`([^`]+)`"), r"\1"),
    # Headers
    (re.compile(r"^#{1,6}\s+", flags=re.MULTILINE), ""),
    # Bold **x** / __x__
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    # Italic *x* / _x_
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), r"\1"),
    (re.compile(r"(?<!_)_([^_\n]+)_(?!_)"), r"\1"),
    # Bullet markers
    (re.compile(r"^\s*[-*•]\s+", flags=re.MULTILINE), ""),
    # Numbered list markers
    (re.compile(r"^\s*\d+\.\s+", flags=re.MULTILINE), ""),
    # Horizontal rules
    (re.compile(r"^\s*[-*_]{3,}\s*$", flags=re.MULTILINE), ""),
    # Markdown links [text](url) → text (url)
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r"\1 (\2)"),
]


def _strip_markdown(text: str) -> str:
    """Remove common Markdown syntax from text (keep links as 'text (url)')."""
    for pattern, replacement in _MARKDOWN_PATTERNS:
        if callable(replacement):
            text = pattern.sub(replacement, text)
        else:
            text = pattern.sub(replacement, text)
    # Clean up any leftover ``` tokens
    text = text.replace("```", "")
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Preference matchers — keywords detected in user preferences text
# ---------------------------------------------------------------------------

_NO_EMOJI_KEYWORDS = (
    "émoji", "emoji", "emoticône", "emoticone", "émoticône", "émoticone",
    "smiley", "main levée", "hand emoji",
)

_NO_MARKDOWN_KEYWORDS = (
    "markdown", "mise en forme", "formatage", "texte brut", "plain text",
)


def _normalize_prefs(prefs: Iterable[str]) -> list[str]:
    """Lowercase + strip accents for matching."""
    out: list[str] = []
    for p in prefs or ():
        n = unicodedata.normalize("NFD", p.lower())
        n = "".join(c for c in n if unicodedata.category(c) != "Mn")
        out.append(n)
    return out


def wants_no_emoji(prefs: Iterable[str]) -> bool:
    """Return True if any user preference asks for no emojis."""
    normalized = _normalize_prefs(prefs)
    # A pref like "ne jamais utiliser d'emojis" contains "emoji" AND a negation
    for p in normalized:
        if any(kw.lower() in p for kw in _NO_EMOJI_KEYWORDS):
            if any(neg in p for neg in ("ne pas", "ne plus", "ne jamais", "sans ", "pas d", "absence", "no ", "arrete", "arrête", "eviter", "éviter")):
                return True
            # "pas d'émoji" without "ne" (contraction)
            if "pas d" in p and "emoji" in p:
                return True
    return False


def wants_no_markdown(prefs: Iterable[str]) -> bool:
    """Return True if any user preference asks for no markdown."""
    normalized = _normalize_prefs(prefs)
    for p in normalized:
        if any(kw.lower() in p for kw in _NO_MARKDOWN_KEYWORDS):
            if any(neg in p for neg in ("ne pas", "ne plus", "ne jamais", "sans", "pas de", "no ", "eviter", "éviter")):
                return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_user_preferences(text: str, preferences: Iterable[str]) -> str:
    """Apply deterministic post-processing based on user preferences.

    Safety net for small/medium LLMs that fail to honor negative constraints.
    Always called after LLM generation, before sending to the user.
    """
    if not text:
        return text

    original_len = len(text)

    if wants_no_emoji(preferences):
        text = _strip_emojis(text)

    if wants_no_markdown(preferences):
        text = _strip_markdown(text)

    if len(text) != original_len:
        logger.debug("Response filter: stripped %d chars by user prefs", original_len - len(text))

    return text
