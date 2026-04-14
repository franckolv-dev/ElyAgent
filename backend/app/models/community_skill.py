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
"""Community skill model — tracks installed third-party skills.

Each community skill has a declared permission set (scopes) and is loaded
in a controlled environment. Unlike OpenClaw's ClawHub, skills cannot
execute arbitrary shell commands or access the filesystem without explicit
permission grants.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CommunitySkill(Base):
    __tablename__ = "community_skills"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Unique slug identifier (e.g. "notion-sync", "spotify-control")
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Human-readable name
    display_name: Mapped[str] = mapped_column(String(200))
    # Description
    description: Mapped[str] = mapped_column(Text, default="")
    # Author name
    author: Mapped[str] = mapped_column(String(100), default="community")
    # Version string (semver)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    # Icon emoji
    icon: Mapped[str] = mapped_column(String(10), default="")
    # Source URL (git repo or archive)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Declared permissions — JSON array of scope strings
    # e.g. ["internet", "filesystem:read", "shell:restricted"]
    declared_permissions: Mapped[str] = mapped_column(Text, default="[]")
    # Granted permissions — admin must approve declared permissions
    granted_permissions: Mapped[str] = mapped_column(Text, default="[]")
    # Whether the skill is installed and active
    is_installed: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether an admin has reviewed and approved this skill
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    # Number of tools provided
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    # Tool names — JSON array
    tool_names: Mapped[str] = mapped_column(Text, default="[]")
    # Installation path (relative to data/community_skills/)
    install_path: Mapped[str] = mapped_column(String(500), default="")
    # Who installed it
    installed_by: Mapped[str] = mapped_column(String(100), default="")
    # Timestamps
    installed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
