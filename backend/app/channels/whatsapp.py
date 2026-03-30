# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""WhatsApp channel adapter for ELY Agent via Meta Cloud API.

Setup:
  1. Create a Meta App at developers.facebook.com
  2. Add WhatsApp product, get a test phone number
  3. Set WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_WEBHOOK_VERIFY_TOKEN
  4. Configure webhook URL: https://your-domain/api/webhook/whatsapp
     (needs HTTPS — use ngrok for local dev: ngrok http 8000)

Security:
  - X-Hub-Signature-256 validation on every webhook
  - User must explicitly link their WA number via the admin UI
  - Same SecurityFilter + HITL as Web UI and Telegram
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.user import User

logger = logging.getLogger(__name__)

# WhatsApp phone number (string) → ELY user_id mapping (loaded at startup)
_linked_users: dict[str, str] = {}

# WhatsApp phone number → conversation_id
_conversations: dict[str, str] = {}


# ── Startup ───────────────────────────────────────────────────────────────────

async def load_linked_whatsapp_users() -> None:
    """Load whatsapp_phone → user_id mappings from DB at startup."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.whatsapp_phone.isnot(None))
        )
        for user in result.scalars().all():
            _linked_users[user.whatsapp_phone] = user.id
    logger.info("Loaded %d linked WhatsApp users", len(_linked_users))


# ── Signature verification ─────────────────────────────────────────────────────

def verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 header."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Send message ──────────────────────────────────────────────────────────────

async def send_whatsapp_message(phone_number: str, text: str) -> bool:
    """Send a text message to a WhatsApp user via Meta Cloud API."""
    from app.config import get_settings
    s = get_settings()

    if not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        logger.warning("WhatsApp not configured — cannot send message")
        return False

    url = f"https://graph.facebook.com/v21.0/{s.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {s.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Failed to send WhatsApp message to %s: %s", phone_number, exc)
        return False


# ── Message processing ────────────────────────────────────────────────────────

async def process_whatsapp_message(from_phone: str, message_text: str) -> None:
    """Process an incoming WhatsApp text message through the ELY agent."""
    from app.agent.graph import build_agent_graph
    from app.models.conversation import Conversation, Message
    from app.services.memory_manager import get_memory_manager
    from app.services.security_filter import SecurityFilter
    from langchain_core.messages import HumanMessage, AIMessage

    # Check if user is linked
    if from_phone not in _linked_users:
        await send_whatsapp_message(
            from_phone,
            "Bonjour ! Je suis ELY, ton assistant personnel.\n\n"
            "Pour utiliser ELY via WhatsApp, demande à l'administrateur "
            "de lier ton numéro à ton compte via l'interface d'administration."
        )
        return

    user_id = _linked_users[from_phone]

    try:
        # Get or create conversation
        conversation_id = _conversations.get(from_phone)

        async with async_session() as db:
            u_result = await db.execute(select(User).where(User.id == user_id))
            user = u_result.scalar_one_or_none()
            google_credentials = user.google_credentials if user else None

            if not conversation_id:
                conv = Conversation(
                    user_id=user_id,
                    title=f"[WhatsApp] {message_text[:40]}"
                )
                db.add(conv)
                await db.flush()
                conversation_id = str(conv.id)
                _conversations[from_phone] = conversation_id
                await db.commit()

            db.add(Message(
                conversation_id=conversation_id,
                role="user",
                content=message_text,
            ))
            await db.commit()

        # Load history
        async with async_session() as db:
            from sqlalchemy import select as sa_select
            hist_result = await db.execute(
                sa_select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            history_rows = hist_result.scalars().all()

        sf = SecurityFilter()
        history_msgs = []
        for row in history_rows[:-1]:
            if row.role == "user":
                history_msgs.append(HumanMessage(content=sf.anonymize(row.content)))
            elif row.role == "assistant":
                history_msgs.append(AIMessage(content=row.content))
        history_msgs = history_msgs[-40:]
        history_msgs.append(HumanMessage(content=sf.anonymize(message_text)))

        # Invoke agent
        agent = build_agent_graph()
        invoke_result = await agent.ainvoke({
            "messages": history_msgs,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "google_credentials": google_credentials or "",
        })

        ai_content = invoke_result["messages"][-1].content
        ai_content = sf.deanonymize(ai_content)

        # Save response
        async with async_session() as db:
            db.add(Message(
                conversation_id=conversation_id,
                role="assistant",
                content=ai_content,
            ))
            await db.commit()

        # Store in memory
        await get_memory_manager().store_interaction(
            user_msg=message_text,
            assistant_msg=ai_content,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        # Split long messages (WhatsApp limit 4096)
        for i in range(0, len(ai_content), 4096):
            await send_whatsapp_message(from_phone, ai_content[i:i+4096])

    except Exception as exc:
        logger.exception("Error processing WhatsApp message from %s", from_phone)
        await send_whatsapp_message(
            from_phone,
            "Désolé, une erreur s'est produite. Réessaie dans quelques instants."
        )
