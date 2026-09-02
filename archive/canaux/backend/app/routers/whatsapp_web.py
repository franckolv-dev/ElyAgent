# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/whatsapp_web.py
# @brief      WhatsApp Web bridge API (QR pairing, session control)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Admin/UI endpoints for the WhatsApp Web channel.

Each ELY user can link their own personal WhatsApp account by scanning a QR
code. The session is persisted (SQLite per user) so a single scan lasts until
the user explicitly logs out or WhatsApp invalidates the device.

Endpoints :
  POST   /api/whatsapp-web/session/start   → start or resume → returns status (+ QR if needed)
  GET    /api/whatsapp-web/session/status  → current status
  POST   /api/whatsapp-web/session/logout  → wipe session + disconnect

All routes are user-scoped via the JWT token (each user only touches their
own session, no cross-user admin override to keep things simple).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/whatsapp-web", tags=["whatsapp-web"])
logger = logging.getLogger(__name__)


@router.post("/session/start")
async def start_session(current_user: User = Depends(get_current_user)) -> dict:
    """Start or resume the authenticated user's WhatsApp Web session.

    If the user has never paired, a QR code is generated and returned as
    base64 PNG — the frontend should poll `/session/status` until the
    status flips from `pending_qr` to `linked`.

    If a SQLite session already exists (previous pairing), neonize will
    auto-reconnect without needing a new QR scan — status goes straight to
    `linked`.
    """
    from app.channels.whatsapp_web import start_session as _start
    return await _start(current_user.id)


@router.get("/session/status")
async def session_status(current_user: User = Depends(get_current_user)) -> dict:
    """Current state of the user's WhatsApp Web session.

    Response fields :
      - `status`     : "not_started" | "connecting" | "pending_qr" | "linked"
                       | "disconnected" | "error"
      - `qr_png_b64` : base64-encoded PNG of the QR to scan (only when
                       status == "pending_qr")
      - `phone`      : linked phone in E.164 once paired (null otherwise)
      - `last_error` : error message if status == "error"
    """
    from app.channels.whatsapp_web import get_status
    return get_status(current_user.id)


@router.post("/session/logout")
async def logout_session(current_user: User = Depends(get_current_user)) -> dict:
    """Terminate the user's WhatsApp Web session + delete its local keys.

    Next `/session/start` will require a fresh QR scan.
    """
    from app.channels.whatsapp_web import logout as _logout
    ok = await _logout(current_user.id)
    return {"logged_out": ok}


class PhonePairRequest(BaseModel):
    phone_number: str  # E.164 format (with or without "+")


@router.post("/session/pair-phone")
async def pair_with_phone(
    body: PhonePairRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Alternative pairing method — returns an 8-char code to enter in
    *WhatsApp → Appareils connectés → "Lier avec un numéro de téléphone"*.

    Use this when the QR scan flow keeps failing with
    "Impossible de connecter l'appareil".
    """
    from app.channels.whatsapp_web import request_pair_code
    return await request_pair_code(current_user.id, body.phone_number)
