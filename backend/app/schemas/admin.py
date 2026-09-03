# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/schemas/admin.py
# @brief      Admin management endpoints
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
from pydantic import BaseModel
from datetime import datetime


class AuditLogResponse(BaseModel):
    id: str
    user_id: str
    action: str
    target_host: str | None
    command: str | None
    result_code: int | None
    details: str | None
    channel: str | None = None
    tool_used: str | None = None
    ip_address: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogDetailResponse(AuditLogResponse):
    """Réponse enrichie avec le username (via jointure User)."""
    username: str | None = None


class UserAdminResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
