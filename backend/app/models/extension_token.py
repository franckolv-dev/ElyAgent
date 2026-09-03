# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/extension_token.py
# @brief      ExtensionToken — long-lived auth tokens for the ELY browser
#             extension (Sprint 0.5).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Long-lived auth tokens for the browser extension.

Why a separate token type?
--------------------------
The regular `access_token` JWT used by the web app expires in 60 minutes.
That's fine for a browser session but disastrous for a background-running
extension: the WebSocket gets kicked every hour and the user has to
re-paste a token from DevTools. The whole "ELY acts in your browser"
flow becomes friction.

This model adds a separate token type, scoped explicitly to the
extension, with the following properties:

- Long-lived (no expiry by default; user can revoke at will)
- Named by the user ("Mac Studio Chrome", "Personal MacBook")
- Hash-stored (we only show the plaintext ONCE at creation; thereafter
  only the last 4 chars are stored for UI identification)
- Tracks `last_used_at` so the user can see if a token is dormant
- Revocable from the Settings UI without affecting web app sessions

Token format: `ely_ext_<48 hex chars>` (192 bits of entropy).
The `ely_ext_` prefix lets the auth middleware distinguish them from
regular JWTs at a glance, and lets accidental leaks be detected
automatically by GitHub's secret scanning.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExtensionToken(Base):
    __tablename__ = "extension_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # SHA-256 of the raw token. The plaintext is only seen by the user
    # ONCE, at creation time — never logged, never persisted.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Last 4 chars of the plaintext, stored for UI display ("ends in …f3a4").
    last_4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # When set, the token is revoked and the WebSocket handshake will
    # reject it. We keep the row instead of deleting to preserve audit.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Optional User relationship (one user → many tokens)
    user = relationship("User", lazy="select")

    def is_active(self) -> bool:
        return self.revoked_at is None
