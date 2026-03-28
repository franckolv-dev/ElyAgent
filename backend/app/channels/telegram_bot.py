"""Telegram channel adapter for ELY Agent.

Routes Telegram messages to the same LangGraph agent used by the Web UI.
Security invariant: same SecurityFilter, same HITL, same tool permissions.

Setup:
  1. Create a bot via @BotFather on Telegram
  2. Save the bot token in Admin → OAuth/Services → telegram_bot_token
  3. Link Telegram users via /link <username> <password> in DM with the bot
"""
from __future__ import annotations

import asyncio
import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.auth.passwords import verify_password
from app.database import async_session
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter
from app.services.hitl_manager import get_hitl_manager

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

# telegram_user_id → ely_user_id
_linked_users: dict[int, str] = {}

# telegram_user_id → conversation_id
_conversations: dict[int, str] = {}

# telegram_user_id → SecurityFilter
_filters: dict[int, SecurityFilter] = {}

# Shared agent graph
_agent_graph = None


def _get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


# ── Startup: load linked users from DB ────────────────────────────────────────

async def _load_linked_users() -> None:
    """Load telegram_id → user_id mappings from DB."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id.isnot(None))
        )
        for user in result.scalars().all():
            _linked_users[int(user.telegram_id)] = user.id
    logger.info("Loaded %d linked Telegram users", len(_linked_users))


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message."""
    tg_id = update.effective_user.id
    if tg_id in _linked_users:
        await update.message.reply_text(
            "Bonjour ! Je suis ELY, ton assistant personnel.\n"
            "Ton compte est lié. Envoie-moi un message et je m'en occupe."
        )
    else:
        await update.message.reply_text(
            "Bonjour ! Je suis ELY, ton assistant personnel.\n\n"
            "Pour commencer, lie ton compte ELY avec la commande :\n"
            "/link ton_nom_utilisateur ton_mot_de_passe\n\n"
            "Cette commande n'est acceptée qu'en message privé."
        )


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /link <username> <password> — link Telegram account to ELY user."""
    # Only allow in private chat
    if update.effective_chat.type != "private":
        await update.message.reply_text("Cette commande n'est disponible qu'en message privé.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage : /link <nom_utilisateur> <mot_de_passe>")
        return

    username, password = args[0], " ".join(args[1:])
    tg_id = update.effective_user.id

    # Delete the message containing credentials immediately
    try:
        await update.message.delete()
    except Exception as del_exc:
        logger.warning("Could not delete /link message (credentials may be visible): %s", del_exc)
        await update.effective_chat.send_message(
            "⚠️ Je n'ai pas pu supprimer ton message contenant tes identifiants. "
            "Supprime-le manuellement pour protéger ton mot de passe."
        )

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            await update.effective_chat.send_message("Identifiants incorrects.")
            return

        user.telegram_id = str(tg_id)
        await db.commit()
        _linked_users[tg_id] = user.id

    await update.effective_chat.send_message(
        f"Compte lié avec succès ! Bienvenue, {username}.\n"
        "Tu peux maintenant me parler directement ici."
    )
    logger.info("Telegram user %s linked to ELY user %s", tg_id, username)


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unlink — remove Telegram link."""
    tg_id = update.effective_user.id
    user_id = _linked_users.pop(tg_id, None)
    if user_id:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.telegram_id = None
                await db.commit()
        await update.message.reply_text("Compte délié. Utilise /link pour te reconnecter.")
    else:
        await update.message.reply_text("Aucun compte lié.")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new — start a new conversation."""
    tg_id = update.effective_user.id
    _conversations.pop(tg_id, None)
    _filters.pop(tg_id, None)
    await update.message.reply_text("Nouvelle conversation. Que puis-je faire pour toi ?")


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — route to agent."""
    if not update.message or not update.message.text:
        return

    tg_id = update.effective_user.id

    # Check if user is linked
    if tg_id not in _linked_users:
        await update.message.reply_text(
            "Tu dois d'abord lier ton compte ELY.\n"
            "Utilise : /link <nom_utilisateur> <mot_de_passe>"
        )
        return

    user_id = _linked_users[tg_id]
    user_content = update.message.text

    # Send typing indicator
    await update.effective_chat.send_action("typing")

    try:
        # Get or create conversation
        conversation_id = _conversations.get(tg_id)

        async with async_session() as db:
            # Refresh google credentials
            u_result = await db.execute(select(User).where(User.id == user_id))
            user = u_result.scalar_one_or_none()
            google_credentials = user.google_credentials if user else None

            if not conversation_id:
                conv = Conversation(user_id=user_id, title=f"[Telegram] {user_content[:40]}")
                db.add(conv)
                await db.flush()
                conversation_id = str(conv.id)
                _conversations[tg_id] = conversation_id
                await db.commit()

            # Save user message
            db.add(Message(conversation_id=conversation_id, role="user", content=user_content))
            await db.commit()

        # Load conversation history
        async with async_session() as db:
            hist_result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            history_rows = hist_result.scalars().all()

        from langchain_core.messages import HumanMessage, AIMessage

        sf = _filters.setdefault(tg_id, SecurityFilter())
        history_msgs = []
        for row in history_rows[:-1]:
            if row.role == "user":
                history_msgs.append(HumanMessage(content=sf.anonymize(row.content)))
            elif row.role == "assistant":
                history_msgs.append(AIMessage(content=row.content))
        history_msgs = history_msgs[-40:]
        history_msgs.append(HumanMessage(content=sf.anonymize(user_content)))

        # Invoke agent
        agent = _get_agent()
        invoke_result = await agent.ainvoke({
            "messages": history_msgs,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "google_credentials": google_credentials or "",
        })

        ai_content = invoke_result["messages"][-1].content
        ai_content = sf.deanonymize(ai_content)

        # Save assistant message
        async with async_session() as db:
            db.add(Message(conversation_id=conversation_id, role="assistant", content=ai_content))
            await db.commit()

        # Store interaction in vector memory
        memory = get_memory_manager()
        await memory.store_interaction(
            user_msg=user_content,
            assistant_msg=ai_content,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        # Send response (split if > 4096 chars — Telegram limit)
        for i in range(0, len(ai_content), 4096):
            await update.message.reply_text(ai_content[i:i + 4096])

    except Exception as exc:
        logger.exception("Error handling Telegram message from user %s", tg_id)
        await update.message.reply_text(
            "Désolé, une erreur s'est produite. Réessaie dans quelques instants."
        )


# ── HITL via Telegram inline keyboard ─────────────────────────────────────────

async def send_hitl_validation(
    tg_id: int,
    description: str,
    request_id: str,
    app: Application,
) -> None:
    """Send HITL validation request as inline keyboard buttons."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Autoriser", callback_data=f"hitl:allow:{request_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"hitl:deny:{request_id}"),
        ],
        [
            InlineKeyboardButton("🚫 Interdire définitivement", callback_data=f"hitl:ban:{request_id}"),
        ],
    ]
    await app.bot.send_message(
        chat_id=tg_id,
        text=f"⚠️ Action nécessitant validation :\n\n{description[:3000]}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_hitl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle HITL approval/deny/ban from inline keyboard."""
    query = update.callback_query
    if not query or not query.data.startswith("hitl:"):
        return

    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return

    decision = parts[1]  # allow / deny / ban
    request_id = parts[2]

    hitl = get_hitl_manager()
    await hitl.resolve(request_id, decision)

    labels = {"allow": "✅ Autorisé", "deny": "❌ Refusé", "ban": "🚫 Interdit définitivement"}
    await query.edit_message_text(
        text=f"{query.message.text}\n\n{labels.get(decision, decision)}"
    )


# ── Bot lifecycle ─────────────────────────────────────────────────────────────

_bot_app: Application | None = None


async def start_telegram_bot() -> None:
    """Start the Telegram bot in webhook mode (called from FastAPI lifespan).

    Webhook mode avoids the Conflict error that occurs when multiple instances
    (e.g. during a rolling deploy) try to long-poll the same token simultaneously.
    Telegram pushes updates to our HTTPS endpoint instead.
    """
    global _bot_app

    from app.services.system_config import get_config
    from app.config import get_settings

    s = get_settings()
    token = await get_config("telegram_bot_token", fallback=getattr(s, "telegram_bot_token", ""))

    if not token:
        logger.info("Telegram bot token not configured — skipping Telegram channel")
        return

    # Determine webhook URL from config/env
    backend_url = getattr(s, "backend_url", "") or ""
    webhook_url = f"{backend_url.rstrip('/')}/webhook/telegram"
    if not backend_url or not backend_url.startswith("https://"):
        # Fallback to polling if no HTTPS backend URL configured
        logger.warning(
            "BACKEND_URL not set or not HTTPS (%r) — falling back to polling mode", backend_url
        )
        await _start_polling(token)
        return

    await _load_linked_users()

    _bot_app = Application.builder().token(token).updater(None).build()

    # Register handlers
    _bot_app.add_handler(CommandHandler("start", cmd_start))
    _bot_app.add_handler(CommandHandler("link", cmd_link))
    _bot_app.add_handler(CommandHandler("unlink", cmd_unlink))
    _bot_app.add_handler(CommandHandler("new", cmd_new))
    _bot_app.add_handler(CallbackQueryHandler(handle_hitl_callback, pattern=r"^hitl:"))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await _bot_app.initialize()
    await _bot_app.start()

    # Register webhook with Telegram
    await _bot_app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )
    logger.info("Telegram bot started — webhook at %s", webhook_url)


async def _start_polling(token: str) -> None:
    """Fallback: start bot in polling mode (development / no HTTPS)."""
    global _bot_app

    await _load_linked_users()

    _bot_app = Application.builder().token(token).build()
    _bot_app.add_handler(CommandHandler("start", cmd_start))
    _bot_app.add_handler(CommandHandler("link", cmd_link))
    _bot_app.add_handler(CommandHandler("unlink", cmd_unlink))
    _bot_app.add_handler(CommandHandler("new", cmd_new))
    _bot_app.add_handler(CallbackQueryHandler(handle_hitl_callback, pattern=r"^hitl:"))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await _bot_app.initialize()
    await _bot_app.start()
    await _bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started — polling mode")


async def receive_telegram_update(data: dict) -> None:
    """Process an incoming webhook update from Telegram.

    Called by the /webhook/telegram FastAPI route.
    """
    if _bot_app is None:
        logger.warning("Received Telegram webhook but bot is not initialized")
        return
    update = Update.de_json(data, _bot_app.bot)
    await _bot_app.process_update(update)


async def stop_telegram_bot() -> None:
    """Stop the Telegram bot gracefully."""
    global _bot_app
    if _bot_app:
        try:
            # Delete webhook so Telegram stops sending updates
            await _bot_app.bot.delete_webhook(drop_pending_updates=False)
        except Exception as exc:
            logger.warning("Could not delete Telegram webhook: %s", exc)
        # Stop polling updater if in polling mode
        if _bot_app.updater and _bot_app.updater.running:
            await _bot_app.updater.stop()
        await _bot_app.stop()
        await _bot_app.shutdown()
        _bot_app = None
        logger.info("Telegram bot stopped")
