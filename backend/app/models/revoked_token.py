# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
# -----------------------------------------------------------------------------
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
