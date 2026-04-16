# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/usage_log.py
# @brief      Usage log model — tracks LLM token usage and skill invocations.
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
"""Usage log model — tracks LLM token usage and skill invocations."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, Text
from app.database import Base


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    # LLM usage
    model = Column(String, nullable=True)          # e.g. "claude-sonnet-4-5"
    provider = Column(String, nullable=True)       # "anthropic", "mistral", etc.
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)          # estimated cost

    # Context
    skill_used = Column(String, nullable=True)     # which skill/tool was invoked
    conversation_id = Column(String, nullable=True)
    channel = Column(String, default="web")        # "web", "telegram", "whatsapp"

    # HITL
    hitl_decision = Column(String, nullable=True)  # "allow", "deny", "ban", None
    hitl_action = Column(Text, nullable=True)      # what action was validated
