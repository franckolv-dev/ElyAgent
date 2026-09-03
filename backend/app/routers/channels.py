# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/channels.py
# @brief      Unified admin API for configuring chat channels from the UI
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Admin API for configuring the Telegram channel from the Settings UI.

Trois routes :
  - GET    /api/channels/telegram/status   → report what's saved + bot alive
  - POST   /api/channels/telegram/save     → validate + persist + hot-restart
  - POST   /api/channels/telegram/disable  → clear creds + stop bot

"Hot-restart" means we stop the currently-running bot task and start a new
one with the freshly-saved creds — no container restart needed.

⚠️ AUDIT 02/09/2026 : ce routeur pilotait quatre canaux. Slack, Discord et
WhatsApp (Meta Cloud + pont neonize) sont partis sous ``archive/canaux`` —
zéro appel de modèle en cinq mois de production, contre 3 pour Telegram, le
seul qui ait jamais servi. Leurs formulaires de réglages ne faisaient
qu'offrir un endroit où coller un jeton sans effet.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.system_config import get_config, set_config

router = APIRouter(prefix="/api/channels", tags=["channels"])
logger = logging.getLogger(__name__)


async def _resolve_channel_token(db_key: str, env_key: str) -> str:
    """Return token from DB first, fallback to env var.

    Telegram a été configuré via .env avant que l'UI de réglages existe : la
    ligne en base n'apparaît qu'au premier enregistrement depuis l'UI. Sans ce
    repli, l'UI afficherait « non configuré » alors que le bot tourne bel et
    bien sur les identifiants de l'environnement.
    """
    val = await get_config(db_key, fallback="")
    if val:
        return val
    return os.environ.get(env_key, "") or ""


# =============================================================================
# Helpers
# =============================================================================

def _admin_only(u: User) -> None:
    """Channel config is an admin-level operation (affects all users)."""
    if getattr(u, "role", "user") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul un administrateur peut configurer les channels.",
        )


async def _is_running(check_fn_name: str, module: str) -> bool:
    """Probe a channel module for a `_bot_app` global to tell if its bot task
    is currently alive. Returns False on any error.
    """
    try:
        import importlib
        mod = importlib.import_module(module)
        val = getattr(mod, check_fn_name, None)
        return val is not None
    except Exception:
        return False


# =============================================================================
# Telegram
# =============================================================================

class TelegramSaveBody(BaseModel):
    token: str


@router.get("/telegram/status")
async def telegram_status(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    token = await _resolve_channel_token("telegram_bot_token", "TELEGRAM_BOT_TOKEN")
    bot_username: Optional[str] = None
    if token:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                if r.status_code == 200:
                    bot_username = r.json().get("result", {}).get("username")
        except Exception:
            pass
    return {
        "configured": bool(token),
        "bot_username": bot_username,
        "running": await _is_running("_bot_app", "app.channels.telegram_bot"),
    }


@router.post("/telegram/save")
async def telegram_save(
    body: TelegramSaveBody,
    current_user: User = Depends(get_current_user),
) -> dict:
    _admin_only(current_user)
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token vide.")

    # Validate via Telegram API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Token invalide — vérifie le token BotFather")
        bot = r.json().get("result", {})
        bot_username = bot.get("username")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Telegram API")

    await set_config("telegram_bot_token", token, is_secret=True, description="Telegram bot token")

    # Hot-restart
    try:
        from app.channels.telegram_bot import start_telegram_bot, stop_telegram_bot
        await stop_telegram_bot()
        await start_telegram_bot()
    except Exception as exc:
        logger.warning("Telegram hot-restart failed: %s", exc)

    logger.info("Channels: Telegram token saved by user=%s (@%s)", current_user.id, bot_username)
    return {"saved": True, "bot_username": bot_username}


@router.post("/telegram/disable")
async def telegram_disable(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    await set_config("telegram_bot_token", "", is_secret=True, description="Telegram bot token")
    try:
        from app.channels.telegram_bot import stop_telegram_bot
        await stop_telegram_bot()
    except Exception as exc:
        logger.debug("stop_telegram_bot: %s", exc)
    return {"disabled": True}


# =============================================================================
# ELY Android (FCM) — per-user, not admin-level
# =============================================================================
# Unlike Telegram which is configured globally by an admin
# (one bot serves all users), the ELY Android channel is per-user : each
# user's app registers its own FCM token via PUT /api/device-token. This
# endpoint reports whether THE CALLING USER has linked their app.

@router.get("/ely-android/status")
async def ely_android_status(current_user: User = Depends(get_current_user)) -> dict:
    """Report whether the calling user has linked their ELY Android app.

    Linked = there's an FCM token registered for this user.
    Used by Settings UI to show 'configured/not configured' badge.
    """
    has_token = bool(getattr(current_user, "fcm_token", None))
    # Firebase needs to be configured server-side too (firebase_credentials_path).
    from app.config import get_settings
    fb_configured = bool(get_settings().firebase_credentials_path)
    return {
        "configured": has_token and fb_configured,
        "user_token_registered": has_token,
        "firebase_configured": fb_configured,
    }


@router.post("/ely-android/unlink")
async def ely_android_unlink(current_user: User = Depends(get_current_user)) -> dict:
    """Clear the FCM token for the calling user (un-pair the Android app)."""
    from app.database import async_session
    async with async_session() as db:
        u = await db.get(User, current_user.id)
        if u:
            u.fcm_token = None
            await db.commit()
    return {"unlinked": True}


# =============================================================================
# Aggregated active-channels — accessible to ALL users (not admin-only)
# =============================================================================
# Used by the chat AvatarPanel "CANAUX ACTIFS" widget. Returns booleans only,
# never tokens. Combines :
#   - Bot-level status (telegram configured globally)
#   - Per-user link state for ely_android (User.fcm_token present + Firebase
#     credentials configured server-side)

@router.get("/active")
async def active_channels(current_user: User = Depends(get_current_user)) -> dict:
    """Aggregated boolean view of which channels are alive on this backend.

    Distinguishes :
      - `configured` : credentials present (env or DB) → bot can run
      - `running`    : bot module is currently alive in memory
      - `linked`     : THE CALLING USER has linked their account (per-user)
    """
    # Bot-level (global)
    tel_token = await _resolve_channel_token("telegram_bot_token", "TELEGRAM_BOT_TOKEN")

    # Firebase / FCM (Android push)
    from app.config import get_settings
    fb_configured = bool(get_settings().firebase_credentials_path)
    user_has_fcm = bool(getattr(current_user, "fcm_token", None))

    return {
        "telegram": {
            "configured": bool(tel_token),
            "running": await _is_running("_bot_app", "app.channels.telegram_bot"),
            "linked": bool(getattr(current_user, "telegram_id", None)),
        },
        "ely_android": {
            "configured": fb_configured,
            "running": fb_configured,  # FCM is server-driven, no session
            "linked": user_has_fcm,
        },
        "ntfy": {
            "configured": bool(get_settings().ntfy_url),
            "running": bool(get_settings().ntfy_url),
            "linked": bool(get_settings().ntfy_url),
        },
    }
