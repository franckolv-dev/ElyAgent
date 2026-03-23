from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api", tags=["device"])

class DeviceTokenRequest(BaseModel):
    token: str

@router.put("/device-token")
async def register_device_token(
    body: DeviceTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Register Android FCM push notification token."""
    current_user.fcm_token = body.token
    db.add(current_user)
    await db.commit()
    return {"status": "ok"}
