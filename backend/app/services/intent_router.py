# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/intent_router.py
# @brief      Intent router — decide which model tier handles each request
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Intent router — decide which model tier handles each request.

Phase 1 : rule-based scoring (fast, no external calls).
Phase 2 : embedding similarity against labelled examples from Qdrant
          (weighted by user feedback scores stored in the DB).

Scoring formula
---------------
Base score : 50  (neutral → goes to LLM by default)
Threshold  : settings.slm_complexity_threshold  (default 40)

  score ≤ threshold  →  SLM  (Ollama, local, cheap)
  score >  threshold →  LLM  (API, capable, expensive)

Positive contributors (→ complex → LLM) :
  Complex keywords    : +25 each  (capped at +50)
  Long message        : +20 if > 150 chars
  Multi-sentence      : +15 if > 2 sentences
  Subordinate clauses : +10
  Has URL / file path : +15

Negative contributors (→ simple → SLM) :
  Simple tool keywords : -15 each  (capped at -45)
  Short message        : -10 if < 50 chars
  Single sentence      : -5
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from langchain_core.messages import BaseMessage


class ModelTier(str, Enum):
    SLM = "slm"   # local Ollama
    LLM = "llm"   # API (Claude / Gemini / …)


@dataclass
class RoutingDecision:
    tier: ModelTier
    score: int          # 0-100 raw complexity score
    reason: str         # human-readable (for logs and Phase-2 data collection)


# ── Keyword lists ──────────────────────────────────────────────────────────────

# Each tuple : (pattern, weight)  — weight is POSITIVE (→ complex → LLM)
_COMPLEX_PATTERNS: list[tuple[str, int]] = [
    # Reasoning / explanation
    (r"\bpourquoi\b",                   25),
    (r"\bexplique[- ]?(moi|nous)?\b",   25),
    (r"\bcomment fonctionne\b",         25),
    (r"\bquelle[s]? (est|sont) la[s]? diff[eé]rence[s]?\b", 25),
    (r"\bavan[tc]age[s]? et inconv[eé]nient[s]?\b", 25),
    # Analysis & comparison
    (r"\banalys[ée]\b",                 25),
    (r"\bcompar[ée]\b",                 25),
    (r"\b[eé]value\b",                  25),
    (r"\bdiagnos[ité]\b",               20),
    # Writing long-form content
    (r"\br[eé]dig[ée]\b",               25),
    (r"\b[eé]cris? (un|une|le|la)\b",  20),
    (r"\bcompose[rz]?\b",               20),
    (r"\bg[eé]n[eè]re? (un|une) (document|rapport|lettre|article|pr[eé]sentation)\b", 30),
    (r"\bformule[rz]?\b",               15),
    (r"\bproposes?[-\s]?moi\b",         20),
    # Code & debugging
    (r"\b(programme[rz]?|code[rz]?|script)\b", 25),
    (r"\bd[eé]bogues?\b",               25),
    (r"\bbug\b",                        20),
    # Strategy
    (r"\bstrat[eé]gie\b",               25),
    (r"\bplan d.action\b",              25),
    # Summarizing complex documents
    (r"\br[eé]sum[ée] (ce|le|ce|cet|cette|ces)\b", 20),
    (r"\blis (ce|le|ce|cet|cette|ces) (pdf|document|fichier|texte)\b", 20),
]

# Negative weight patterns (→ simple → SLM)
_SIMPLE_PATTERNS: list[tuple[str, int]] = [
    # Weather
    (r"\bm[eé]t[eé]o\b",               15),
    (r"\btemps qu.il fait\b",           15),
    (r"\btemp[eé]rature\b",             15),
    # Calendar / agenda
    (r"\bagenda\b",                     15),
    (r"\bcalendrier\b",                 15),
    (r"\brdv\b",                        15),
    (r"\brendez[- ]?vous\b",            15),
    (r"\bplanning\b",                   10),
    # Email (check only, not write)
    (r"\bmes (mails?|e?mails?)\b",      15),
    (r"\bbo[iî]te mail\b",              15),
    (r"\blire mes (mails?|e?mails?)\b", 15),
    # Simple search
    (r"\bcherche (sur le web|sur internet|sur google)\b", 15),
    (r"\brecherche\b",                  10),
    # Notes
    (r"\bprends une note\b",            15),
    (r"\bm[eé]morise\b",                15),
    (r"\bmes notes\b",                  10),
    # Timer / reminder
    (r"\brappelle[- ]?moi\b",           15),
    (r"\bwithin\b",                     5),
    # Translation
    (r"\btraduis\b",                    15),
    (r"\btraduction\b",                 10),
    # Maps / directions
    (r"\bitin[eé]raire\b",              15),
    (r"\btrajet\b",                     10),
    (r"\bcomment aller [aà]\b",         15),
    # Tasks
    (r"\bmes t[aâ]ches\b",              10),
    (r"\bto[- ]?do\b",                  10),
    # Weather / news simple
    (r"\bactualit[eé]s?\b",             10),
    (r"\bnews\b",                       10),
    # Quick calc
    (r"\bcalcule\b",                    10),
    (r"\bconvertis\b",                  10),
    # QR code
    (r"\bqr code\b",                    15),
    # Whatsapp simple send
    (r"\benvoie (un |le )?(message|whatsapp|sms)\b", 10),
]

_SUBORDINATE_RE = re.compile(
    r"\b(parce que|puisque|afin de|afin que|pour que|bien que|quoique"
    r"|si\s+tu|si\s+vous|si\s+je|si\s+on|[aà] condition que)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://|/[a-z0-9._/-]{5,}", re.IGNORECASE)


class IntentRouter:
    """Route each user message to SLM or LLM based on complexity score.

    Phase 2 hook: override ``_phase2_adjustment`` to apply embedding-based
    corrections from Qdrant feedback scores.
    """

    def route(
        self,
        message: str,
        history: list[BaseMessage] | None = None,
    ) -> RoutingDecision:
        from app.config import get_settings
        settings = get_settings()

        if not settings.slm_enabled:
            return RoutingDecision(
                tier=ModelTier.LLM,
                score=100,
                reason="SLM disabled",
            )

        score = self._score(message, history or [])
        threshold = settings.slm_complexity_threshold

        # Phase 2 hook — returns 0 in Phase 1
        score = max(0, min(100, score + self._phase2_adjustment(message, score)))

        if score <= threshold:
            return RoutingDecision(
                tier=ModelTier.SLM,
                score=score,
                reason=f"simple task (score={score})",
            )
        return RoutingDecision(
            tier=ModelTier.LLM,
            score=score,
            reason=f"complex request (score={score})",
        )

    # ── Scoring ────────────────────────────────────────────────────────────

    def _score(self, message: str, history: list[BaseMessage]) -> int:
        text = message.lower()
        score = 50  # neutral baseline

        # ── Complexity signals (→ LLM) ────────────────────────────────────
        complex_hits = 0
        for pattern, weight in _COMPLEX_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
                complex_hits += 1
                if complex_hits >= 2:   # cap at +50
                    break

        if len(message) > 150:
            score += 20
        elif len(message) > 80:
            score += 10

        sentences = [s.strip() for s in re.split(r"[.!?]", message) if s.strip()]
        if len(sentences) > 2:
            score += 15

        if _SUBORDINATE_RE.search(text):
            score += 10

        if _URL_RE.search(message):
            score += 15

        # ── Simplicity signals (→ SLM) ────────────────────────────────────
        simple_hits = 0
        for pattern, weight in _SIMPLE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                score -= weight
                simple_hits += 1
                if simple_hits >= 3:    # cap at -45
                    break

        if len(message) < 50:
            score -= 10

        if len(sentences) <= 1:
            score -= 5

        return max(0, min(100, score))

    # ── Phase 2 hook ───────────────────────────────────────────────────────

    def _phase2_adjustment(self, message: str, current_score: int) -> int:
        """Phase 2: return a Δscore derived from Qdrant feedback similarity.

        In Phase 1 this always returns 0.
        In Phase 2, override this to:
        - Embed the message
        - Retrieve the N most similar past interactions from Qdrant
        - Compute a weighted average of their feedback scores
        - Return a delta that nudges routing toward the historically preferred tier
        """
        return 0


# ── Singleton ─────────────────────────────────────────────────────────────────

_router: IntentRouter | None = None


def get_intent_router() -> IntentRouter:
    global _router
    if _router is None:
        _router = IntentRouter()
    return _router
