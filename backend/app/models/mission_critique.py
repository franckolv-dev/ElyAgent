# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/mission_critique.py
# @brief      Sprint 3.7 Jalon 1 — LLM-as-judge verdict per mission.
#             Filled by the post-mortem cron (Jalon 4) for failed/aborted
#             missions (100%) + 1/5 of completed (sample for "façade
#             success" detection).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# @version    1.5.0
# =============================================================================
"""LLM-as-judge verdict per mission — Sprint 3.7 §4.3.

Rationale (design note §4) : a mission's `final_summary` is written by
the agent itself and therefore subject to self-evaluation bias. A
separate critic (DeepSeek pro by default, see `critic_llm_provider`
config) reads the full step trace post-completion and answers 5
questions in strict JSON. Persisted here for dashboard aggregation and
A/B testing.

Trigger policy (B+C) :
  - status in (failed, aborted) → 100% sampling
  - status == completed         → 1/5 deterministic sampling

One critique per mission max (UNIQUE on mission_id).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MissionCritique(Base):
    """Post-mortem critique of a mission — one row per mission max."""

    __tablename__ = "mission_critiques"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("missions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # Model that ran the critique, e.g. "deepseek-v4-pro" or "gpt-oss-20b-mxfp4-q4"
    critic_model: Mapped[str] = mapped_column(String(120))
    # 0 = total failure, 100 = exemplary — the judge's overall score
    quality_score: Mapped[int] = mapped_column(Integer)
    # True if the agent's final_summary truthfully matches the executed steps
    honest_completion: Mapped[bool] = mapped_column(Boolean)
    # True if the trace shows useless retries, dead-end paths, churn
    wasted_effort: Mapped[bool] = mapped_column(Boolean)
    # True if the agent claimed success but should have warned the user it failed
    user_should_have_been_warned: Mapped[bool] = mapped_column(Boolean)
    # Single-sentence summary of the main issue (NULL when quality_score is high)
    main_issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256[:8] of the CRITIQUE prompt template used (not the agent's)
    prompt_version: Mapped[str] = mapped_column(String(16))
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
