# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/api_key.py
# @brief      Personal API keys — long-lived auth for the MCP server + API.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Personal API keys — long-lived credentials for non-browser clients.

Why a separate key type (vs the JWT or the extension token)?
------------------------------------------------------------
The web app's ``access_token`` JWT expires in ~60 minutes — fine for a
browser, useless for an external MCP client (Claude Desktop, scripts…)
that connects to ELY's MCP server and must stay authenticated for days.
``ExtensionToken`` is conceptually scoped to the browser extension; a
user must be able to revoke MCP access without killing their extension.

This model adds a dedicated personal API key:
- Long-lived (no expiry; user revokes at will)
- Named by the user ("Claude Desktop", "Laptop CLI")
- Hash-stored (plaintext shown ONCE at creation; only the last 4 chars
  are kept for UI identification)
- Tracks ``last_used_at`` so dormant keys are visible
- Revocable from Settings without touching web/extension sessions

Key format: ``ely_api_<64 hex chars>`` (256 bits of entropy). The
``ely_api_`` prefix lets the MCP middleware spot it at a glance and lets
secret-scanning (GitHub, gitleaks) flag accidental commits.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    last_4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Optional User relationship (one user → many keys)
    user = relationship("User", lazy="select")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
