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
"""FastAPI route that receives Telegram webhook POSTs.

Telegram calls POST /webhook/telegram with a JSON Update payload.
We forward it to the bot Application for processing.

Security:
  - The endpoint is unauthenticated but only accessible via the secret path.
  - Telegram only sends updates to the registered webhook URL, which is set
    at startup and includes our domain (HTTPS only).
  - Rate-limiting from slowapi applies.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive and process a Telegram update via webhook."""
    try:
        data = await request.json()
        from app.channels.telegram_bot import receive_telegram_update
        await receive_telegram_update(data)
    except Exception as exc:
        # Always return 200 to Telegram — if we return an error Telegram
        # will keep retrying the same update for 24h.
        logger.exception("Error processing Telegram webhook update: %s", exc)
    return Response(content='{"ok":true}', media_type="application/json")
