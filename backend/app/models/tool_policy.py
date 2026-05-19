# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/tool_policy.py
# @brief      Tool policy — declarative allow / deny / require_hitl per tool per user
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Tool policy — per-user declarative rules for tool execution.

Each row defines, for a given (user_id, tool_name) pair, whether the tool
should be:
- "allow"        : execute without HITL even if normally critical
- "deny"         : refuse outright, never ask the user
- "require_hitl" : force HITL prompt even if the tool is not in the
                   ALWAYS_CRITICAL_TOOLS set
- (no row)       : fall back to legacy behavior
                   (ALWAYS_CRITICAL_TOOLS + SecurityFilter.is_critical)

The policy is consulted by tool_node (backend/app/agent/nodes.py) before
the legacy HITL check, so it always takes precedence when present.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolPolicy(Base):
    __tablename__ = "tool_policies"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_name", name="uq_tool_policy_user_tool"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, index=True)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # "allow" | "deny" | "require_hitl"
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "ui" : edited via REST API
    # "yaml" : imported from a YAML file (admin maintenance)
    # "default" : seeded from default policy
    source: Mapped[str] = mapped_column(String(20), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
