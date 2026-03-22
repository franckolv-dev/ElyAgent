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
