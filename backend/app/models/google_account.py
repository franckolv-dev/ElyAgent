# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/google_account.py
# @brief      SQLAlchemy GoogleAccount model — multi-account per user
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""GoogleAccount model — one ELY user can link several Google accounts.

Replaces the legacy `User.google_credentials` (single account) with a 1-to-N
relationship so a user can drive several mailboxes (perso, pro, …) from the
same agent. The legacy column is kept for backward compat — it always
mirrors the row flagged ``is_default = True``.

Schema choices:
- ``alias`` : short human label ("perso", "pro", "side-project") chosen by
  the user when adding the account. Unique per (user_id) — the agent uses
  it to disambiguate ("envoie un mail depuis mon pro").
- ``email`` : populated from the ID token at OAuth callback. Unique per
  (user_id) so the same Google account can't be linked twice with two
  different aliases.
- ``is_default`` : exactly one row per user has this set to True. Enforced
  in the router layer (no DB constraint — SQLite doesn't support partial
  unique indexes well across all versions).
- ``credentials_json`` : full JSON blob from the Google OAuth flow
  (access_token, refresh_token, scopes, expiry). Same shape as the legacy
  ``User.google_credentials`` so downstream tools see no schema change.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GoogleAccount(Base):
    __tablename__ = "google_accounts"
    __table_args__ = (
        # An alias must be unique per user (you can't have two "perso")
        UniqueConstraint("user_id", "alias", name="uq_google_accounts_user_alias"),
        # The same Google email can't be linked twice for the same user
        UniqueConstraint("user_id", "email", name="uq_google_accounts_user_email"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    credentials_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
