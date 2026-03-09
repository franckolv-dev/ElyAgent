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
    created_at: datetime

    model_config = {"from_attributes": True}


class UserAdminResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
