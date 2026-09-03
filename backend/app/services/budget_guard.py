# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/budget_guard.py
# @brief      Budget LLM quotidien par utilisateur — cap dur opt-in
#             (revue multi-utilisateurs 2026-06-10, constat A-6b).
#
# Pattern d'inspiration : branche salvage/abandoned-agent-tool-policy-
# budget-heartbeat (budget_guard.py Phase 5A, tracking-only). Le tracking
# vit désormais dans analytics_service (UsageLog.cost_usd) — ce module
# n'ajoute QUE le cap.
# @license    MIT
# =============================================================================
"""Per-user daily LLM budget — opt-in hard cap.

``UsageLog.cost_usd`` already records the estimated cost of every
interactive run (and, since this batch, the background ones). What was
missing for multi-user is the CAP: nothing stopped one user — or a script
holding a stolen token — from generating unlimited cloud spend that the
instance owner pays for.

``check_user_budget(user_id)`` sums today's spend (UTC midnight) and
returns a refusal reason once ``ELY_USER_DAILY_BUDGET_USD`` is exceeded.
**Disabled by default (0)** : a single-operator install (Franck) should
never self-block on a heuristic price table ; multi-user instances opt in
via env.

Enforcement points: chat WS, voice WS, scheduler runs, mission ticks
(deferred — a temporarily broke user must not lose their mission).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.database import async_session
from app.models.usage_log import UsageLog

logger = logging.getLogger(__name__)


def daily_budget_usd() -> float:
    """0 (ou valeur invalide) = cap désactivé."""
    try:
        return float(os.environ.get("ELY_USER_DAILY_BUDGET_USD", "0"))
    except ValueError:
        return 0.0


async def get_today_spend_usd(user_id: str) -> float:
    """Somme des coûts estimés du user depuis minuit UTC."""
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    async with async_session() as db:
        row = await db.execute(
            select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0)).where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= midnight,
            )
        )
        return float(row.scalar_one() or 0.0)


async def check_user_budget(user_id: str) -> str | None:
    """None si le run peut partir, sinon le message de refus à afficher.

    Best-effort : une erreur DB ne bloque JAMAIS un run (on log et on
    laisse passer) — le budget est un garde-fou de coût, pas une barrière
    de sécurité.
    """
    limit = daily_budget_usd()
    if limit <= 0:
        return None
    try:
        spent = await get_today_spend_usd(user_id)
    except Exception as exc:
        logger.warning("budget_guard: spend lookup failed for %s: %s", user_id, exc)
        return None
    if spent >= limit:
        logger.info(
            "budget_guard: user %s over daily budget (%.4f$ >= %.2f$)",
            user_id, spent, limit,
        )
        return (
            f"💸 Budget LLM quotidien atteint ({spent:.2f} $ sur "
            f"{limit:.2f} $). Les requêtes reprendront demain (minuit UTC), "
            f"ou demande à l'administrateur d'augmenter "
            f"ELY_USER_DAILY_BUDGET_USD."
        )
    return None
