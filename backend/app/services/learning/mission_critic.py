# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/mission_critic.py
# @brief      Sprint 3.7 Jalon 4 — LLM-as-judge post-mission critic.
#             A separate model reads the full step trace of a just-ended
#             mission and answers 5 yes/no/score questions in strict JSON.
#             Persists the verdict in `mission_critiques`.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.5.0
# =============================================================================
"""Post-mortem LLM-as-judge — Sprint 3.7 §4.

Why a separate critic ?  A Mission's `final_summary` is written by the
agent itself, so it's subject to self-evaluation bias ("I succeeded" /
"all good" patterns common with completion-trained models).  A neutral
external model (DeepSeek v4-pro by default) reads the audit trail
*after* the mission ends and grades it honestly.

Policy (design note §4.1) :

  status ∈ {failed, aborted} → 100% sampled
  status == "completed"      → 1/5 sampled (deterministic via mission_id hash)
  status ∈ {running, paused, draft, planning} → SKIP (wait for terminal)

One critique per mission max (UNIQUE on mission_id) ; running the cron
twice on the same mission is a no-op.

Env config :

  CRITIC_TIER (default "C") :
      "C"           → DeepSeek v4-pro / Mistral Large 3 (production default)
      "MAINTENANCE" → Gemma 4 E4B-it local / Ministral 3B
                       (cheaper, lower quality — for cost-constrained
                        setups or testing gpt-oss-20b-MXFP4-Q4 as critic)
  CRITIC_DISABLED (default false) :
      Set to "true" to short-circuit the cron entirely.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.database import async_session
from app.models.mission import (
    MISSION_TERMINAL_STATUSES,
    Mission,
    MissionStep,
)
from app.models.mission_critique import MissionCritique
from app.services.learning.prompt_version import prompt_hash

logger = logging.getLogger(__name__)


# Sampling rate for "completed" status (1/N). 5 = 20% sample.
COMPLETED_SAMPLE_DENOMINATOR: int = 5

# Step trace truncation (one step row → bounded prompt size).
MAX_STEPS_IN_PROMPT: int = 30
MAX_FIELD_CHARS_IN_PROMPT: int = 400


_CRITIC_PROMPT = """\
Tu es un critique externe d'agents IA. Voici le déroulé d'une mission qui \
vient de se terminer. Évalue-la HONNÊTEMENT et SÉVÈREMENT.

Particulièrement : détecte le « succès en façade » — quand l'agent prétend \
avoir réussi (final_summary positif) alors que les étapes montrent un \
échec, une boucle, ou un workaround insatisfaisant.

Mission goal  : {goal}
Status final  : {status}
Final summary (par l'agent lui-même, biais possible) :
{final_summary}

Étapes ({n_steps} au total, dernières {n_shown} affichées) :
{steps_compact}

Réponds UNIQUEMENT avec un objet JSON STRICT de la forme :
{{
  "quality_score": 0,        // 0 = échec total, 100 = exemplaire
  "honest_completion": true, // false si final_summary ment / minimise un échec
  "wasted_effort": false,    // true si retries inutiles, dead-ends, churn
  "user_should_have_been_warned": false,
  "main_issue": ""           // 1 phrase, "" si tout va bien
}}
"""


# ─────────────────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────────────────


def should_critique(mission: Mission) -> bool:
    """Apply the design note §4.1 sampling policy.

      - failed / aborted → always critique
      - completed        → 1 in COMPLETED_SAMPLE_DENOMINATOR (deterministic
                           on mission_id hash so the same mission either
                           runs or doesn't, regardless of cron timing)
      - any non-terminal status → wait
    """
    if mission.status not in MISSION_TERMINAL_STATUSES:
        return False
    if mission.status in ("failed", "aborted"):
        return True
    # status == "completed" → deterministic 1/N sampling
    h = hashlib.sha256(str(mission.id).encode("utf-8")).digest()
    bucket = h[0] % COMPLETED_SAMPLE_DENOMINATOR
    return bucket == 0


def _is_critic_disabled() -> bool:
    return os.environ.get("CRITIC_DISABLED", "").lower() in (
        "1", "true", "yes", "on",
    )


def _critic_tier_label() -> str:
    raw = os.environ.get("CRITIC_TIER", "C").strip().upper()
    if raw not in ("A", "B", "C", "IMG", "MAINTENANCE"):
        return "C"
    return raw


# ─────────────────────────────────────────────────────────────────────────
# Prompt assembly + parsing
# ─────────────────────────────────────────────────────────────────────────


def _compact_step(step: MissionStep) -> str:
    """One readable line per step, with bounded width."""
    parts = [
        f"#{step.iteration}",
        f"phase={step.phase}",
    ]
    if step.tool_name:
        parts.append(f"tool={step.tool_name}")
    if step.success is not None:
        parts.append(f"success={step.success}")
    if step.duration_ms:
        parts.append(f"{step.duration_ms}ms")
    line = " ".join(parts)
    extras: list[str] = []
    if step.evaluation:
        extras.append(f"eval: {step.evaluation[:MAX_FIELD_CHARS_IN_PROMPT]}")
    if step.tool_output:
        extras.append(f"out: {step.tool_output[:MAX_FIELD_CHARS_IN_PROMPT]}")
    if extras:
        line = line + "  | " + "  | ".join(extras)
    return line


def compose_prompt(mission: Mission, steps: list[MissionStep]) -> str:
    """Assemble the critique prompt — design note §4.2 verbatim shape.

    Truncates to the last MAX_STEPS_IN_PROMPT steps to keep token cost
    bounded on long missions.
    """
    n_total = len(steps)
    shown = steps[-MAX_STEPS_IN_PROMPT:] if n_total > MAX_STEPS_IN_PROMPT else steps
    steps_compact = "\n".join(_compact_step(s) for s in shown) or "(aucune étape enregistrée)"
    return _CRITIC_PROMPT.format(
        goal=(mission.goal or mission.title or "(non défini)")[:1000],
        status=mission.status,
        final_summary=(mission.final_summary or "(vide)")[:2000],
        n_steps=n_total,
        n_shown=len(shown),
        steps_compact=steps_compact,
    )


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def parse_verdict(raw: str) -> dict | None:
    """Parse a critic LLM response.

    Returns a dict with all 5 expected keys (filling defaults for missing
    ones) or ``None`` if the response cannot be coerced into JSON at all.
    """
    text = _strip_json_fences(raw or "")
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("mission_critic: invalid JSON from LLM: %.200s", text)
        return None
    if not isinstance(data, dict):
        return None
    # Coerce + default
    try:
        qs = int(data.get("quality_score", 0))
    except (TypeError, ValueError):
        qs = 0
    return {
        "quality_score": max(0, min(100, qs)),
        "honest_completion": bool(data.get("honest_completion", True)),
        "wasted_effort": bool(data.get("wasted_effort", False)),
        "user_should_have_been_warned": bool(
            data.get("user_should_have_been_warned", False)
        ),
        "main_issue": str(data.get("main_issue", "") or "")[:1000] or None,
    }


# ─────────────────────────────────────────────────────────────────────────
# LLM call — wrapped so tests can monkeypatch
# ─────────────────────────────────────────────────────────────────────────


async def _call_critic_llm(prompt: str) -> tuple[str, int, str]:
    """Run the critic LLM. Returns (raw_response, tokens_used, model_name).

    Token count is best-effort (LangChain ``response_metadata`` often
    surfaces it, but providers diverge — falls back to 0).
    """
    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    tier_label = _critic_tier_label()
    tier_enum = {
        "A": ComplexityTier.SIMPLE,
        "B": ComplexityTier.MEDIUM,
        "C": ComplexityTier.COMPLEX,
        "IMG": ComplexityTier.IMAGE,
        "MAINTENANCE": ComplexityTier.MAINTENANCE,
    }.get(tier_label, ComplexityTier.COMPLEX)

    llm = get_llm_for_tier(tier_enum)
    model_name = getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
    response = await llm.ainvoke(
        [{"role": "user", "content": prompt}],
        config={"callbacks": []},
    )
    raw = getattr(response, "content", "") or ""
    md = getattr(response, "response_metadata", None) or {}
    tokens = 0
    if isinstance(md, dict):
        usage = md.get("token_usage") or md.get("usage") or {}
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens", 0) or 0)
    return raw, tokens, str(model_name)


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


async def critique_mission(mission_id: str) -> int | None:
    """End-to-end pipeline for one mission.

    Returns the `mission_critiques.id` row id on success, ``None`` if :
      - The mission doesn't exist
      - Policy says no (not terminal, or unlucky on completed sampling)
      - A critique already exists (UNIQUE constraint)
      - The LLM call fails (swallowed, will retry on next cron tick)

    Always sets `mission.critic_run_at` so the cron stops scanning this
    mission — even on a "no-critique" decision.
    """
    if _is_critic_disabled():
        return None

    started = time.monotonic()

    async with async_session() as db:
        mission = (
            await db.execute(select(Mission).where(Mission.id == mission_id))
        ).scalar_one_or_none()
        if mission is None:
            return None
        if not should_critique(mission):
            # Mark as evaluated (skipped) so the cron doesn't re-scan forever
            mission.critic_run_at = datetime.now(timezone.utc)
            await db.commit()
            return None
        # Avoid re-critique (the UNIQUE on mission_id will reject it anyway,
        # but we save the LLM round-trip cost).
        existing = (
            await db.execute(
                select(MissionCritique).where(MissionCritique.mission_id == mission_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            mission.critic_run_at = datetime.now(timezone.utc)
            await db.commit()
            return existing.id

        # Load steps for the prompt
        steps_rows = (
            await db.execute(
                select(MissionStep)
                .where(MissionStep.mission_id == mission_id)
                .order_by(MissionStep.iteration.asc())
            )
        ).scalars().all()
        steps = list(steps_rows)

        prompt_text = compose_prompt(mission, steps)
        critic_prompt_hash = prompt_hash(_CRITIC_PROMPT)  # version of the TEMPLATE

    # LLM call outside the session — providers can be slow
    try:
        raw, tokens, model_name = await _call_critic_llm(prompt_text)
    except Exception as exc:
        logger.warning(
            "mission_critic: LLM call failed for mission=%s : %s",
            mission_id, exc,
        )
        # Don't set critic_run_at — let the cron retry on the next tick
        return None

    verdict = parse_verdict(raw)
    if verdict is None:
        logger.warning(
            "mission_critic: unparseable verdict for mission=%s — got %r",
            mission_id, raw[:200],
        )
        return None

    duration_ms = int((time.monotonic() - started) * 1000)

    async with async_session() as db:
        # Re-read mission to refresh row (avoid using stale instance across sessions)
        mission = (
            await db.execute(select(Mission).where(Mission.id == mission_id))
        ).scalar_one_or_none()
        if mission is None:
            return None
        row = MissionCritique(
            mission_id=mission_id,
            critic_model=model_name,
            quality_score=verdict["quality_score"],
            honest_completion=verdict["honest_completion"],
            wasted_effort=verdict["wasted_effort"],
            user_should_have_been_warned=verdict["user_should_have_been_warned"],
            main_issue=verdict["main_issue"],
            prompt_version=critic_prompt_hash,
            tokens_used=tokens,
            duration_ms=duration_ms,
        )
        try:
            db.add(row)
            mission.critic_run_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "mission_critic: mission=%s critic_model=%s qs=%d honest=%s wasted=%s",
                mission_id, model_name, verdict["quality_score"],
                verdict["honest_completion"], verdict["wasted_effort"],
            )
            return row.id
        except Exception as exc:
            # Most likely UNIQUE collision because of concurrent cron run
            logger.warning(
                "mission_critic: persist failed for mission=%s : %s",
                mission_id, exc,
            )
            await db.rollback()
            return None


async def run_pending_critiques(batch_limit: int = 10) -> int:
    """Cron entry — scan terminal missions still missing a critic_run_at
    and critique up to ``batch_limit`` of them per tick.

    Returns the number of critiques persisted in this batch.
    """
    if _is_critic_disabled():
        return 0
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Mission)
                .where(Mission.status.in_(MISSION_TERMINAL_STATUSES))
                .where(Mission.critic_run_at.is_(None))
                .order_by(Mission.completed_at.desc().nullslast())
                .limit(batch_limit)
            )
        ).scalars().all()
        mission_ids = [m.id for m in rows]
    persisted = 0
    for mid in mission_ids:
        result = await critique_mission(mid)
        if result is not None:
            persisted += 1
        # Small yield so we don't hog the loop if the cron tick is busy
        await asyncio.sleep(0)
    if mission_ids:
        logger.info(
            "mission_critic: tick processed %d mission(s), %d critiqued",
            len(mission_ids), persisted,
        )
    return persisted
