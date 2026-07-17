# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/channels/telegram_bot.py
# @brief      Telegram channel adapter for ELY Agent
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
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
from collections import OrderedDict

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
from app.services.conversation_filters import discard_filter, get_filter
from app.services.hitl_manager import get_hitl_manager

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

# telegram_user_id → ely_user_id
_linked_users: dict[int, str] = {}

# telegram_user_id → conversation_id
_conversations: dict[int, str] = {}

# PII (C0, audit 16/07 P0) : plus de dict de filtres LOCAL par id Telegram —
# le SecurityFilter vit dans le registre PARTAGÉ conversation_filters, indexé
# par conversation_id, le même que tool_node et les sous-agents. Sinon leurs
# lookups par conversation_id tombent sur un filtre vide et les placeholders
# deviennent irrésolubles (args) ou les résultats repartent en clair.

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

        if not user or not await verify_password(password, user.hashed_password):
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
    _old_conv = _conversations.pop(tg_id, None)
    if _old_conv:
        discard_filter(_old_conv)
    await update.message.reply_text("Nouvelle conversation. Que puis-je faire pour toi ?")


async def cmd_mission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mission <titre> :: <goal>

    Creates a new mission, starts it, and reports the ID. The heartbeat
    will pick it up on the next beat (within 30 s) and the user receives
    progress + final result back via DM (cf. mission_heartbeat
    notifications — Phase 4.4).

    Examples :
      /mission Météo demain :: Donne-moi la météo de Paris pour demain
      /mission Audit emails :: Liste mes 10 derniers mails non lus et résume-les
    """
    tg_id = update.effective_user.id
    if tg_id not in _linked_users:
        await update.message.reply_text(
            "Tu dois d'abord lier ton compte ELY.\nUtilise : /link <nom_utilisateur> <mot_de_passe>"
        )
        return

    raw = " ".join(context.args) if context.args else ""
    if " :: " not in raw:
        await update.message.reply_text(
            "Usage : `/mission <titre> :: <goal>`\n\n"
            "Exemple :\n"
            "`/mission Météo demain :: Donne-moi la météo de Paris pour demain`",
            parse_mode="Markdown",
        )
        return

    title, goal = raw.split(" :: ", 1)
    title = title.strip()[:80]
    goal = goal.strip()
    if not title or len(goal) < 5:
        await update.message.reply_text("Titre ou goal trop court — réessaie.")
        return

    user_id = _linked_users[tg_id]
    try:
        from app.services import mission_service
        from app.services.mission_heartbeat import schedule_first_tick

        m = await mission_service.create_mission(
            user_id=user_id,
            title=title,
            goal=goal,
            source="channel",
            source_ref=f"telegram:{tg_id}",
            budget_iterations=15,
            budget_tokens=80_000,
        )
        await mission_service.start_mission(m.id)
        await schedule_first_tick(m.id)
        await update.message.reply_text(
            f"🎯 *Mission créée et démarrée*\n\n"
            f"*Titre* : {title}\n"
            f"*Goal* : {goal[:200]}\n\n"
            f"ID : `{m.id[:8]}…`\n\n"
            f"Je travaille dessus en arrière-plan. Je te préviens ici quand c'est fini "
            f"(ou si je rencontre un problème). En attendant tu peux suivre la progression sur "
            f"https://ely.catalogmaker.fr/missions/{m.id}",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.exception("cmd_mission failed for tg_id=%s: %s", tg_id, exc)
        await update.message.reply_text(f"Erreur création mission : {exc}")


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

        sf = get_filter(conversation_id)
        history_msgs = []
        for row in history_rows[:-1]:
            if row.role == "user":
                history_msgs.append(HumanMessage(content=sf.anonymize(row.content)))
            elif row.role == "assistant":
                # Stockés désanonymisés (vraies valeurs, pour l'affichage) →
                # re-masquer avant le LLM, comme chat.py (ner off : machine).
                history_msgs.append(AIMessage(
                    content=sf.anonymize(row.content, ner_detection=False)))
        history_msgs = history_msgs[-40:]
        history_msgs.append(HumanMessage(content=sf.anonymize(user_content)))

        # PII sovereignty — see chat.py for full rationale.
        try:
            from app.services.sovereignty import SOVEREIGNTY_STRICT
            SOVEREIGNTY_STRICT.set(bool(getattr(user, "sovereignty_strict", False)))
        except Exception as _sov_exc:  # noqa: BLE001
            logger.debug("sovereignty ContextVar set skipped: %s", _sov_exc)

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

        # ── Anti-hallucination completion guard (C3c) ──────────────────────
        # Same verification the web surface runs, before delivery: replace a
        # claimed action ("c'est supprimé") that no tool actually performed
        # this turn with an honest warning. Buffered surface → derive the
        # tools-in-turn list from the result messages. Never breaks delivery.
        try:
            from app.services.output_verifier import verify_outcome_from_result
            ai_content = verify_outcome_from_result(
                invoke_result, ai_content,
                surface="telegram",
                user_message=user_content,
                user_id=user_id,
                conversation_id=conversation_id,
            ).content
        except Exception as _guard_exc:
            logger.warning("completion_guard skipped (telegram): %s", _guard_exc)

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

    # Force polling mode when the backend is not the one Telegram's webhook
    # points to (typical local dev setup: BACKEND_URL still points to the
    # production VPS domain but we're running on a laptop / Mac Studio).
    # Set TELEGRAM_USE_POLLING=1 in .env to bypass the HTTPS webhook path.
    import os
    force_polling = os.getenv("TELEGRAM_USE_POLLING", "").strip().lower() in {"1", "true", "yes"}

    # Determine webhook URL from config/env
    backend_url = getattr(s, "backend_url", "") or ""
    webhook_url = f"{backend_url.rstrip('/')}/webhook/telegram"
    if force_polling or not backend_url or not backend_url.startswith("https://"):
        # Polling mode — the bot long-polls the Telegram API and receives
        # updates directly in-process, no webhook needed.
        if force_polling:
            logger.info("TELEGRAM_USE_POLLING=1 → polling mode (webhook bypassed)")
            try:
                # Clear any previously registered webhook so Telegram stops
                # forwarding updates to the old URL and lets us poll instead.
                from telegram import Bot as _Bot
                await _Bot(token).delete_webhook(drop_pending_updates=True)
            except Exception as exc:
                logger.debug("delete_webhook failed (non-fatal): %s", exc)
        else:
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
    _bot_app.add_handler(CommandHandler("mission", cmd_mission))
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
    _bot_app.add_handler(CommandHandler("mission", cmd_mission))
    _bot_app.add_handler(CallbackQueryHandler(handle_hitl_callback, pattern=r"^hitl:"))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await _bot_app.initialize()
    await _bot_app.start()
    await _bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started — polling mode")


# B-8 (revue 2026-06-10) — dedup des updates rejouées par Telegram.
# Borné : on garde les ~1000 derniers update_id (un id Telegram est
# strictement croissant, le set suffit).
_SEEN_UPDATE_IDS: "OrderedDict[int, None]" = OrderedDict()
_SEEN_UPDATE_IDS_MAX = 1000


async def receive_telegram_update(data: dict) -> None:
    """Accept an incoming webhook update from Telegram and return FAST.

    Called by the /webhook/telegram FastAPI route.

    B-8 (revue 2026-06-10) : le traitement était inline — la réponse HTTP
    au webhook ne partait qu'APRÈS le run agent complet (souvent > 60 s).
    Telegram considérait le webhook en échec et REJOUAIT le même update →
    agent exécuté 2-3× pour un seul message (actions et coûts dupliqués).
    Désormais : dédup par ``update_id`` puis traitement en tâche de fond
    (référence forte via ``spawn``) — la route répond 200 immédiatement.
    """
    if _bot_app is None:
        logger.warning("Received Telegram webhook but bot is not initialized")
        return
    update = Update.de_json(data, _bot_app.bot)

    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        if update_id in _SEEN_UPDATE_IDS:
            logger.info("Telegram update %s already seen — duplicate dropped", update_id)
            return
        _SEEN_UPDATE_IDS[update_id] = None
        while len(_SEEN_UPDATE_IDS) > _SEEN_UPDATE_IDS_MAX:
            _SEEN_UPDATE_IDS.popitem(last=False)

    from app.services.background_tasks import spawn
    spawn(_bot_app.process_update(update), label=f"telegram-update-{update_id}")


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
