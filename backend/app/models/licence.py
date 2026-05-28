# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/licence.py
# @brief      Licence table — DEPRECATED, kept for DB compatibility only
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#             https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Licence table — DEPRECATED after the 22 May 2026 pivot.

ELY no longer has tiered licensing. The current licence is Elastic
License v2 and applies uniformly to every installation. This table is
kept around because :

  1. Existing installations may already have rows in it — dropping the
     table would force a migration with risk of data loss on legacy
     audit history.
  2. The shape of the table is harmless. No production code writes to
     it anymore (see ``services/licence_service.py``) and the row
     count remains whatever it was at the time of the pivot.

DO NOT add new functionality on top of this table. If you need to
record licence-related state in the future (e.g. a usage telemetry
counter for an Elastic-v2-compliant feature), introduce a new table
with a clear purpose and leave this one as forensic history.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Boolean, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Canonical tier names — keep in sync with services/licence_service.TIER_LIMITS.
LICENCE_TIERS = {"free", "pro", "business", "enterprise", "demo"}


class Licence(Base):
    """A single activated licence row.

    Only one row should be active at a time (`is_active=True`).  Inactive
    rows are kept around as forensic history (audit trail) — never deleted.
    """
    __tablename__ = "licences"

    # ── Identity ──────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ── Tier definition ───────────────────────────────────────────────────
    tier: Mapped[str] = mapped_column(String(20))  # free | pro | business | enterprise | demo
    # NULL = unlimited (enterprise).  For finite tiers, this is enforced by
    # licence_service.check_user_creation_allowed before each user creation.
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)

    customer_label: Mapped[str] = mapped_column(String(200))  # "Personal/Family use" or "Acme Corp"

    # ── Licence key payload ───────────────────────────────────────────────
    # Phase 1 : raw payload, no signature check.
    # Phase 2 : the key will be a base64-encoded JSON payload + Ed25519
    # signature; activate_paid_tier will verify the signature and decode
    # max_users / valid_until from the payload itself.  This column stays
    # the same — only the activation flow changes.
    licence_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Activation metadata ───────────────────────────────────────────────
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    activated_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Decoded / forensic copy of the key payload — Phase 2 will populate
    # this with the JSON decoded from the signed envelope.
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Legacy click-wrap flag — required by the pre-pivot PolyForm Strict
    # licence for the free tier. Elastic License v2 has no consent
    # requirement; the column is kept so historic rows still load.
    consent_personal_use: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
