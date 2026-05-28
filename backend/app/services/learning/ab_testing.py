# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/ab_testing.py
# @brief      Sprint 3.7 Jalon 5 — A/B testing stub for system prompts.
#             Deterministic per-user variant selection + composite
#             weighted scoring over the learning signal tables.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""A/B testing — Sprint 3.7 §5.

Two-part scaffolding :

1. **Variant selection** (`select_variant`) — hashes the user_id to a
   bucket [0, 100) ; routes to "B" if bucket < env-configured threshold,
   else "A". Deterministic for a given user — the same person stays on
   the same variant across sessions.

2. **Composite scoring** (`score_variants`) — for a given prompt key,
   reads the 4 learning signal sources (HITL refusals, hallucinations,
   user feedback, mission completion) over a time window, computes
   per-variant rates, then a weighted composite score
   (0.3/0.3/0.2/0.2 by design note §5.2 default weights).

V1 status :
  - The variants registry holds only "A" at boot — the production
    prompt. When a real B comes (e.g. a shorter prompt experiment),
    register it as a separate Python const and add to the dict.
  - No actual scoring happens until both variants have ≥ N samples ;
    the API simply reports per-variant rates and a recommended winner
    when the gap is big enough.

Future (V2) :
  - Externalise variants to YAML under ``backend/app/agent/prompts/``
    (audit Gemini priority medium, cf. design note §5.4).
  - Plug into a UI so a non-developer can declare a new variant.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.database import async_session

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# 1. Variant registry + selection
# ─────────────────────────────────────────────────────────────────────────


def _load_base_prompt() -> str:
    """Lazy import to avoid heavy LangGraph load at module import time."""
    from app.agent.nodes import _SYSTEM_PROMPT_BASE
    return _SYSTEM_PROMPT_BASE


def _build_default_variants() -> dict[str, dict[str, str]]:
    """Initial registry. V1 has only one variant per key ; B is added
    when someone wants to run a real experiment."""
    return {
        "system_prompt_base": {
            "A": _load_base_prompt(),
        },
    }


# Lazy singleton so tests can clear / repopulate
_VARIANTS: dict[str, dict[str, str]] | None = None


def _get_variants() -> dict[str, dict[str, str]]:
    global _VARIANTS
    if _VARIANTS is None:
        _VARIANTS = _build_default_variants()
    return _VARIANTS


def register_variant(prompt_key: str, variant_name: str, prompt_text: str) -> None:
    """Add or override a variant. Idempotent. Useful in tests and to
    register a 'B' variant from another module at boot.
    """
    variants = _get_variants()
    variants.setdefault(prompt_key, {})[variant_name] = prompt_text


def list_prompt_keys() -> list[str]:
    return sorted(_get_variants().keys())


def list_variants(prompt_key: str) -> list[str]:
    return sorted(_get_variants().get(prompt_key, {}).keys())


def _b_pct_for(prompt_key: str) -> int:
    """Read ``AB_<KEY_UPPER>_B_PCT`` env var (0-100). Default 0 = no split."""
    raw = os.environ.get(f"AB_{prompt_key.upper()}_B_PCT", "0")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, val))


def _bucket_for_user(user_id: str) -> int:
    """Deterministic [0, 100) bucket. Same user_id → same bucket forever.

    Uses the first 4 bytes of sha256 (32-bit integer) modulo 100 — picking
    only one byte (256 values) is too coarse for a clean 100-way split
    (256/100 = 2.56 introduces a ~6% skew). 4 bytes = 4.3 billion values,
    skew becomes negligible.
    """
    if not user_id:
        return 0
    h = hashlib.sha256(user_id.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % 100


def select_variant(prompt_key: str, user_id: str) -> tuple[str, str]:
    """Return ``(variant_name, prompt_text)`` for this (key, user).

    Logic :
      - If the key has only one variant → that one (no split).
      - Else : bucket = hash(user_id) % 100 ;
               variant = "B" if bucket < AB_<KEY>_B_PCT else "A".
      - If "B" is selected but doesn't exist for this key → fall back to "A".

    Always returns a (name, text) pair — never raises on missing key,
    falls back to ``("A", _SYSTEM_PROMPT_BASE)``.
    """
    variants = _get_variants().get(prompt_key)
    if not variants:
        # Key never registered — emergency fall-through to the live prompt
        return "A", _load_base_prompt()
    names = list(variants.keys())
    if len(names) == 1:
        only = names[0]
        return only, variants[only]
    # Multi-variant split
    bucket = _bucket_for_user(user_id)
    threshold = _b_pct_for(prompt_key)
    chosen = "B" if (bucket < threshold and "B" in variants) else "A"
    if chosen not in variants:
        # Asked for A but no A registered — pick first available
        chosen = names[0]
    return chosen, variants[chosen]


# ─────────────────────────────────────────────────────────────────────────
# 2. Composite scoring
# ─────────────────────────────────────────────────────────────────────────


# Default weights — design note §5.2.
DEFAULT_WEIGHTS = {
    "hitl_refusal_rate": 0.30,   # lower is better → inverted in formula
    "hallucination_rate": 0.30,  # lower is better → inverted
    "feedback_mean": 0.20,       # range [-1, +1], normalised to [0, 1]
    "completion_rate": 0.20,     # already 0-1, higher is better
}


def ab_score(metrics: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """Composite score in [0, 1] — higher is better.

    Missing metrics are treated as worst case (0 contribution).
    """
    w = weights or DEFAULT_WEIGHTS

    def _safe(key: str, default: float) -> float:
        v = metrics.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    hitl_rate = _safe("hitl_refusal_rate", 1.0)        # worst = 100% refusals
    hallu_rate = _safe("hallucination_rate", 1.0)      # worst = always hallucinating
    fb_mean = _safe("feedback_mean", -1.0)             # worst = all thumbs-down
    completion = _safe("completion_rate", 0.0)         # worst = never completing

    return (
        w["hitl_refusal_rate"] * (1.0 - max(0.0, min(1.0, hitl_rate)))
        + w["hallucination_rate"] * (1.0 - max(0.0, min(1.0, hallu_rate)))
        + w["feedback_mean"] * ((max(-1.0, min(1.0, fb_mean)) + 1.0) / 2.0)
        + w["completion_rate"] * max(0.0, min(1.0, completion))
    )


def _parse_window(window: str) -> timedelta:
    """Accepts ``"7d"``, ``"30d"``, ``"90d"``, ``"24h"``. Defaults to 7d."""
    if not window:
        return timedelta(days=7)
    s = window.strip().lower()
    try:
        if s.endswith("d"):
            return timedelta(days=int(s[:-1]))
        if s.endswith("h"):
            return timedelta(hours=int(s[:-1]))
    except ValueError:
        pass
    return timedelta(days=7)


async def compute_variant_metrics(prompt_version: str, window: timedelta) -> dict[str, Any]:
    """Aggregate the 4 sub-metrics for a given prompt_version hash.

    Returns dict with :
      n_samples_hitl, n_samples_hallu, n_samples_feedback, n_samples_missions,
      hitl_refusal_rate (refusals / messages with same prompt_version,
        approximated by mission_steps having that hash for V1),
      hallucination_rate (blocks / messages),
      feedback_mean (-1..+1),
      completion_rate (completed / terminal).
    """
    from app.models.feedback import Feedback
    from app.models.hallucination_block import HallucinationBlock
    from app.models.hitl_refusal import HitlRefusal
    from app.models.mission import MISSION_TERMINAL_STATUSES, Mission, MissionStep

    since = datetime.now(timezone.utc) - window

    async with async_session() as db:
        # n_messages proxy: number of mission_steps tagged with this prompt_version
        # (the most reliable per-turn marker we currently have).
        n_messages_res = await db.execute(
            select(func.count(MissionStep.id)).where(
                MissionStep.prompt_version == prompt_version,
                MissionStep.created_at >= since,
            )
        )
        n_messages = int(n_messages_res.scalar() or 0)

        # HITL refusals
        n_hitl_res = await db.execute(
            select(func.count(HitlRefusal.id)).where(
                HitlRefusal.prompt_version == prompt_version,
                HitlRefusal.created_at >= since,
            )
        )
        n_hitl = int(n_hitl_res.scalar() or 0)

        # Hallucination blocks
        n_hallu_res = await db.execute(
            select(func.count(HallucinationBlock.id)).where(
                HallucinationBlock.prompt_version == prompt_version,
                HallucinationBlock.created_at >= since,
            )
        )
        n_hallu = int(n_hallu_res.scalar() or 0)

        # Feedback mean + count
        fb_count_res = await db.execute(
            select(func.count(Feedback.id), func.avg(Feedback.rating)).where(
                Feedback.prompt_version == prompt_version,
                Feedback.created_at >= since,
            )
        )
        fb_row = fb_count_res.first() or (0, None)
        n_feedback = int(fb_row[0] or 0)
        feedback_mean = float(fb_row[1]) if fb_row[1] is not None else 0.0

        # Mission completion rate (over terminal status, scoped by mission_steps
        # carrying the prompt_version)
        mission_ids_subq = (
            select(MissionStep.mission_id)
            .where(MissionStep.prompt_version == prompt_version)
            .distinct()
        )
        n_terminal_res = await db.execute(
            select(func.count(Mission.id)).where(
                Mission.id.in_(mission_ids_subq),
                Mission.status.in_(MISSION_TERMINAL_STATUSES),
                Mission.completed_at >= since,
            )
        )
        n_terminal = int(n_terminal_res.scalar() or 0)

        n_completed_res = await db.execute(
            select(func.count(Mission.id)).where(
                Mission.id.in_(mission_ids_subq),
                Mission.status == "completed",
                Mission.completed_at >= since,
            )
        )
        n_completed = int(n_completed_res.scalar() or 0)

    completion_rate = (n_completed / n_terminal) if n_terminal > 0 else 0.0
    # Rate denominator : n_messages floor 1 to avoid div by zero
    safe_msg = max(1, n_messages)
    return {
        "n_messages": n_messages,
        "n_samples_hitl": n_hitl,
        "n_samples_hallu": n_hallu,
        "n_samples_feedback": n_feedback,
        "n_terminal_missions": n_terminal,
        "n_completed_missions": n_completed,
        "hitl_refusal_rate": n_hitl / safe_msg,
        "hallucination_rate": n_hallu / safe_msg,
        "feedback_mean": feedback_mean,
        "completion_rate": completion_rate,
    }


async def score_variants(prompt_key: str, window: timedelta) -> dict[str, Any]:
    """Aggregate metrics for every registered variant of ``prompt_key``.

    Returns :
      {
        "key": "system_prompt_base",
        "window": "7d",
        "variants": {
          "A": {"prompt_version": "abc12345", "metrics": {...}, "score": 0.81},
          "B": {"prompt_version": "def67890", "metrics": {...}, "score": 0.74},
        },
        "winner": "A" | "B" | null,  // null if insufficient samples
        "warning": ""                // explanation when no winner
      }
    """
    from app.services.learning.prompt_version import prompt_hash

    variants = _get_variants().get(prompt_key, {})
    out_variants: dict[str, dict] = {}
    for name, text in variants.items():
        pv = prompt_hash(text)
        metrics = await compute_variant_metrics(pv, window)
        out_variants[name] = {
            "prompt_version": pv,
            "metrics": metrics,
            "score": round(ab_score(metrics), 4),
        }

    # Pick a winner only if every variant has at least MIN_SAMPLES messages
    MIN_SAMPLES = 50
    winner: str | None = None
    warning = ""
    if not out_variants:
        warning = f"no variants registered for key {prompt_key!r}"
    elif len(out_variants) < 2:
        warning = "only one variant registered — register a B variant to start A/B testing"
    elif any(v["metrics"]["n_messages"] < MIN_SAMPLES for v in out_variants.values()):
        warning = (
            f"insufficient samples — every variant needs ≥ {MIN_SAMPLES} messages "
            f"in the window before a winner can be declared"
        )
    else:
        # Highest score wins (must beat by at least 0.02 for confidence)
        sorted_variants = sorted(
            out_variants.items(), key=lambda kv: kv[1]["score"], reverse=True
        )
        top, second = sorted_variants[0], sorted_variants[1]
        if top[1]["score"] - second[1]["score"] >= 0.02:
            winner = top[0]
        else:
            warning = (
                "winner ambiguous — top two variants are within 0.02 "
                "(more samples needed)"
            )

    return {
        "key": prompt_key,
        "window": _humanize_window(window),
        "variants": out_variants,
        "winner": winner,
        "warning": warning,
    }


def _humanize_window(w: timedelta) -> str:
    if w.total_seconds() % 86400 == 0:
        return f"{int(w.total_seconds() // 86400)}d"
    return f"{int(w.total_seconds() // 3600)}h"
