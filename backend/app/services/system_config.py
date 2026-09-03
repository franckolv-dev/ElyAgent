# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/system_config.py
# @brief      Async helpers for the SystemConfig table
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
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
    """Read a config value from DB, fallback to provided default.

    B-11 (revue 2026-06-10) : ``decrypt`` est auto-descriptif (préfixe
    ``enc:gcm:``) — les valeurs legacy en clair passent telles quelles.
    """
    try:
        async with async_session() as db:
            result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
            row = result.scalar_one_or_none()
            if row and row.value:
                from app.services.secrets_at_rest import decrypt
                return decrypt(row.value)
    except Exception as exc:
        logger.warning("system_config get failed for key=%s: %s", key, exc)
    return fallback


async def set_config(key: str, value: str, *, is_secret: bool = False, description: str = "") -> None:
    """Upsert a config value in DB.

    B-11 : ``is_secret=True`` ne faisait que masquer l'UI — la valeur
    restait en CLAIR dans SQLite. Désormais chiffrée AES-GCM au repos.
    """
    if is_secret and value:
        from app.services.secrets_at_rest import encrypt
        value = encrypt(value)
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


async def migrate_plaintext_secrets() -> int:
    """Chiffre en une passe les secrets encore en clair (boot, B-11).

    Couvre ``system_config`` (``is_secret=True``) et
    ``llm_instances.api_key``. Idempotent — les valeurs déjà ``enc:gcm:``
    sont laissées telles quelles. Retourne le nombre de valeurs migrées.
    """
    from app.models.llm_instance import LLMInstance
    from app.services.secrets_at_rest import encrypt, is_encrypted

    migrated = 0
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(SystemConfig).where(SystemConfig.is_secret == True)  # noqa: E712
            )).scalars().all()
            for row in rows:
                if row.value and not is_encrypted(row.value):
                    row.value = encrypt(row.value)
                    migrated += 1
            instances = (await db.execute(select(LLMInstance))).scalars().all()
            for inst in instances:
                if inst.api_key and not is_encrypted(inst.api_key):
                    inst.api_key = encrypt(inst.api_key)
                    migrated += 1
            await db.commit()
        if migrated:
            logger.info(
                "secrets_at_rest: %d secret(s) en clair chiffrés (migration B-11)",
                migrated,
            )
    except Exception as exc:
        logger.warning("migrate_plaintext_secrets failed: %s", exc)
    return migrated


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
