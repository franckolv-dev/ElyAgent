# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/whatsapp_tool.py
# @brief      WhatsApp tools — send messages via Meta WhatsApp Cloud API
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""WhatsApp tools — send messages via Meta WhatsApp Cloud API.

Requires WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN to be configured.
The phone number must be in international format: +33612345678
"""
from __future__ import annotations

import logging
import re

import httpx
from langchain_core.tools import tool

from app.config import get_settings

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format (remove spaces, dashes; ensure leading +)."""
    cleaned = re.sub(r"[\s\-\.\(\)]", "", phone.strip())
    if cleaned.startswith("0") and len(cleaned) == 10:
        # French number without country code → +33
        cleaned = "+33" + cleaned[1:]
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


@tool
async def whatsapp_send(
    phone_number: str,
    message: str,
) -> str:
    """Send a WhatsApp text message to a phone number.

    Requires WhatsApp Cloud API to be configured (WHATSAPP_PHONE_NUMBER_ID +
    WHATSAPP_ACCESS_TOKEN in settings).

    Args:
        phone_number: Recipient phone in international format (e.g. '+33612345678' or '0612345678')
        message: Message text to send (max 4096 characters)
    """
    s = get_settings()
    if not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        return (
            "WhatsApp non configuré. Renseigne WHATSAPP_PHONE_NUMBER_ID et "
            "WHATSAPP_ACCESS_TOKEN dans les paramètres."
        )

    phone = _normalize_phone(phone_number)
    if not re.match(r"^\+\d{7,15}$", phone):
        return f"Numéro de téléphone invalide : {phone_number!r}. Utilise le format international (+33...)."

    url = f"https://graph.facebook.com/v21.0/{s.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {s.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": True, "body": message[:4096]},
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

        if resp.status_code == 200 and data.get("messages"):
            msg_id = data["messages"][0].get("id", "?")
            return f"Message WhatsApp envoyé à {phone} ✅ (ID: {msg_id})"
        else:
            err = data.get("error", {})
            return (
                f"Erreur WhatsApp lors de l'envoi à {phone} : "
                f"{err.get('message', str(data))}"
            )
    except Exception as exc:
        return f"Erreur lors de l'envoi WhatsApp : {exc}"


@tool
async def whatsapp_send_template(
    phone_number: str,
    template_name: str,
    language_code: str = "fr",
) -> str:
    """Send a pre-approved WhatsApp template message (e.g. for notifications).

    Template messages are required for outbound conversations not initiated by the user.
    You must have the template approved in Meta Business Manager first.

    Args:
        phone_number: Recipient phone in international format
        template_name: Approved template name (e.g. 'hello_world', 'ely_notification')
        language_code: Template language code (default 'fr', or 'en_US')
    """
    s = get_settings()
    if not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        return "WhatsApp non configuré."

    phone = _normalize_phone(phone_number)

    url = f"https://graph.facebook.com/v21.0/{s.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {s.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

        if resp.status_code == 200 and data.get("messages"):
            return f"Template « {template_name} » envoyé à {phone} ✅"
        else:
            err = data.get("error", {})
            return f"Erreur template WhatsApp : {err.get('message', str(data))}"
    except Exception as exc:
        return f"Erreur lors de l'envoi du template WhatsApp : {exc}"
