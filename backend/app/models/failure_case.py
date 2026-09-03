# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/failure_case.py
# @brief      Sprint 4b Phase 1 — replay-able failure capture
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#             https://opensource.org/licenses/MIT
# =============================================================================
"""Failure cases — Sprint 4b Phase 1 (auto-amélioration par création de skills).

Sprint 3.7 captures 4 typed signals (hitl_refusals, hallucination_blocks,
provider_switches, mission_critiques) but they only describe **what** went
wrong — not enough to *replay* the conversation and try a fix.

A FailureCase is a normalized, replay-able pointer: it links to one signal
row, carries the minimal payload needed to reconstruct the conversation
state at the failure point, and tracks whether a skill creator has tried
to address it yet.

Pattern d'inspiration : Hermes ``tools/skill_usage.py`` (provenance tracking)
voir docs/external-references/hermes-skills-self-improvement.md §1
Implémentation : code maison, adapté au modèle multi-signal ELY.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FailureCase(Base):
    """One replay-able failure pointer.

    A FailureCase joins one signal row (hitl_refusal / hallucination_block /
    mission_critique) with the *minimum* state needed to replay the
    conversation up to that point: messages, active toolset, tier_llm,
    frozen_memory snapshot.

    Lifecycle:
        created (processed_at=NULL)  ←  skill_creator scans nightly
              ↓
        processed_at set            ←  a SkillCandidate row references this case
              ↓
        terminal                    ←  either the skill passed eval (active)
                                       or N iterations exhausted (rejected)

    Provider switches are intentionally NOT captured here — they're an
    infra-level concern (fallback chain) rather than an agent procedural
    failure that a playbook could fix.
    """

    __tablename__ = "failure_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)

    # Which signal table this case points at + the row id within it.
    # Values: "hitl_refusals" | "hallucination_blocks" | "mission_critiques".
    signal_table: Mapped[str] = mapped_column(String(40), index=True)
    signal_id: Mapped[int] = mapped_column(Integer)

    # Conversation context (nullable for mission-level critiques that don't
    # bind to a single conversation).
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    mission_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Minimal replay payload — JSON. Shape (V1, see design note §5 Phase 1):
    #   {
    #     "messages": [{"role": "user", "content": "..."}, ...],   # last N turns
    #     "toolset": ["gmail_list_emails", ...],                    # active tools
    #     "tier_llm": "B",
    #     "model_used": "gemma-4-e4b",
    #     "frozen_memory_excerpt": "..."                            # truncated, no PII
    #   }
    # We cap each string field at ~2 KB to keep rows under ~10 KB and
    # avoid blowing up the SQLite WAL. Full replay requires the original
    # conversation row anyway — this is just enough to identify the
    # pattern + bootstrap an eval re-run.
    replay_payload: Mapped[str] = mapped_column(Text)

    # The outcome the skill is supposed to produce, when it can be inferred.
    # Left NULL at capture time; the skill_creator (tier S Opus) infers it
    # later when grouping failure cases into actionable patterns.
    expected_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)

    # sha256[:16] of a fingerprint built from {signal_table + tool_name +
    # truncated user_query}. Used to cluster similar failures so the
    # skill_creator picks 1 case per pattern rather than treating every
    # row as unique. Computed at capture time, indexed.
    pattern_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # When a skill candidate has been generated to address this case, the
    # timestamp + that candidate's id. NULL = still pending.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    learned_skill_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("learned_skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # The tier active when the failure happened, copied here so the cluster
    # logic can prioritise (e.g. tier-B failures probably need different
    # playbook than tier-C failures).
    tier_llm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # sha256[:8] of the system prompt active when the failure occurred —
    # so the skill_creator can spot prompts that produced many failures.
    prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
