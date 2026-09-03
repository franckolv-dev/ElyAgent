# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/telegram_tool.py
# @brief      Telegram outbound tools — send messages to the calling user.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Telegram outbound tools.

The Telegram bot in ``app/channels/telegram_bot.py`` already handles inbound
messages (user → ELY) and HITL prompts (ELY → user for validation). This
module adds OUTBOUND tools (ELY → user, agent-initiated) so missions and
scheduled tasks can push briefings, alerts, or task results to the calling
user's linked Telegram account.

Security model :
  - ONE recipient only : the user who invoked the tool (`user_id` is
    InjectedToolArg, so the LLM cannot target an arbitrary chat).
  - User must have linked their Telegram account first via /link in the bot.
  - Sending a message to oneself carries near-zero risk (no data leak), so
    HITL is NOT forced for these tools — they're meant to be transparent
    delivery channels for missions running unattended.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

logger = logging.getLogger(__name__)


async def _resolve_telegram_chat_id(user_id: str) -> int | None:
    """Resolve the Telegram chat ID for an ELY user_id.

    Returns None if the user hasn't linked their Telegram account yet.
    """
    if not user_id:
        return None
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        u = await db.get(User, user_id)
        if u and u.telegram_id:
            try:
                return int(u.telegram_id)
            except (TypeError, ValueError):
                return None
    return None


@tool
async def telegram_send_message(
    text: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Send a Telegram message to the calling user's own linked account.

    PERFECT for : daily briefings, scheduled-task notifications, mission
    summaries, alerts. The recipient is ALWAYS the user themselves — there
    is no `to` parameter (security : the LLM cannot send to arbitrary chats).

    Requires the user to have linked their Telegram account via the /link
    command in the @ELY bot. If not linked, returns an error string the
    LLM can act on (e.g. ask the user to link).

    Args:
        text: Message text to send (Markdown supported, max 4096 chars per
            message — longer texts are truncated with "…").
    """
    chat_id = await _resolve_telegram_chat_id(user_id)
    if chat_id is None:
        return (
            "Telegram non lié. L'utilisateur doit d'abord lier son compte "
            "en envoyant /link <username> <password> au bot Telegram d'ELY."
        )

    # The bot Application is initialized in app/channels/telegram_bot.py
    # at FastAPI startup (lifespan). We import lazily to avoid a circular
    # import at module load.
    try:
        from app.channels import telegram_bot
        app = getattr(telegram_bot, "_bot_app", None)
    except Exception as exc:
        logger.warning("telegram_send_message: failed to import bot app: %s", exc)
        return f"Bot Telegram indisponible : {exc}"

    if app is None or app.bot is None:
        return (
            "Bot Telegram non démarré côté backend. Vérifier "
            "TELEGRAM_BOT_TOKEN et le démarrage du service."
        )

    truncated = text[:4093] + "…" if len(text) > 4096 else text
    try:
        await app.bot.send_message(chat_id=chat_id, text=truncated)
        return f"✅ Message envoyé sur Telegram ({len(truncated)} caractères)."
    except Exception as exc:
        logger.warning("telegram_send_message failed for user %s: %s",
                       (user_id or "?")[:8], exc)
        return f"Erreur envoi Telegram : {exc}"
