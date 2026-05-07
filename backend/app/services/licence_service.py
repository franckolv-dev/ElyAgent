# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/licence_service.py
# @brief      Licence lifecycle + tier enforcement (Phase 1)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# =============================================================================
"""Licence service.

Public API
----------
* ``get_active_licence(db)``           — return the single active row, or None.
* ``check_user_creation_allowed(db)``  — guard for POST /auth/register.
* ``activate_free_tier(...)``          — click-wrap free tier (max 4 users).
* ``activate_paid_tier(...)``          — pro / business / enterprise.
* ``get_licence_status(db)``           — dict for the frontend Licence panel.
* ``licence_required_for_install()``   — first-boot detection helper.

There is intentionally no demo / trial flow — the free tier (4 users)
serves as the evaluation path. Customers who need more users buy a
licence directly.

Phase 1 vs Phase 2
------------------
Phase 1 (current) accepts the licence key as a *raw string* and stores
it verbatim — no signature verification.  Phase 2 will introduce
Ed25519 signature verification in :func:`activate_paid_tier` and decode
``max_users`` / ``valid_until`` from the signed payload itself.  The
column layout does not change between phases.

No phone-home, no external network call — every check is local.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.licence import Licence
from app.models.user import User

logger = logging.getLogger(__name__)


# ── Tier definitions (canonical) ─────────────────────────────────────────────
# None means unlimited (enterprise).  These are the *defaults* applied when a
# licence is provisioned through the activation flow ; Phase 2 will override
# them from the decoded payload, but the fallback remains here for free / demo
# (which do not carry a signed payload).
TIER_LIMITS: dict[str, int | None] = {
    "free": 4,
    "pro": 5,
    "business": 25,
    "enterprise": None,  # unlimited
}

# Tiers that require a paid licence key.  Free bypasses this.
PAID_TIERS = {"pro", "business", "enterprise"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce a naïve datetime (as SQLite returns) into UTC-aware.

    SQLAlchemy's ``DateTime(timezone=True)`` is a no-op on SQLite — the
    backend stores ISO strings without offset and returns naïve objects.
    We always treat them as UTC so arithmetic against ``_utcnow()`` works.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _count_users(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count(User.id))) or 0)


async def _deactivate_existing(db: AsyncSession) -> None:
    """Mark every previously active licence row inactive.

    Called before inserting a new active row so the
    "exactly one active licence" invariant holds.
    """
    await db.execute(
        update(Licence).where(Licence.is_active.is_(True)).values(is_active=False)
    )


# ── Public API ───────────────────────────────────────────────────────────────


async def get_active_licence(db: AsyncSession) -> Optional[Licence]:
    """Return the single active licence row, or ``None`` if not yet provisioned."""
    res = await db.execute(
        select(Licence).where(Licence.is_active.is_(True)).order_by(Licence.activated_at.desc())
    )
    return res.scalar_one_or_none()


async def check_user_creation_allowed(
    db: AsyncSession,
) -> tuple[bool, Optional[str]]:
    """Returns ``(allowed, error_message_if_blocked)``.

    Logic
    -----
    1. If there are zero users → always allow (bootstrap admin).
    2. If there is no active licence row → block (must activate first),
       *except* for the bootstrap case above.
    3. If the active licence has ``max_users=NULL`` → unlimited, allow.
    4. Otherwise compare the current user count to ``max_users``.
    """
    user_count = await _count_users(db)

    # Bootstrap admin — first user can always be created, no licence needed.
    if user_count == 0:
        return True, None

    licence = await get_active_licence(db)
    if licence is None:
        return False, (
            "Aucune licence active. L'administrateur doit activer une licence "
            "depuis Paramètres → Licence avant de créer d'autres utilisateurs."
        )

    if licence.max_users is None:
        return True, None  # enterprise / unlimited

    if user_count >= licence.max_users:
        return False, (
            f"Limite de {licence.max_users} utilisateurs atteinte pour la licence "
            f"{licence.tier}. Pour ajouter un utilisateur, passez à un palier "
            f"supérieur sur https://agent-ely.fr/pricing."
        )

    return True, None


async def activate_free_tier(
    db: AsyncSession,
    admin_user_id: str,
    consent: bool,
) -> Licence:
    """Provision the free tier.

    Idempotent : if a free-tier licence is already active, return it as-is.
    Requires ``consent=True`` (click-wrap) — raises ``ValueError`` otherwise,
    which the router maps to HTTP 400.
    """
    existing = await get_active_licence(db)
    if existing is not None and existing.tier == "free":
        return existing  # idempotent

    if not consent:
        raise ValueError(
            "Vous devez confirmer un usage strictement privé, non commercial, "
            "pour activer le palier gratuit."
        )

    await _deactivate_existing(db)

    licence = Licence(
        tier="free",
        max_users=TIER_LIMITS["free"],
        customer_label="Personal/Family use",
        licence_key=None,
        issued_at=_utcnow(),
        valid_until=None,
        activated_by_user_id=admin_user_id,
        is_active=True,
        consent_personal_use=True,
    )
    db.add(licence)
    await db.flush()
    await db.refresh(licence)
    return licence


async def activate_paid_tier(
    db: AsyncSession,
    admin_user_id: str,
    tier: str,
    licence_key: str,
    customer_label: str,
) -> Licence:
    """Activate a paid tier (pro / business / enterprise).

    Phase 1
    -------
    The licence_key is stored as-is.  No signature verification, no payload
    decoding.  ``max_users`` is derived from :data:`TIER_LIMITS`.

    Phase 2 (TODO)
    --------------
    The licence_key will be a base64-encoded JSON payload + Ed25519
    signature.  We will :
      * verify the signature against the embedded public key,
      * decode the payload to extract ``max_users``, ``valid_until``,
        ``customer_label``,
      * reject the activation if the signature is invalid or expired.
    """
    if tier not in PAID_TIERS:
        raise ValueError(
            f"Palier inconnu : {tier!r}. Attendu : pro, business ou enterprise."
        )

    if not licence_key or not licence_key.strip():
        raise ValueError("La clé de licence est requise pour ce palier.")

    if not customer_label or not customer_label.strip():
        raise ValueError("Le nom de l'organisation est requis pour ce palier.")

    # TODO: Phase 2 — verify Ed25519 signature, decode payload to get
    #       max_users / valid_until / customer_label.  For now we trust the
    #       caller's claimed tier and apply the canonical limit.
    max_users = TIER_LIMITS[tier]
    raw_payload: dict | None = None
    valid_until: datetime | None = None  # Phase 2 will populate from payload

    await _deactivate_existing(db)

    now = _utcnow()
    licence = Licence(
        tier=tier,
        max_users=max_users,
        customer_label=customer_label.strip(),
        licence_key=licence_key.strip(),
        issued_at=now,
        valid_until=valid_until,
        activated_by_user_id=admin_user_id,
        is_active=True,
        raw_payload=raw_payload,
        consent_personal_use=False,
    )
    db.add(licence)
    await db.flush()
    await db.refresh(licence)
    return licence


async def get_licence_status(db: AsyncSession) -> dict:
    """Return a JSON-serialisable status dict for the frontend Licence panel.

    Shape :
        {
          "tier": "business" | None,
          "max_users": 25 | None,
          "current_users": 12,
          "customer_label": "Acme Corp",
          "valid_until": "2027-05-03T...",
          "days_remaining": 365 | None,
          "is_demo_expired": False,
          "is_provisioned": True,
          "consent_personal_use": False,
          "activated_at": "2026-05-03T...",
        }
    """
    licence = await get_active_licence(db)
    current_users = await _count_users(db)

    if licence is None:
        return {
            "tier": None,
            "max_users": None,
            "current_users": current_users,
            "customer_label": None,
            "valid_until": None,
            "days_remaining": None,
            "is_demo_expired": False,
            "is_provisioned": False,
            "consent_personal_use": False,
            "activated_at": None,
        }

    days_remaining: int | None = None
    valid_until = _aware(licence.valid_until)
    if valid_until is not None:
        delta = valid_until - _utcnow()
        days_remaining = max(0, int(delta.total_seconds() // 86400))

    return {
        "tier": licence.tier,
        "max_users": licence.max_users,
        "current_users": current_users,
        "customer_label": licence.customer_label,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "days_remaining": days_remaining,
        "is_demo_expired": False,  # legacy field, always False since demo removed
        "is_provisioned": True,
        "consent_personal_use": bool(licence.consent_personal_use),
        "activated_at": _aware(licence.activated_at).isoformat() if licence.activated_at else None,
    }


def licence_required_for_install() -> bool:
    """Stub helper — returns True if no active licence row yet.

    Kept synchronous for use in non-async contexts.  Always wraps a fresh
    session so it can be called from anywhere (cli, scripts, etc.).
    """
    # Sync wrapper — runs the async check with its own event loop helper.
    # Use the async ``get_active_licence`` directly when possible.
    import asyncio
    from app.database import async_session

    async def _check() -> bool:
        async with async_session() as db:
            return (await get_active_licence(db)) is None

    try:
        return asyncio.run(_check())
    except RuntimeError:
        # Already inside a running loop — caller should use the async API.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_check())
        finally:
            loop.close()
