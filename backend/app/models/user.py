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

from sqlalchemy import String, Boolean, DateTime, Text
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
    # UI / agent reply language. ISO 639-1 code. Default "fr" — Éli was
    # designed in French. The frontend sets this when the user clicks the
    # LangSwitcher; the agent prompt is rebuilt every turn to honor it.
    language: Mapped[str] = mapped_column(String(2), default="fr", server_default="fr")
