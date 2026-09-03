# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/idempotency_store.py
# @brief      Store d'idempotence — « jamais deux fois par accident » (P1/J3).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Idempotence des actions, pilotée par le manifeste.

Une action n'est dédupliquée QUE si son ``CapabilityManifest`` déclare
``idempotency: supported``. La clé est l'empreinte du plan d'action (J2) ; le
résultat mémorisé (borné) est renvoyé tant qu'il n'a pas expiré.

Devient pleinement protecteur quand l'exécution peut être rejouée après une
reprise (file durable / missions, P2) ; en attendant, il neutralise déjà les
ré-émissions accidentelles d'une même action « supported ».
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Borne du résultat mémorisé (même esprit que la troncature de l'historique).
_RESULT_CAP = 16 * 1024


def _aware(dt: datetime) -> datetime:
    """Normalise un datetime (SQLite renvoie souvent du naïf) en UTC aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _ttl_seconds() -> int:
    from app.config import get_settings
    return int(getattr(get_settings(), "idempotency_ttl_seconds", 600) or 600)


def _is_supported(tool_name: str) -> bool:
    from app.services.capability_manifest import Idempotency, get_manifest
    return get_manifest(tool_name).idempotency is Idempotency.SUPPORTED


async def lookup(key: str) -> str | None:
    """Résultat mémorisé non expiré pour ``key``, sinon None (purge le périmé)."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.idempotency import IdempotencyRecord

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        rec = (await db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )).scalar_one_or_none()
        if rec is None:
            return None
        if _aware(rec.expires_at) <= now:
            await db.delete(rec)
            await db.commit()
            return None
        return rec.result


async def record(key: str, user_id: str, capability_id: str, result: str,
                 ttl_seconds: int | None = None) -> None:
    """Mémorise (ou rafraîchit) le résultat d'une action sous sa clé."""
    from app.database import async_session
    from app.models.idempotency import IdempotencyRecord

    ttl = ttl_seconds if ttl_seconds is not None else _ttl_seconds()
    now = datetime.now(timezone.utc)
    bounded = (result or "")[:_RESULT_CAP]
    async with async_session() as db:
        rec = (await db.get(IdempotencyRecord, key))
        if rec is None:
            db.add(IdempotencyRecord(
                key=key, user_id=user_id, capability_id=capability_id,
                result=bounded, created_at=now, expires_at=now + timedelta(seconds=ttl),
            ))
        else:
            rec.result = bounded
            rec.expires_at = now + timedelta(seconds=ttl)
        await db.commit()


# ── Garde haut-niveau utilisée par tool_node ─────────────────────────────


async def check_idempotent(tool_name: str, fingerprint: str) -> str | None:
    """Résultat à court-circuiter si l'action ``supported`` a déjà réussi.

    None si l'outil n'est pas idempotent, ou si aucun enregistrement frais."""
    if not fingerprint or not _is_supported(tool_name):
        return None
    try:
        return await lookup(fingerprint)
    except Exception as exc:  # pragma: no cover — best-effort, jamais bloquant
        logger.debug("idempotency lookup failed (%s): %s", tool_name, exc)
        return None


async def remember(tool_name: str, fingerprint: str, user_id: str, result: str) -> None:
    """Mémorise le résultat d'une action ``supported`` réussie. Best-effort."""
    if not fingerprint or not _is_supported(tool_name):
        return
    try:
        await record(fingerprint, user_id, tool_name, result)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("idempotency record failed (%s): %s", tool_name, exc)
