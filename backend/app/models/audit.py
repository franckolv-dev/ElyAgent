# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/audit.py
# @brief      Audit log endpoints
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)  # "ssh_command" | "file_access" | "login" | "config_change" | "tool_call" | "hitl_decision"
    target_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Champs ajoutés — Phase 2.3 : traçabilité étendue
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)   # "web" | "telegram" | "api"
    tool_used: Mapped[str | None] = mapped_column(String(100), nullable=True)             # nom de l'outil agent invoqué
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)             # IPv4 ou IPv6
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True,
    )
