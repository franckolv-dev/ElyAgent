# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/io_tool_dispatch.py
# @brief      Sprint 4b V3 J6.c.1 — per-call audit log for io python_tool
#             dispatches.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""One row per sandboxed io tool invocation — the operational footprint of
the V3 path (Sprint 4b V3 J6.c §audit).

Why a dedicated table rather than reusing `error_log` / `usage_log` /
`failure_case`:
  - The signals are different. Usage_log already tracks LLM-tier consumption
    per skill but doesn't know about sandbox outcomes; error_log is for
    backend exceptions, not for tool-call results; failure_case is the
    derived signal we synthesise FROM dispatches once we have enough.
  - Volume profile is different. Pure / playbook dispatches happen orders
    of magnitude more often than io dispatches will (io tools are by
    construction expensive — network calls + sandbox spin-up + Vault
    reads). A dedicated table lets the retention policy stay aggressive
    (90 days rolling, matching provider_switches) without affecting the
    much hotter tables.
  - One thing one place: when a reviewer wants to audit "what did this
    user's io tool X actually do this month", they can read ONE table by
    skill_id rather than join-grep across signals.

Privacy & safety boundary — what this table CAN store:
  - The list of secret LABELS the tool requested (never the values).
  - The list of network domains the tool was allowed to reach (declared,
    not the actual URLs it called — those live only in the sandbox's
    stdout if the tool prints them).
  - Outcome (returned / raised / timeout / etc.), duration, truncated
    error message (500 chars cap).
This table is NEVER read by the LLM and never injected into a prompt —
it's an admin/operator surface. The `error_truncated` field gets the
SecurityFilter scrub through the existing PII pipeline before write.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IoToolDispatch(Base):
    """One row per `run_in_sandbox` call from the io runtime — Sprint 4b V3 J6.c.1."""

    __tablename__ = "io_tool_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    # FK is best-effort: a skill could be archived between dispatch and
    # the audit row's insert. Soft FK (no ON DELETE CASCADE) keeps the
    # audit row alive even if the skill is later wiped.
    skill_id: Mapped[str] = mapped_column(String, index=True)
    # Snapshot of the tool's name at dispatch time — robust to a rename.
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    # Optional. The conversation is the natural context for replay, but
    # not every io tool call comes from a conversation (cron tasks, the
    # mission scheduler, etc. — V3.x).
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # SandboxResult.outcome — returned | raised | nonserializable |
    # timeout | crashed | error | unavailable. Indexed because the most
    # common query is "show me all failed dispatches today".
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    # SandboxResult.duration_s converted to ms — bigger granularity is
    # noise, smaller is overkill for a network-bound tool.
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # JSON list of secret LABELS used (e.g. `["openweather_api_key"]`).
    # NEVER values. Empty list `"[]"` for tools that declared none.
    secrets_used_json: Mapped[str] = mapped_column(Text, default="[]")
    # JSON list of declared `network_allow` domains, snapshotted at
    # dispatch (so a later edit of the skill doesn't lose the trace).
    network_allow_json: Mapped[str] = mapped_column(Text, default="[]")
    # Truncated error message when outcome != returned. PII-scrubbed
    # upstream of the write (`audit.record_dispatch`).
    error_truncated: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
