# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/channels/discord_bot.py
# @brief      Discord channel adapter for ELY Agent
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
"""Discord channel adapter for ELY Agent.

Routes Discord messages to the same LangGraph agent used by the Web UI.
Security invariant: same SecurityFilter, same HITL, same tool permissions.

Setup:
  1. Create a Discord Application at https://discord.com/developers/applications
  2. Enable Message Content Intent in Bot settings
  3. Generate a Bot Token
  4. Invite to server with scopes: bot, applications.commands
     Bot permissions: Send Messages, Read Message History, Add Reactions, Manage Messages
  5. In ELY Admin or .env: set DISCORD_BOT_TOKEN
  6. DM the bot: "!link <username> <password>" to link your Discord account
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.services.background_tasks import spawn
import re
import uuid

from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.agent.helpers.message_content import content_to_text
from app.auth.passwords import verify_password
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.memory_manager import get_memory_manager
from app.services.conversation_filters import discard_filter, get_filter
from app.services.hitl_manager import get_hitl_manager

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

# discord_user_id → ely_user_id
_linked_users: dict[int, str] = {}

# discord_user_id → conversation_id
_conversations: dict[int, str] = {}

# PII (C0) : le SecurityFilter vit dans le registre PARTAGÉ
# conversation_filters (indexé par conversation_id) — voir telegram_bot.py.

# Shared agent graph
_agent_graph = None

# Discord client instance
_discord_client = None
_discord_task: asyncio.Task | None = None


def _get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


# ── Startup: load linked users from DB ────────────────────────────────────────

async def _load_linked_users() -> None:
    """Load discord_id → user_id mappings from DB."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.discord_id.isnot(None))
        )
        for user in result.scalars().all():
            _linked_users[int(user.discord_id)] = user.id
    logger.info("Loaded %d linked Discord users", len(_linked_users))


# ── Discord Client ───────────────────────────────────────────────────────────

def _create_client():
    """Create and configure the Discord client with message handlers."""
    try:
        import discord
    except ImportError:
        logger.warning("discord.py not installed — skipping Discord channel")
        return None

    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info("Discord bot logged in as %s (ID: %s)", client.user.name, client.user.id)

    @client.event
    async def on_message(message: discord.Message):
        # Ignore own messages
        if message.author == client.user:
            return

        # Only respond to DMs or mentions in channels
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = client.user in message.mentions if not is_dm else False

        if not is_dm and not is_mentioned:
            return

        # Clean text: remove bot mention
        text = message.content
        if not is_dm:
            text = re.sub(rf"<@!?{client.user.id}>\s*", "", text).strip()

        if not text:
            return

        discord_user_id = message.author.id

        # ── Command: !link ───────────────────────────────────────────
        if text.lower().startswith("!link "):
            parts = text.split(None, 2)
            if len(parts) >= 3:
                await _do_link(discord_user_id, parts[1], parts[2], message)
            else:
                await message.reply("Usage : `!link <nom_utilisateur> <mot_de_passe>`")
            return

        # ── Command: !unlink ─────────────────────────────────────────
        if text.lower() == "!unlink":
            await _do_unlink(discord_user_id, message)
            return

        # ── Command: !new ────────────────────────────────────────────
        if text.lower() == "!new":
            _old_conv = _conversations.pop(discord_user_id, None)
            if _old_conv:
                discard_filter(_old_conv)
            await message.reply("Nouvelle conversation. Que puis-je faire pour toi ?")
            return

        # ── Command: !help ───────────────────────────────────────────
        if text.lower() == "!help":
            await message.reply(
                "**Commandes disponibles :**\n"
                "• `!link <username> <mot_de_passe>` — Lier ton compte ELY\n"
                "• `!unlink` — Délier ton compte\n"
                "• `!new` — Nouvelle conversation\n"
                "• Sinon, envoie-moi ton message directement !"
            )
            return

        # ── Check linked ─────────────────────────────────────────────
        if discord_user_id not in _linked_users:
            await message.reply(
                "Tu dois d'abord lier ton compte ELY.\n"
                "Envoie-moi en DM : `!link <nom_utilisateur> <mot_de_passe>`"
            )
            return

        user_id = _linked_users[discord_user_id]

        # Show typing indicator
        async with message.channel.typing():
            try:
                await _process_message(discord_user_id, user_id, text, message)
            except Exception:
                logger.exception("Error handling Discord message from user %s", discord_user_id)
                await message.reply(
                    "Désolé, une erreur s'est produite. Réessaie dans quelques instants."
                )

    return client


async def _process_message(
    discord_user_id: int,
    user_id: str,
    text: str,
    message,
) -> None:
    """Process a user message through the agent pipeline."""
    # Get or create conversation
    conversation_id = _conversations.get(discord_user_id)

    async with async_session() as db:
        if not conversation_id:
            conv = Conversation(
                user_id=user_id,
                title=f"[Discord] {text[:40]}",
            )
            db.add(conv)
            await db.flush()
            conversation_id = str(conv.id)
            _conversations[discord_user_id] = conversation_id
            await db.commit()

        # Save user message
        db.add(Message(
            conversation_id=conversation_id,
            role="user",
            content=text,
        ))
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
            # Stockés désanonymisés → re-masquer avant le LLM (cf. chat.py).
            history_msgs.append(AIMessage(
                content=sf.anonymize(row.content, ner_detection=False)))
    history_msgs = history_msgs[-40:]
    history_msgs.append(HumanMessage(content=sf.anonymize(text)))

    # Invoke agent
    # V2-1 — départ du chrono AVANT l'invocation : c'est le temps
    # que l'utilisateur attend réellement (vague 2).
    _turn_started_at = time.monotonic()
    agent = _get_agent()
    # V1 temps 1 — le profil court-circuite le routeur et donne le
    # runtime unique : outils appris, <learned_skills>, vecteur
    # d etat et preferences arrivent enfin sur ce canal.
    from app.agent.toolset_profiles import resolve_conversation_profile
    _profile = await resolve_conversation_profile(conversation_id, user_content)
    invoke_result = await agent.ainvoke({
        "messages": history_msgs,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "toolset_profile": _profile,
    })

    # content_to_text AVANT deanonymize : sur tier codex (Responses API),
    # ``content`` arrive en liste de blocs — str.replace crasherait.
    ai_content = content_to_text(invoke_result["messages"][-1].content)
    ai_content = sf.deanonymize(ai_content)

    # ── Anti-hallucination completion guard (C3c) ──────────────────────────
    # Verify before delivery, exactly as the web surface does (shared
    # OutcomeVerifier). Buffered surface → tools derived from the result
    # messages. Never breaks delivery.
    try:
        from app.services.output_verifier import verify_outcome_from_result
        ai_content = verify_outcome_from_result(
            invoke_result, ai_content,
            surface="discord",
            user_message=text,
            user_id=user_id,
            conversation_id=conversation_id,
        ).content
    except Exception as _guard_exc:
        logger.warning("completion_guard skipped (discord): %s", _guard_exc)

    # Save assistant message
    async with async_session() as db:
        db.add(Message(
            conversation_id=conversation_id,
            role="assistant",
            content=ai_content,
        ))
        await db.commit()

    # V2-1 (vague 2) — ce canal n'enregistrait AUCUNE ligne d'usage :
    # l'architecture a sous-agents etait donc invisible dans les
    # chiffres, et la question mono/sous-agents non mesurable.
    # latency_ms + architecture (sub_agent:<domaine>) sont posees ici.
    from app.services.usage_instrumentation import record_turn_usage
    spawn(record_turn_usage(
        user_id=user_id,
        conversation_id=conversation_id,
        channel="discord",
        result=invoke_result,
        started_at=_turn_started_at,
    ), label="usage:discord")

    # Store interaction in vector memory
    memory = get_memory_manager()
    await memory.store_interaction(
        user_msg=text,
        assistant_msg=ai_content,
        user_id=user_id,
        conversation_id=conversation_id,
    )

    # Send response (split at 2000 chars — Discord limit)
    for i in range(0, len(ai_content), 2000):
        await message.reply(ai_content[i:i + 2000])


async def _do_link(
    discord_user_id: int,
    username: str,
    password: str,
    message,
) -> None:
    """Link a Discord user to an ELY account."""
    # Try to delete the message containing credentials
    try:
        await message.delete()
    except Exception:
        await message.channel.send(
            "Je n'ai pas pu supprimer ton message contenant tes identifiants. "
            "Supprime-le manuellement."
        )

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user or not await verify_password(password, user.hashed_password):
            await message.channel.send("Identifiants incorrects.")
            return

        user.discord_id = str(discord_user_id)
        await db.commit()
        _linked_users[discord_user_id] = user.id

    await message.channel.send(
        f"Compte lié avec succès ! Bienvenue, {username}.\n"
        "Tu peux maintenant me parler directement ici."
    )
    logger.info("Discord user %s linked to ELY user %s", discord_user_id, username)


async def _do_unlink(discord_user_id: int, message) -> None:
    """Unlink a Discord user from their ELY account."""
    user_id = _linked_users.pop(discord_user_id, None)
    if user_id:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.discord_id = None
                await db.commit()
        await message.reply("Compte délié. Utilise `!link <username> <password>` pour te reconnecter.")
    else:
        await message.reply("Aucun compte lié.")


# ── HITL via Discord reactions ───────────────────────────────────────────────

async def send_hitl_validation(
    discord_user_id: int,
    description: str,
    request_id: str,
) -> None:
    """Send HITL validation request via Discord DM with reaction buttons."""
    if not _discord_client or not _discord_client.is_ready():
        return

    try:
        user = await _discord_client.fetch_user(discord_user_id)
        dm = await user.create_dm()

        msg = await dm.send(
            f"**Action nécessitant validation :**\n{description[:1800]}\n\n"
            f"Réagis avec : ✅ Autoriser | ❌ Refuser | 🚫 Interdire\n"
            f"ID: `{request_id}`"
        )

        # Add reaction options
        for emoji in ("✅", "❌", "🚫"):
            await msg.add_reaction(emoji)

        # Wait for reaction (60s timeout)
        def check(reaction, reactor):
            return (
                reactor.id == discord_user_id
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("✅", "❌", "🚫")
            )

        try:
            reaction, _ = await _discord_client.wait_for(
                "reaction_add",
                timeout=300.0,  # 5 minutes
                check=check,
            )
            emoji = str(reaction.emoji)
            decision = {"✅": "allow", "❌": "deny", "🚫": "ban"}.get(emoji, "deny")

            hitl = get_hitl_manager()
            await hitl.resolve(request_id, decision)

            labels = {"allow": "Autorisé", "deny": "Refusé", "ban": "Interdit définitivement"}
            await msg.edit(
                content=(
                    f"**Action nécessitant validation :**\n{description[:1800]}\n\n"
                    f"**Décision :** {labels.get(decision, decision)}"
                )
            )
        except asyncio.TimeoutError:
            hitl = get_hitl_manager()
            await hitl.resolve(request_id, "deny")
            await msg.edit(
                content=(
                    f"**Action nécessitant validation :**\n{description[:1800]}\n\n"
                    "**Décision :** Refusé (timeout)"
                )
            )

    except Exception as exc:
        logger.error("Failed to send HITL to Discord user %s: %s", discord_user_id, exc)


# ── Bot lifecycle ────────────────────────────────────────────────────────────

async def start_discord_bot() -> None:
    """Start the Discord bot (called from FastAPI lifespan).

    Runs the discord.py client in a background asyncio task so it doesn't
    block the FastAPI event loop.
    """
    global _discord_client, _discord_task

    from app.services.system_config import get_config
    from app.config import get_settings

    s = get_settings()
    token = await get_config(
        "discord_bot_token",
        fallback=getattr(s, "discord_bot_token", ""),
    )

    if not token:
        logger.info("Discord bot token not configured — skipping Discord channel")
        return

    try:
        import discord  # noqa: F401
    except ImportError:
        logger.warning("discord.py not installed — skipping Discord channel")
        return

    await _load_linked_users()

    _discord_client = _create_client()
    if not _discord_client:
        return

    # Run in background task
    _discord_task = asyncio.create_task(_discord_client.start(token))
    logger.info("Discord bot starting in background task")


async def stop_discord_bot() -> None:
    """Stop the Discord bot gracefully."""
    global _discord_client, _discord_task
    if _discord_client:
        try:
            await _discord_client.close()
        except Exception as exc:
            logger.warning("Error stopping Discord bot: %s", exc)
    if _discord_task:
        _discord_task.cancel()
        try:
            await _discord_task
        except (asyncio.CancelledError, Exception):
            pass
        _discord_task = None
    _discord_client = None
    logger.info("Discord bot stopped")
