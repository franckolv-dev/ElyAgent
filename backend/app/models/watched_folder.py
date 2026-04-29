# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/watched_folder.py
# @brief      SQLAlchemy WatchedFolder model — RAG auto-indexing
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""WatchedFolder model — local folders auto-indexed into the RAG knowledge base.

Replaces the manual one-file-at-a-time upload workflow with a "set it and
forget it" indexing : the user selects a folder via the ELY Desktop
daemon, and a periodic cron walks the tree, picks up new / modified
files (detected by mtime + size), and ingests them into Qdrant via
``rag_service.ingest_document``. Files no longer present are NOT removed
from the index by default — that would be lossy if the user just moves
files around. A separate `prune` action (manual) handles cleanup.

Schema choices :
- ``path`` : absolute path on the user's machine. Validated by the daemon
  at scan time (reject if outside permitted directories — same guard as
  desktop_list_dir).
- ``recursive`` : whether to walk subdirectories. Default True.
- ``include_extensions`` : comma-separated whitelist (defaults to the
  RAG-supported set : pdf, txt, md, csv, json, doc, docx, xls, xlsx).
  Empty string means "use server default".
- ``exclude_paths`` : comma-separated substrings that exclude matching
  paths (e.g. ".git,/node_modules,~/.ssh"). Defensive default.
- ``last_scan_at`` : when the last scan completed (success or partial).
- ``last_scan_status`` : "ok" | "partial" | "error" | "running" | "pending".
- ``last_scan_message`` : human-readable summary ("Indexed 12 new files,
  skipped 3 unchanged, 1 error").
- ``files_indexed`` : cumulative count of files currently in the index for
  this folder. Updated after each scan.
- ``enabled`` : if False, the folder is kept in the list but cron skips it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Default supported file extensions (lower-cased, no dot).
# Mirrors the set handled by app/services/rag_service._extract_text_*.
DEFAULT_INCLUDE_EXTENSIONS = "pdf,txt,md,csv,json,doc,docx,xls,xlsx"

# Defensive default exclusion list — paths or substrings that should never
# be auto-indexed even if the user picks a parent folder. Uses substring
# match (not glob), case-insensitive.
DEFAULT_EXCLUDE_PATHS = (
    ".git,"
    "node_modules,"
    "__pycache__,"
    ".venv,"
    "venv/,"
    ".ssh,"
    ".gnupg,"
    ".aws,"
    ".cache,"
    ".Trash,"
    ".DS_Store"
)


class WatchedFolder(Base):
    __tablename__ = "watched_folders"
    __table_args__ = (
        # Same path can't be watched twice for the same user.
        UniqueConstraint("user_id", "path", name="uq_watched_folders_user_path"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    include_extensions: Mapped[str] = mapped_column(
        String(500), default=DEFAULT_INCLUDE_EXTENSIONS, nullable=False
    )
    exclude_paths: Mapped[str] = mapped_column(
        String(2000), default=DEFAULT_EXCLUDE_PATHS, nullable=False
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_scan_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    last_scan_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
