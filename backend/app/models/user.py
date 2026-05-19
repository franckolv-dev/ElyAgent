# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/user.py
# @brief      SQLAlchemy User model
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
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
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")  # "admin" | "user"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    google_credentials: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    telegram_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, default=None)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True, default=None)
    slack_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, default=None)
    discord_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, default=None)
    fcm_token: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── Heartbeat (Phase 5A — autonomie continue inspirée d'openclaw) ──
    # Disabled by default. When enabled, a background job invokes the agent
    # every `heartbeat_interval_minutes` with the heartbeat prompt + this
    # user's `heartbeat_context` (free-form markdown). The agent acts only
    # if the context describes pending work; otherwise it returns HEARTBEAT_OK.
    heartbeat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    heartbeat_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    heartbeat_context: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
