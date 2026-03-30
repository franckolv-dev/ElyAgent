# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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
