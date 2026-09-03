# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/whatsapp_webhook.py
# @brief      WhatsApp Cloud API webhook router
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""WhatsApp Cloud API webhook router.

GET  /api/webhook/whatsapp  — webhook verification (Meta sends this once)
POST /api/webhook/whatsapp  — incoming messages
POST /api/whatsapp/link     — admin: link a WA phone to a user account
DELETE /api/whatsapp/link/{user_id} — admin: remove WA link
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.database import async_session
from app.services.background_tasks import spawn
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """Handle Meta's webhook verification challenge."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    s = get_settings()
    if mode == "subscribe" and token == s.whatsapp_webhook_verify_token:
        logger.info("WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(403, "Forbidden — invalid verify token")


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receive and process incoming WhatsApp messages."""
    from app.channels.whatsapp import process_whatsapp_message, verify_signature

    body = await request.body()

    # Verify Meta signature.
    # If whatsapp_phone_number_id is set (channel is active), app_secret MUST also
    # be set — otherwise ANY request would be accepted, allowing spoofed messages.
    s = get_settings()
    if s.whatsapp_phone_number_id and not s.whatsapp_app_secret:
        raise HTTPException(503, "WhatsApp webhook misconfigured: WHATSAPP_APP_SECRET is required")
    if s.whatsapp_app_secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, sig, s.whatsapp_app_secret):
            raise HTTPException(403, "Invalid signature")

    data = json.loads(body)

    # Extract messages from the webhook payload
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                if msg.get("type") == "text":
                    from_phone = msg["from"]
                    text = msg["text"]["body"]
                    # Process asynchronously to return 200 quickly.
                    # ⚠️ (audit 02/09) `create_task` nu : Meta reçoit son 200,
                    # puis la tâche peut être ramassée par le GC avant d'avoir
                    # répondu — message perdu, sans trace. `spawn` la retient
                    # et journalise son exception.
                    spawn(
                        process_whatsapp_message(from_phone, text),
                        label="whatsapp.incoming_message",
                    )

    # Meta expects a 200 response quickly
    return {"status": "ok"}


class WhatsAppLinkRequest(BaseModel):
    user_id: str
    phone_number: str  # in E.164 format: +33612345678


@router.post("/whatsapp/link")
async def link_whatsapp(
    data: WhatsAppLinkRequest,
    current_user=Depends(get_current_user),
):
    """Admin: link a WhatsApp phone number to an ELY user account."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")

    from app.channels.whatsapp import _linked_users

    # Normalize phone (remove + if present for dict key, but store E.164)
    phone = data.phone_number.lstrip("+")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == data.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        user.whatsapp_phone = phone
        await db.commit()

    _linked_users[phone] = data.user_id
    return {"linked": True, "phone": phone, "user_id": data.user_id}


@router.delete("/whatsapp/link/{user_id}")
async def unlink_whatsapp(
    user_id: str,
    current_user=Depends(get_current_user),
):
    """Admin: remove a WhatsApp link."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")

    from app.channels.whatsapp import _linked_users

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        phone = user.whatsapp_phone
        user.whatsapp_phone = None
        await db.commit()

    if phone:
        _linked_users.pop(phone, None)

    return {"unlinked": True}
