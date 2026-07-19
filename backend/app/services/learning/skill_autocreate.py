# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_autocreate.py
# @brief      Jalon 1 (portage Hermes) — autonomous skill-creation tick
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Autonomous skill-creation tick — Jalon 1 (portage Hermes).

THE root-cause fix from the 2026-06-15 audit + Hermes comparison: Ely's skill
funnel had every part EXCEPT the trigger. ``run_full_loop`` (create → eval →
iterate) was only ever called by an admin endpoint — ``skill_orchestrator``
even said so : « It's also what a future cron job will call ». That cron was
never written, so despite dozens of unprocessed ``failure_cases`` waiting as
fuel, zero playbooks were ever created autonomously. Hermes creates skills
with no human in the loop ; this tick restores that for Ely, reusing the
existing engine unchanged.

Registered as a periodic interval job next to the mission-critic and
diagnostician loops (``main.py``). Each tick:
  - is a no-op when ``SKILL_AUTOCREATE_DISABLED`` is set (kill switch) ;
  - finds users with at least ``MIN_UNPROCESSED_CASES`` unprocessed
    ``failure_cases`` (the raw material the creator clusters into playbooks) ;
  - runs one creator batch per such user (capped at ``MAX_USERS_PER_TICK``)
    with ``auto_promote=True`` so a passing playbook goes live immediately ;
  - never raises — a failure on one user is logged and skipped.

This is deliberately off the request hot-path (a background tick, like the
diagnostician), faithful to Hermes' inactivity-triggered curator philosophy
rather than blocking a user's conversation on a tier-S generation.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import func, select

from app.database import async_session
from app.models.failure_case import FailureCase
from app.services.learning.skill_orchestrator import run_full_loop

logger = logging.getLogger(__name__)

# A user needs at least this many unprocessed failure_cases before we spend
# tier-S tokens drafting playbooks for them. Below the floor, there isn't
# enough signal to cluster a meaningful pattern.
MIN_UNPROCESSED_CASES = 3
# Cap users handled per tick so one busy instance can't trigger a token storm.
MAX_USERS_PER_TICK = 3
# Clusters drafted per user per tick (passed straight to run_full_loop).
BATCH_SIZE = 3

_TRUTHY = {"1", "true", "yes", "on"}


def _is_disabled() -> bool:
    return str(os.getenv("SKILL_AUTOCREATE_DISABLED", "")).strip().lower() in _TRUTHY


async def _users_with_pending_cases(limit: int) -> list[str]:
    """User ids with ≥ ``MIN_UNPROCESSED_CASES`` unprocessed failure_cases,
    most-pending first."""
    async with async_session() as db:
        rows = (await db.execute(
            select(FailureCase.user_id, func.count().label("n"))
            .where(FailureCase.processed_at.is_(None))
            .group_by(FailureCase.user_id)
            .having(func.count() >= MIN_UNPROCESSED_CASES)
            .order_by(func.count().desc())
            .limit(limit)
        )).all()
    return [r[0] for r in rows if r[0]]


async def run_pending_skill_creation() -> dict:
    """One autonomous skill-creation tick. Never raises.

    Returns a small summary dict (also useful for tests + admin observability).
    """
    if _is_disabled():
        return {"status": "disabled", "users": 0}

    summary = {
        "status": "ok",
        "users": 0,
        "drafts": 0,
        "passed": 0,
        "promoted": 0,
    }
    try:
        user_ids = await _users_with_pending_cases(MAX_USERS_PER_TICK)
    except Exception as exc:
        logger.warning("skill_autocreate: user scan failed: %s", exc)
        return {"status": "error", "users": 0}

    for uid in user_ids:
        try:
            result = await run_full_loop(
                user_id=uid, batch_size=BATCH_SIZE, auto_promote=True,
            )
            totals = result.get("totals", {})
            summary["users"] += 1
            summary["drafts"] += int(totals.get("drafts", 0) or 0)
            summary["passed"] += int(totals.get("passed", 0) or 0)
            summary["promoted"] += sum(
                1 for lp in result.get("loops", []) if lp.get("auto_promoted")
            )
        except Exception as exc:
            logger.warning("skill_autocreate: loop failed for %s: %s", uid, exc)

    if summary["drafts"] or summary["passed"]:
        logger.info(
            "skill_autocreate tick: users=%d drafts=%d passed=%d promoted=%d",
            summary["users"], summary["drafts"], summary["passed"],
            summary["promoted"],
        )
    # C4-2 / arbitrage 19-07 — l'auto-promotion des playbooks est CONSERVÉE
    # (texte à faible risque, le curator fait le ménage) mais plus jamais
    # silencieuse : push d'information à chaque activation automatique.
    if summary.get("promoted"):
        try:
            from app.services.learning.candidate_notify import (
                notify_playbook_activated,
            )

            await notify_playbook_activated(int(summary["promoted"]))
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("skill_autocreate: notify skipped: %s", exc)
    return summary
