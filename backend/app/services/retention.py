# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/retention.py
# @brief      Rétention des tables de signaux à forte croissance
#             (revue multi-utilisateurs 2026-06-10, §4 mineurs).
# @license    Elastic License 2.0
# =============================================================================
"""Nightly retention job for high-growth signal tables.

Aucune politique de rétention n'existait : audit, usage, signaux learning
(hitl_refusals, hallucination_blocks, provider_switches, error_logs)
croissent à chaque tour de chat — N fois plus vite en multi-utilisateurs.
Sur SQLite, un gros fichier = checkpoints WAL plus longs = fenêtres de
lock plus larges pour tout le monde.

Périmètre VOLONTAIREMENT restreint aux tables de télémétrie :

- ``audit_logs``, ``hitl_refusals``, ``hallucination_blocks``,
  ``provider_switches``, ``error_logs`` → ``ELY_SIGNALS_RETENTION_DAYS``
  (défaut 90 j, 0 = désactivé) ;
- ``usage_logs`` → ``ELY_USAGE_RETENTION_DAYS`` (défaut 365 j — sert le
  dashboard analytics ET le budget quotidien, on garde large).

NE SONT PAS purgés (données utilisateur ou carburant d'apprentissage) :
``messages``/conversations, ``mission_critiques`` (bench mining 3.7.3),
``failure_cases`` (UI tool-gaps), tables FTS (suivent leurs messages).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.database import async_session

logger = logging.getLogger(__name__)


def _days(env_var: str, default: int) -> int:
    try:
        return int(os.environ.get(env_var, str(default)))
    except ValueError:
        return default


async def run_retention() -> dict[str, int]:
    """Purge les lignes au-delà de la fenêtre. Retourne {table: supprimées}."""
    from app.models.audit import AuditLog
    from app.models.error_log import ErrorLog
    from app.models.hallucination_block import HallucinationBlock
    from app.models.hitl_refusal import HitlRefusal
    from app.models.provider_switch import ProviderSwitch
    from app.models.usage_log import UsageLog

    signals_days = _days("ELY_SIGNALS_RETENTION_DAYS", 90)
    usage_days = _days("ELY_USAGE_RETENTION_DAYS", 365)

    now = datetime.now(timezone.utc)
    removed: dict[str, int] = {}

    targets: list[tuple[str, object, object, int]] = []
    if signals_days > 0:
        cutoff = now - timedelta(days=signals_days)
        targets += [
            ("audit_logs", AuditLog, AuditLog.created_at, cutoff),
            ("hitl_refusals", HitlRefusal, HitlRefusal.created_at, cutoff),
            ("hallucination_blocks", HallucinationBlock, HallucinationBlock.created_at, cutoff),
            ("provider_switches", ProviderSwitch, ProviderSwitch.created_at, cutoff),
            ("error_logs", ErrorLog, ErrorLog.created_at, cutoff),
        ]
    if usage_days > 0:
        targets.append(
            ("usage_logs", UsageLog, UsageLog.timestamp, now - timedelta(days=usage_days)),
        )

    for table, model, ts_col, cutoff in targets:
        try:
            async with async_session() as db:
                result = await db.execute(delete(model).where(ts_col < cutoff))
                await db.commit()
                count = int(result.rowcount or 0)
                if count:
                    removed[table] = count
        except Exception as exc:
            logger.warning("retention: purge de %s échouée : %s", table, exc)

    if removed:
        logger.info(
            "retention: %s",
            ", ".join(f"{t}={n}" for t, n in removed.items()),
        )
    return removed
