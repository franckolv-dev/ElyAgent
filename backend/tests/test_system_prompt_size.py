# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_system_prompt_size.py
# @brief      2026-05-23 — pin the size of `_SYSTEM_PROMPT_BASE` after the
#             Passe 1 reduction. Prevents accidental re-bloat as defensive
#             rules get added over time.
# @license    Elastic License 2.0
# =============================================================================
"""Size guard for `_SYSTEM_PROMPT_BASE`.

Context (2026-05-23) : the system prompt accumulated defensive rules
after each incident (DeepSeek hallucinations, Mistral loops, Doctolib
flow, etc.) and grew to 34 449 chars / 387 lines. On long
conversations with Gemma 4 4B (default ctx 8k) this saturated the
context and triggered hallucinations.

After the Passe 1 compaction, the prompt sits at ~12 500 chars / 137
lines, holding all the critical rules in denser form. This test
prevents silent regrowth.

If a future change LEGITIMATELY needs to add a rule, the test can be
updated — but only after explicit decision (e.g. via an updated audit).
"""
from __future__ import annotations

import re


# Hard ceiling — anything above this should be flagged as regrowth that
# needs the audit doc updated first. Leave ~15% headroom over the
# current value (~12.5k) so a small rule addition doesn't break CI.
_MAX_CHARS = 15_000

# Soft floor — under this we're probably missing critical rules. Set
# very generously below the current value to catch only a major loss.
_MIN_CHARS = 8_000


def _load_prompt() -> str:
    from app.agent.nodes import _SYSTEM_PROMPT_BASE
    return _SYSTEM_PROMPT_BASE


def test_system_prompt_is_under_15k_chars() -> None:
    prompt = _load_prompt()
    assert len(prompt) <= _MAX_CHARS, (
        f"_SYSTEM_PROMPT_BASE grew back to {len(prompt)} chars (max "
        f"{_MAX_CHARS}). Either compact further or update the audit "
        f"doc + this test ceiling consciously."
    )


def test_system_prompt_is_above_8k_chars() -> None:
    prompt = _load_prompt()
    assert len(prompt) >= _MIN_CHARS, (
        f"_SYSTEM_PROMPT_BASE shrank to {len(prompt)} chars (min "
        f"{_MIN_CHARS}). Likely a critical rule was deleted by mistake."
    )


def test_system_prompt_keeps_critical_anchors() -> None:
    """A short list of phrases without which we know the prompt
    is missing something the user-facing behaviour relies on."""
    prompt = _load_prompt().lower()
    critical_anchors = [
        # Identity
        "féminin",
        "prononcé",
        # Memory persistence
        "mémoire persistante",
        # Anti-hallucination core
        "règle 0",
        "aucune mémoire interne",
        # Action integrity
        "vérité absolue",  # tool return is truth
        "function calling",  # tool calling protocol
        # Anti-auto-dialogue
        "auto-dialogue",
        # Browser extension
        "browser_open_tab",
        "extension_not_connected",
        # Patterns A/B/C
        "pattern a",
        "pattern b",
        "pattern c",
        # Scheduler vs Calendar distinction
        "scheduler_create_task",
        "calendar_create_event",
        # Cross-conv memory
        "search_past_conversations_tool",
        # Format
        "sans markdown",
    ]
    missing = [a for a in critical_anchors if a not in prompt]
    assert not missing, (
        f"_SYSTEM_PROMPT_BASE is missing critical anchors: {missing}. "
        f"Either the rule was removed unintentionally, or the wording "
        f"shifted — verify before updating this test."
    )


def test_system_prompt_has_no_dead_references() -> None:
    """The compacted prompt must not reference sections or audit dates
    that no longer exist in it. Catches half-finished refactors."""
    prompt = _load_prompt()
    # The "audit Franck du 16 mai" anecdote was removed in Passe 1 ; if
    # someone re-adds the reference without re-adding the content,
    # users would see a dangling pointer.
    assert "audit Franck du 16 mai" not in prompt, (
        "Reference to '16 mai audit' should not return — that anecdote "
        "was retired in Passe 1 as it was historical context, not a rule."
    )
    # The Doctolib detailed walkthrough was generalised into PATTERN C ;
    # specific selectors like aria-expanded=\"false\" or li:nth-child
    # should not return inline (they belong in tool runbooks).
    assert 'aria-expanded="false"' not in prompt, (
        "Detailed Doctolib selectors should not return to the system "
        "prompt — generalise via PATTERN C and put specifics in a tool "
        "runbook if needed."
    )


def test_system_prompt_has_no_duplicate_paragraphs() -> None:
    """Catch accidental copy-paste duplication (the legacy prompt had
    the "Format de réponse OBLIGATOIRE" paragraph twice verbatim)."""
    prompt = _load_prompt()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", prompt) if p.strip()]
    # Long paragraphs (≥ 200 chars) duplicating exactly indicate
    # copy-paste accident.
    long_paragraphs = [p for p in paragraphs if len(p) >= 200]
    seen: dict[str, int] = {}
    for p in long_paragraphs:
        seen[p] = seen.get(p, 0) + 1
    dupes = [p[:80] + "…" for p, n in seen.items() if n > 1]
    assert not dupes, (
        f"Duplicate paragraphs detected (≥200 chars, seen 2×) : {dupes}"
    )
