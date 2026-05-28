# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/anti_self_dialogue.py
# @brief      Detect and trim self-dialogue hallucinations from LLM responses
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Anti self-dialogue — trim hallucinated user-turn continuations.

Problem
-------
Small instruct LLMs (Ministral 3 8B, Mistral 7B, some Qwen variants under
8B) frequently CONTINUE the conversation past their own turn — emitting a
fake user reply followed by their own answer to it. Example seen in
production 2026-05-07 :

    « D'accord, mais peux-tu me dire si j'ai bien compris que je veux X ?
      Oui, tu as bien compris :
      • Toi contrôles la capture
      • Moi, je vérifie...
      C'est ça ?
      Oui, exactement.
      Mais avant toute action, peux-tu vérifier... »

The user reads this and is confused — Éli appears to have a conversation
with herself. Stop tokens at the LLM provider level catch most cases, but
some templates / providers still let the dialogue slip through.

This module is the last-line defense : a regex-based detector that finds
self-dialogue patterns in the final response and trims everything after
the first hallucinated user turn.

Patterns detected
-----------------
1. **Q-then-A loop**: "<question> ?\\n<positive_acknowledgment>" where
   the acknowledgment reads like a user response (« Oui exactement »,
   « C'est ça », « D'accord », « Yes that's right »).
2. **Voice swap**: « Toi … / Moi … » bullet structure listing the user's
   responsibilities and the assistant's responsibilities — a clear sign
   the model is summarising both sides of an imaginary contract.
3. **Sudden third-person re-statement**: lines like « L'utilisateur souhaite… »
   right after a direct address.

When a self-dialogue is detected, we cut the response at the FIRST
boundary marker (whichever comes first) and append a brief note in
debug logs so we can tune the patterns over time.
"""
from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)


# Trigger 1 : a question followed by a user-style affirmation. The first
# group is the answer-token; we cut at its start position.
_QA_LOOP_PATTERN: Final[re.Pattern] = re.compile(
    r"\?\s*\n+\s*(?P<answer>"
    r"oui[\s,!.]*(tu\s+as\s+bien\s+compris|exactement|c'est\s+ça|exact|voilà|c'est\s+cela)|"
    r"exactement[\s,!.]+|"
    r"c'est\s+ça[\s,!.]+oui|"
    r"d'accord[\s,!.]+(donc|alors|c'est)|"
    r"yes[\s,!.]+(that'?s|exactly|right|correct)|"
    r"that'?s\s+(right|correct|exactly)"
    r")\b",
    re.IGNORECASE,
)

# Trigger 2 : « Toi … / Moi … » dialog of attribution
_VOICE_SWAP_PATTERN: Final[re.Pattern] = re.compile(
    r"(\n\s*[-•*]\s*\*?\*?(toi|tu)\b[^\n]{5,200}\n+\s*[-•*]\s*\*?\*?(moi|je)\b)",
    re.IGNORECASE,
)

# Trigger 3 : sudden third-person narration about "the user"
_THIRD_PERSON_PATTERN: Final[re.Pattern] = re.compile(
    r"\n+\s*(l'utilisateur\s+(souhaite|veut|demande|a\s+demandé|a\s+fourni)|"
    r"the\s+user\s+(wants|asks|provided|needs))",
    re.IGNORECASE,
)

# Trigger 4 : the model clearly fabricates a user-turn marker like
# « Réponse de l'utilisateur : », « User: » in a fresh paragraph.
_FAKE_USER_TURN_PATTERN: Final[re.Pattern] = re.compile(
    r"\n+\s*(réponse\s+de\s+l'utilisateur\s*:|user\s*:|utilisateur\s*:)",
    re.IGNORECASE,
)

# Trigger 5 : the model puts the USER in the position of asking IT a question.
# Pattern: "Tu (va|vas|veux|peux) (me|m') (demander|dire|préciser|expliquer
# |indiquer|confirmer|annoncer|raconter)..." — clearly impersonating the user
# asking the bot for clarification. Real user phrasing is "Peux-tu me…",
# never "Tu peux me…" used by the bot to pre-script the user's question.
# Observed 2026-05-07 on ministral-3-8b: « Tu va d'abord me demander par
# quel moyen tu dois envoyer le screenshot ? ».
# Restricted to FUTURE-tense verbs that scenarise the user asking the
# bot a meta-question. « Tu peux me dire » (present) is ambiguous — could
# be a legitimate bot question. « Tu vas me demander » (future) is
# almost always self-dialogue: the bot scripts what the user will ask
# next. Anchor on FUTURE + meta-verbs (demander, expliquer, indiquer,
# raconter) which are rare in legitimate bot prose.
_USER_IMPERSONATION_PATTERN: Final[re.Pattern] = re.compile(
    r"\bTu\s+(va|vas|allais)\s+"
    r"(d['e]?abord\s+)?(me\s+|m['e]?)?"
    r"(demander|expliquer|indiquer|raconter)\b",
    re.IGNORECASE,
)


def trim_self_dialogue(text: str) -> tuple[str, bool]:
    """Return ``(cleaned_text, was_trimmed)``.

    ``was_trimmed=True`` indicates that a self-dialogue pattern was found
    and the suffix has been removed. The cleaned text is the longest
    prefix that does not exhibit any of the patterns.
    """
    if not text or not isinstance(text, str):
        return text or "", False

    cuts: list[int] = []

    m = _QA_LOOP_PATTERN.search(text)
    if m:
        cuts.append(m.start("answer"))

    m = _VOICE_SWAP_PATTERN.search(text)
    if m:
        cuts.append(m.start(1))

    m = _THIRD_PERSON_PATTERN.search(text)
    if m:
        cuts.append(m.start())

    m = _FAKE_USER_TURN_PATTERN.search(text)
    if m:
        cuts.append(m.start())

    m = _USER_IMPERSONATION_PATTERN.search(text)
    if m:
        cuts.append(m.start())

    if not cuts:
        return text, False

    cut_at = min(cuts)
    # Walk back to the last sentence/paragraph end to keep clean prose.
    cleaned = text[:cut_at].rstrip()
    # If the trim leaves a dangling question, append a tasteful ellipsis
    # so the user sees a complete-looking thought rather than a cliffhanger.
    if cleaned.endswith("?"):
        pass  # question is fine, the user can answer it
    elif cleaned and cleaned[-1] not in ".!?":
        cleaned += "…"

    logger.warning(
        "anti_self_dialogue: trimmed %d chars (kept %d). Suffix preview: %r",
        len(text) - len(cleaned), len(cleaned),
        text[cut_at:cut_at + 120],
    )
    return cleaned, True
