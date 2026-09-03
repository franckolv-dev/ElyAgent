# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/error_log.py
# @brief      Error memory — every tool/mission failure captured for Sprint 3.7
#             auto-improvement and current-turn avoidance ("I already tried that").
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.3.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Error memory store — Sprint 2.5.

In V1 this is **write-only** — we capture every tool/mission failure so the
data is ready for Sprint 3.7 (auto-improvement loop). Reads happen in V2.

Retention policy (design note §7): rolling 90 days, with rows where
`recovered=True` archived immediately (next nightly cron) since they're no
longer actionable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ErrorLog(Base):
    """One row per tool/mission failure observed during agent execution."""

    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    # Mission this error occurred in, if any (some errors fire outside missions)
    mission_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Name of the tool that raised, e.g. "drive_find_duplicates"
    tool_name: Mapped[str] = mapped_column(String(120), index=True)
    # JSON-serialized args with PII redacted by the anonymisation pipeline
    args_redacted: Mapped[str] = mapped_column(Text)
    # Python exception class name, e.g. "ValueError", "httpx.TimeoutException"
    error_type: Mapped[str] = mapped_column(String(120), index=True)
    # Single-line error message
    error_msg: Mapped[str] = mapped_column(Text)
    # Full traceback (optional — may be truncated for very deep stacks)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM tier in use when the error fired ("A", "B", "C", "IMG")
    tier_llm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # True once a later step / retry / fallback recovered the situation
    recovered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Filled when the cron archives recovered rows
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sprint 3.7 Jalon 3 — sha256[:8] of the system prompt active when the
    # error fired. Lets the dashboard correlate error rates with specific
    # prompt versions.
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Sprint 4d J1 — "learned" si le tool était un python_tool ACTIF de ce
    # user au moment de l'erreur, sinon "builtin". NULL = rows pré-J1 ou
    # origine indéterminable (lookup best-effort). Permet d'agréger les
    # stats de graduation sans JOIN fragile sur learned_skills.
    tool_origin: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
