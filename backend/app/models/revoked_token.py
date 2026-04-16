# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/revoked_token.py
# @brief      RevokedToken — persists invalidated JWT refresh token IDs (ARCH-3).
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""RevokedToken — persists invalidated JWT refresh token IDs (ARCH-3).

A row is inserted on logout (or forced session revocation).
The /refresh endpoint rejects any token whose jti appears here.
Rows are purged automatically once the token's exp has passed.
"""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    # jti = JWT ID claim — a UUID assigned at token creation
    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    # exp mirrors the token's expiry so we can purge stale rows
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
