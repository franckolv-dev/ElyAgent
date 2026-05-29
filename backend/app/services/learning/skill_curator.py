# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_curator.py
# @brief      Sprint 4b Phase 5.a — weekly curator for auto-generated skills
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Skill curator — Sprint 4b Phase 5.a.

Background maintenance for auto-generated `LearnedSkill` rows. Runs
weekly (Monday 03:00 UTC by default) via APScheduler, transitions
unused skills through `active → stale → archived` according to
configurable age thresholds, and respects the `pinned` opt-out flag.

Pattern d'inspiration : Hermes `agent/curator.py` (background
maintenance, inactivity-triggered, only mutates agent-created
skills). Voir docs/external-references/hermes-skills-self-improvement.md
§2 Composant C.

Strict invariants
-----------------
- **Never delete**. Archive is the most-terminal state the curator
  produces. Users delete manually if they want via the UI.
- **Only auto-generated skills are mutated**. `user_added` and
  `imported_marketplace` skills are immune — the user owns them.
- **Pinned skills bypass everything**. The user has explicitly said
  "keep this around" — we listen.
- **`candidate` and `rejected` skills are immune**. Candidates are
  waiting for HITL admin review (Phase 4.a) ; rejected skills are
  terminal forensic history.

Lifecycle rules (configurable via env)
--------------------------------------
- `LEARNED_SKILLS_STALE_AFTER_DAYS`     default 30 — `active` →
                                        `stale` after this many days
                                        without a `skill_view` call.
- `LEARNED_SKILLS_ARCHIVE_AFTER_DAYS`   default 90 — `stale` → `archived`
                                        after this many days IN the
                                        `stale` state (so total inactivity
                                        is stale_after + archive_after).
- `LEARNED_SKILLS_CURATOR_DISABLED`     truthy → skip the cycle entirely
                                        (useful for users who don't want
                                        any auto-maintenance).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus

logger = logging.getLogger(__name__)


DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 90


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        logger.warning("skill_curator: invalid %s=%r — using default %d", name, raw, default)
        return default


def _is_disabled() -> bool:
    return _truthy(os.getenv("LEARNED_SKILLS_CURATOR_DISABLED"))


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce a naïve datetime (as SQLite returns) into UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Stale detection ─────────────────────────────────────────────────────────


def _is_active_stale(
    skill: LearnedSkill,
    now: datetime,
    stale_after_days: int,
) -> bool:
    """An active skill is stale if it has NOT been used (via skill_view)
    in the last `stale_after_days` days.

    Anchor: max(`last_used_at`, `created_at`) — a brand new skill that
    was promoted today but never called yet should NOT be stale on
    its very first curator run. We give it the same window from
    creation as any other.
    """
    if skill.status != SkillStatus.ACTIVE:
        return False
    last = _aware(skill.last_used_at) or _aware(skill.created_at)
    if last is None:
        return False  # defensive — shouldn't happen, no created_at
    age = now - last
    return age >= timedelta(days=stale_after_days)


def _is_stale_archivable(
    skill: LearnedSkill,
    now: datetime,
    archive_after_days: int,
) -> bool:
    """A stale skill graduates to archived after `archive_after_days`
    additional days without use. Anchored on `updated_at` (which the
    transition stamps) so the window is FROM-STALE, not from-creation."""
    if skill.status != SkillStatus.STALE:
        return False
    anchor = _aware(skill.last_used_at) or _aware(skill.updated_at) or _aware(skill.created_at)
    if anchor is None:
        return False
    age = now - anchor
    return age >= timedelta(days=archive_after_days)


# ── Public API ──────────────────────────────────────────────────────────────


async def _load_eligible_skills(db: AsyncSession) -> list[LearnedSkill]:
    """Pull every auto-generated, non-pinned, non-terminal skill.

    Candidate / rejected are excluded — see module docstring invariants.
    Pinned skills are excluded — they bypass all transitions.
    """
    result = await db.execute(
        select(LearnedSkill).where(
            LearnedSkill.source == SkillSource.AUTO_GENERATED,
            LearnedSkill.pinned.is_(False),
            LearnedSkill.status.in_({SkillStatus.ACTIVE, SkillStatus.STALE}),
        )
    )
    return list(result.scalars().all())


async def run_curator_cycle(
    now: datetime | None = None,
    *,
    stale_after_days: int | None = None,
    archive_after_days: int | None = None,
) -> dict[str, Any]:
    """Run one curator pass.

    Parameters allow injection in tests; in prod the cron job calls
    this with defaults (env-driven).

    Returns a structured summary ::

        {
          "skipped_disabled": False,
          "considered": <int>,
          "promoted_to_stale": <int>,
          "promoted_to_archived": <int>,
          "now": "<isoformat>",
        }

    Never raises — a DB outage logs at WARNING and returns counts of 0.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if _is_disabled():
        logger.info("skill_curator: cycle skipped — LEARNED_SKILLS_CURATOR_DISABLED is set")
        return {
            "skipped_disabled": True,
            "considered": 0,
            "promoted_to_stale": 0,
            "promoted_to_archived": 0,
            "now": now.isoformat(),
        }

    if stale_after_days is None:
        stale_after_days = _int_env("LEARNED_SKILLS_STALE_AFTER_DAYS", DEFAULT_STALE_AFTER_DAYS)
    if archive_after_days is None:
        archive_after_days = _int_env("LEARNED_SKILLS_ARCHIVE_AFTER_DAYS", DEFAULT_ARCHIVE_AFTER_DAYS)

    summary: dict[str, Any] = {
        "skipped_disabled": False,
        "considered": 0,
        "promoted_to_stale": 0,
        "promoted_to_archived": 0,
        "now": now.isoformat(),
    }

    try:
        async with async_session() as db:
            eligible = await _load_eligible_skills(db)
            summary["considered"] = len(eligible)

            to_stale: list[str] = []
            to_archive: list[str] = []
            for skill in eligible:
                if _is_active_stale(skill, now, stale_after_days):
                    to_stale.append(skill.id)
                elif _is_stale_archivable(skill, now, archive_after_days):
                    to_archive.append(skill.id)

            if to_stale:
                await db.execute(
                    update(LearnedSkill)
                    .where(LearnedSkill.id.in_(to_stale))
                    .values(status=SkillStatus.STALE, updated_at=now)
                )
                summary["promoted_to_stale"] = len(to_stale)
                logger.info(
                    "skill_curator: %d skill(s) active → stale", len(to_stale),
                )

            if to_archive:
                await db.execute(
                    update(LearnedSkill)
                    .where(LearnedSkill.id.in_(to_archive))
                    .values(status=SkillStatus.ARCHIVED, updated_at=now)
                )
                summary["promoted_to_archived"] = len(to_archive)
                logger.info(
                    "skill_curator: %d skill(s) stale → archived", len(to_archive),
                )

            if to_stale or to_archive:
                await db.commit()
    except Exception as exc:
        logger.warning("skill_curator: cycle failed (%s) — counts stay at 0", exc)

    return summary
