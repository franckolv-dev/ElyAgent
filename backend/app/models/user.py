# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/user.py
# @brief      SQLAlchemy User model
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
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
    # UI / agent reply language. ISO 639-1 code. Default "fr" — Éli was
    # designed in French. The frontend sets this when the user clicks the
    # LangSwitcher; the agent prompt is rebuilt every turn to honor it.
    language: Mapped[str] = mapped_column(String(2), default="fr", server_default="fr")
    # Preferred channel for HITL push notifications. None / "all" = broadcast
    # to all linked channels (legacy behaviour). Specific value silences the
    # others — useful when multiple channels are linked and the user doesn't
    # want a notif on each every time. Allowed values :
    #   "ely_android" — native Android app (FCM)
    #   "ntfy"        — ntfy push (lockscreen action buttons, no app needed)
    #   "telegram"    — Telegram bot inline keyboard
    #   "discord"     — Discord DM with reactions
    #   "slack"       — Slack DM with Block Kit
    #   "web_only"    — only the web frontend (silent on phone)
    #   "all" / null  — broadcast to every linked channel (default)
    # The web frontend is ALWAYS notified regardless of this preference,
    # because it must sync the chat UI in real time.
    hitl_preferred_channel: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )
    # PII sovereignty toggle. When True, the agent forces every tier-B/C call
    # to the Mistral EU chain (Large → Medium → Small) instead of the user's
    # default cloud provider (typically DeepSeek). Off by default; opt-in via
    # Settings. Local + maintenance tiers are unaffected (they're already local).
    # See app/services/sovereignty.py for the routing override.
    sovereignty_strict: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    # Conversational onboarding — Éli initiates a guided chat at first
    # login to learn the user's vocabulary, preferred names, Gmail labels,
    # calendar names, routines, strict rules, etc. Stored as a series of
    # facts in memory_manager + structured mappings in user_vocabulary.
    # `completed_at` = user finished the flow (or did it later by clicking
    #   "Refaire l'onboarding" in Settings).
    # `skipped_at`   = user clicked "Plus tard". Re-prompt next login but
    #   not nag every screen change.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    onboarding_skipped_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    # Index of the next question to ask. Lets the user resume mid-flow
    # if they close the tab. -1 = not started yet.
    onboarding_step: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # How many times the user clicked "Plus tard". After 3, we stop
    # re-prompting at login — they can still launch it manually from
    # Settings → Mon compte → « Refaire l'onboarding ».
    onboarding_skip_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # TTS preference — when False, the agent's text replies are NOT read
    # aloud automatically by the avatar. Default True (legacy behaviour).
    # The user can toggle the per-message « Voix active / muette » button
    # on the avatar panel, and the choice now survives page reload.
    # Voice INPUT (microphone) is a separate concept — the dedicated voice
    # mode overlay handles its own enable/disable lifecycle.
    tts_auto_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
