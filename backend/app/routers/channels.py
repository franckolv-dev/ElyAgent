# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/channels.py
# @brief      Unified admin API for configuring chat channels from the UI
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Unified admin API for configuring chat channels (Telegram, Discord, Slack,
WhatsApp Meta Cloud) directly from the Settings UI.

Each channel has three endpoints:
  - GET    /api/channels/<ch>/status      → report what's saved + bot alive
  - POST   /api/channels/<ch>/save        → validate + persist + hot-restart
  - POST   /api/channels/<ch>/disable     → clear creds + stop bot

"Hot-restart" means we stop the currently-running bot task and start a new
one with the freshly-saved creds — no container restart needed.

WhatsApp Web (neonize) has its own /api/whatsapp-web/* endpoints because its
lifecycle is different (per-user QR pairing). This router is for the four
"bot-token" channels where the UI just needs to accept a token / credentials.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.system_config import get_config, set_config

router = APIRouter(prefix="/api/channels", tags=["channels"])
logger = logging.getLogger(__name__)


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
    """Probe a channel module for a `_bot_app` / `_discord_client` global
    to tell if its bot task is currently alive. Returns False on any error.
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
    token = await get_config("telegram_bot_token", fallback="")
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
# Discord
# =============================================================================

class DiscordSaveBody(BaseModel):
    token: str


@router.get("/discord/status")
async def discord_status(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    token = await get_config("discord_bot_token", fallback="")
    return {
        "configured": bool(token),
        "running": await _is_running("_discord_client", "app.channels.discord_bot"),
    }


@router.post("/discord/save")
async def discord_save(
    body: DiscordSaveBody,
    current_user: User = Depends(get_current_user),
) -> dict:
    _admin_only(current_user)
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token vide.")

    # Validate via Discord API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Token invalide — vérifie le token Discord Developer Portal")
        bot = r.json()
        bot_username = bot.get("username")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Discord API")

    await set_config("discord_bot_token", token, is_secret=True, description="Discord bot token")

    try:
        from app.channels.discord_bot import start_discord_bot, stop_discord_bot
        await stop_discord_bot()
        await start_discord_bot()
    except Exception as exc:
        logger.warning("Discord hot-restart failed: %s", exc)

    logger.info("Channels: Discord token saved by user=%s (%s)", current_user.id, bot_username)
    return {"saved": True, "bot_username": bot_username}


@router.post("/discord/disable")
async def discord_disable(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    await set_config("discord_bot_token", "", is_secret=True, description="Discord bot token")
    try:
        from app.channels.discord_bot import stop_discord_bot
        await stop_discord_bot()
    except Exception as exc:
        logger.debug("stop_discord_bot: %s", exc)
    return {"disabled": True}


# =============================================================================
# Slack
# =============================================================================

class SlackSaveBody(BaseModel):
    bot_token: str
    app_token: str  # xapp-... for Socket Mode


@router.get("/slack/status")
async def slack_status(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    bot_token = await get_config("slack_bot_token", fallback="")
    app_token = await get_config("slack_app_token", fallback="")
    return {
        "configured": bool(bot_token and app_token),
        "has_bot_token": bool(bot_token),
        "has_app_token": bool(app_token),
    }


@router.post("/slack/save")
async def slack_save(
    body: SlackSaveBody,
    current_user: User = Depends(get_current_user),
) -> dict:
    _admin_only(current_user)
    bot_token = body.bot_token.strip()
    app_token = body.app_token.strip()
    if not bot_token or not app_token:
        raise HTTPException(status_code=400, detail="Les deux tokens (bot + app) sont requis.")

    # Validate bot token via auth.test
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
        data = r.json() if r.status_code == 200 else {}
        if not data.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=f"Bot token invalide: {data.get('error', 'unknown')}",
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout Slack API")

    await set_config("slack_bot_token", bot_token, is_secret=True, description="Slack bot token")
    await set_config("slack_app_token", app_token, is_secret=True, description="Slack app token")

    try:
        from app.channels.slack_bot import start_slack_bot, stop_slack_bot
        await stop_slack_bot()
        await start_slack_bot()
    except Exception as exc:
        logger.warning("Slack hot-restart failed: %s", exc)

    logger.info("Channels: Slack tokens saved by user=%s", current_user.id)
    return {"saved": True}


@router.post("/slack/disable")
async def slack_disable(current_user: User = Depends(get_current_user)) -> dict:
    _admin_only(current_user)
    await set_config("slack_bot_token", "", is_secret=True, description="Slack bot token")
    await set_config("slack_app_token", "", is_secret=True, description="Slack app token")
    try:
        from app.channels.slack_bot import stop_slack_bot
        await stop_slack_bot()
    except Exception as exc:
        logger.debug("stop_slack_bot: %s", exc)
    return {"disabled": True}
