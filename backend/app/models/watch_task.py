# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/watch_task.py
# @brief      Watch task model — monitors URLs/queries for changes.
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
"""Watch task model — monitors URLs/queries for changes."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from app.database import Base


class WatchTask(Base):
    __tablename__ = "watch_tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    # type: "url" (monitor a specific URL) or "search" (monitor search results)
    watch_type = Column(String, nullable=False, default="url")
    target = Column(String, nullable=False)  # URL or search query
    check_interval_minutes = Column(Integer, default=60)
    notify_channel = Column(String, default="web")  # "web" or "telegram"
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_content_hash = Column(String, nullable=True)
    last_content_preview = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    change_count = Column(Integer, default=0)
