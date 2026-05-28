# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/system_config.py
# @brief      Async helpers for the SystemConfig table
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Async helpers for the SystemConfig table.

Priority: DB value > env value > default
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)


async def get_config(key: str, fallback: str = "") -> str:
    """Read a config value from DB, fallback to provided default."""
    try:
        async with async_session() as db:
            result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
            row = result.scalar_one_or_none()
            if row and row.value:
                return row.value
    except Exception as exc:
        logger.warning("system_config get failed for key=%s: %s", key, exc)
    return fallback


async def set_config(key: str, value: str, *, is_secret: bool = False, description: str = "") -> None:
    """Upsert a config value in DB."""
    async with async_session() as db:
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
            row.is_secret = is_secret
            if description:
                row.description = description
        else:
            db.add(SystemConfig(
                key=key,
                value=value,
                is_secret=is_secret,
                description=description or key,
            ))
        await db.commit()


async def delete_config(key: str) -> None:
    """Remove a config entry."""
    async with async_session() as db:
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            await db.delete(row)
            await db.commit()


async def list_configs(db: AsyncSession) -> list[SystemConfig]:
    """Return all config entries (secrets masked in caller)."""
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    return list(result.scalars().all())
