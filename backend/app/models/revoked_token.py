# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/revoked_token.py
# @brief      RevokedToken — persists invalidated JWT refresh token IDs (ARCH-3).
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
