# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/channels/slack_bot.py
# @brief      Slack channel adapter for ELY Agent
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
"""Slack channel adapter for ELY Agent.

Routes Slack messages to the same LangGraph agent used by the Web UI.
Security invariant: same SecurityFilter, same HITL, same tool permissions.

Setup:
  1. Create a Slack App at https://api.slack.com/apps
  2. Enable Socket Mode (generates an App-Level Token starting with xapp-)
  3. Subscribe to bot events: message.im, message.channels, app_mention
  4. Install bot scopes: chat:write, im:history, channels:history, app_mentions:read, users:read
  5. Install to workspace → copy Bot User OAuth Token (xoxb-...)
  6. In ELY Admin or .env: set SLACK_BOT_TOKEN and SLACK_APP_TOKEN
  7. Invite @ELY to any channel where you want to use it
  8. DM the bot: "link <username> <password>" to link your Slack account
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.auth.passwords import verify_password
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter
from app.services.hitl_manager import get_hitl_manager

logger = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

# slack_user_id → ely_user_id
_linked_users: dict[str, str] = {}

# slack_user_id → conversation_id
_conversations: dict[str, str] = {}

# slack_user_id → SecurityFilter
_filters: dict[str, SecurityFilter] = {}

# Shared agent graph
_agent_graph = None

# Slack app instance
_slack_app = None
_socket_handler = None


def _get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


# ── Startup: load linked users from DB ────────────────────────────────────────

async def _load_linked_users() -> None:
    """Load slack_id → user_id mappings from DB."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.slack_id.isnot(None))
        )
        for user in result.scalars().all():
            _linked_users[user.slack_id] = user.id
    logger.info("Loaded %d linked Slack users", len(_linked_users))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_link_command(text: str) -> tuple[str, str] | None:
    """Parse 'link <username> <password>' from message text."""
    parts = text.strip().split(None, 2)
    if len(parts) >= 3 and parts[0].lower() == "link":
        return parts[1], parts[2]
    return None


def _parse_command(text: str) -> str | None:
    """Parse single-word commands: new, unlink, help."""
    word = text.strip().lower()
    if word in ("new", "unlink", "help"):
        return word
    return None


# ── Message handler ──────────────────────────────────────────────────────────

async def _handle_message(body: dict, say, client) -> None:
    """Handle incoming Slack messages — route to agent."""
    event = body.get("event", {})
    slack_user_id = event.get("user", "")
    text = event.get("text", "").strip()
    channel = event.get("channel", "")

    # Ignore bot's own messages
    if event.get("bot_id") or not text:
        return

    # Strip bot mention from text (<@U12345> message → message)
    import re
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
    if not text:
        return

    # ── Command: link ────────────────────────────────────────────────────
    link_args = _parse_link_command(text)
    if link_args:
        username, password = link_args
        await _do_link(slack_user_id, username, password, say, client, channel)
        return

    # ── Command: unlink / new / help ─────────────────────────────────────
    cmd = _parse_command(text)
    if cmd == "unlink":
        await _do_unlink(slack_user_id, say)
        return
    if cmd == "new":
        _conversations.pop(slack_user_id, None)
        _filters.pop(slack_user_id, None)
        await say("Nouvelle conversation. Que puis-je faire pour toi ?")
        return
    if cmd == "help":
        await say(
            "*Commandes disponibles :*\n"
            "• `link <username> <mot_de_passe>` — Lier ton compte ELY\n"
            "• `unlink` — Délier ton compte\n"
            "• `new` — Nouvelle conversation\n"
            "• Sinon, envoie-moi ton message directement !"
        )
        return

    # ── Check linked ─────────────────────────────────────────────────────
    if slack_user_id not in _linked_users:
        await say(
            "Tu dois d'abord lier ton compte ELY.\n"
            "Envoie-moi en DM : `link <nom_utilisateur> <mot_de_passe>`"
        )
        return

    user_id = _linked_users[slack_user_id]

    try:
        # Get or create conversation
        conversation_id = _conversations.get(slack_user_id)

        async with async_session() as db:
            if not conversation_id:
                conv = Conversation(
                    user_id=user_id,
                    title=f"[Slack] {text[:40]}",
                )
                db.add(conv)
                await db.flush()
                conversation_id = str(conv.id)
                _conversations[slack_user_id] = conversation_id
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

        sf = _filters.setdefault(slack_user_id, SecurityFilter())
        history_msgs = []
        for row in history_rows[:-1]:
            if row.role == "user":
                history_msgs.append(HumanMessage(content=sf.anonymize(row.content)))
            elif row.role == "assistant":
                history_msgs.append(AIMessage(content=row.content))
        history_msgs = history_msgs[-40:]
        history_msgs.append(HumanMessage(content=sf.anonymize(text)))

        # Invoke agent
        agent = _get_agent()
        invoke_result = await agent.ainvoke({
            "messages": history_msgs,
            "user_id": user_id,
            "conversation_id": conversation_id,
        })

        ai_content = invoke_result["messages"][-1].content
        ai_content = sf.deanonymize(ai_content)

        # Save assistant message
        async with async_session() as db:
            db.add(Message(
                conversation_id=conversation_id,
                role="assistant",
                content=ai_content,
            ))
            await db.commit()

        # Store interaction in vector memory
        memory = get_memory_manager()
        await memory.store_interaction(
            user_msg=text,
            assistant_msg=ai_content,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        # Send response (split at 3000 chars — Slack limit is ~4000 for blocks)
        for i in range(0, len(ai_content), 3000):
            await say(ai_content[i:i + 3000])

    except Exception:
        logger.exception("Error handling Slack message from user %s", slack_user_id)
        await say("Désolé, une erreur s'est produite. Réessaie dans quelques instants.")


async def _do_link(
    slack_user_id: str,
    username: str,
    password: str,
    say,
    client,
    channel: str,
) -> None:
    """Link a Slack user to an ELY account."""
    # Try to delete the message containing credentials
    # (only works in channels, not always in DMs)
    try:
        event = {}  # We cannot delete DMs easily, just warn
        await say(
            "Pour ta sécurité, utilise cette commande uniquement en message privé (DM) avec moi."
        )
    except Exception:
        pass

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user or not await verify_password(password, user.hashed_password):
            await say("Identifiants incorrects.")
            return

        user.slack_id = slack_user_id
        await db.commit()
        _linked_users[slack_user_id] = user.id

    await say(
        f"Compte lié avec succès ! Bienvenue, {username}.\n"
        "Tu peux maintenant me parler directement ici."
    )
    logger.info("Slack user %s linked to ELY user %s", slack_user_id, username)


async def _do_unlink(slack_user_id: str, say) -> None:
    """Unlink a Slack user from their ELY account."""
    user_id = _linked_users.pop(slack_user_id, None)
    if user_id:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.slack_id = None
                await db.commit()
        await say("Compte délié. Utilise `link <username> <password>` pour te reconnecter.")
    else:
        await say("Aucun compte lié.")


# ── HITL via Slack interactive buttons ───────────────────────────────────────

async def send_hitl_validation(
    slack_user_id: str,
    description: str,
    request_id: str,
) -> None:
    """Send HITL validation request as Slack Block Kit buttons."""
    if not _slack_app:
        return

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Action nécessitant validation :*\n{description[:2500]}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Autoriser"},
                    "style": "primary",
                    "action_id": f"hitl_allow_{request_id}",
                    "value": request_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Refuser"},
                    "style": "danger",
                    "action_id": f"hitl_deny_{request_id}",
                    "value": request_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Interdire"},
                    "action_id": f"hitl_ban_{request_id}",
                    "value": request_id,
                },
            ],
        },
    ]

    try:
        # Send DM to the user
        resp = await _slack_app.client.conversations_open(users=[slack_user_id])
        dm_channel = resp["channel"]["id"]
        await _slack_app.client.chat_postMessage(
            channel=dm_channel,
            blocks=blocks,
            text=f"Action nécessitant validation : {description[:200]}",
        )
    except Exception as exc:
        logger.error("Failed to send HITL to Slack user %s: %s", slack_user_id, exc)


async def _handle_hitl_action(ack, body, client) -> None:
    """Handle HITL button clicks from Slack."""
    await ack()

    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")
    request_id = action.get("value", "")

    if "hitl_allow_" in action_id:
        decision = "allow"
    elif "hitl_deny_" in action_id:
        decision = "deny"
    elif "hitl_ban_" in action_id:
        decision = "ban"
    else:
        return

    hitl = get_hitl_manager()
    await hitl.resolve(request_id, decision)

    labels = {"allow": "Autorisé", "deny": "Refusé", "ban": "Interdit définitivement"}

    # Update the original message
    try:
        await client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"Action {labels.get(decision, decision)} : {request_id}",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{body['message'].get('text', '')}\n\n"
                            f"*Décision :* {labels.get(decision, decision)}"
                        ),
                    },
                }
            ],
        )
    except Exception as exc:
        logger.warning("Could not update HITL Slack message: %s", exc)


# ── Bot lifecycle ────────────────────────────────────────────────────────────

async def start_slack_bot() -> None:
    """Start the Slack bot in Socket Mode (called from FastAPI lifespan).

    Socket Mode uses a WebSocket connection initiated by the app (outbound),
    so it works behind firewalls and NATs without needing a public URL.
    """
    global _slack_app, _socket_handler

    from app.services.system_config import get_config
    from app.config import get_settings

    s = get_settings()
    bot_token = await get_config(
        "slack_bot_token",
        fallback=getattr(s, "slack_bot_token", ""),
    )
    app_token = await get_config(
        "slack_app_token",
        fallback=getattr(s, "slack_app_token", ""),
    )

    if not bot_token or not app_token:
        logger.info("Slack bot/app token not configured — skipping Slack channel")
        return

    try:
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    except ImportError:
        logger.warning("slack-bolt not installed — skipping Slack channel")
        return

    await _load_linked_users()

    _slack_app = AsyncApp(token=bot_token)

    # Register event handlers
    _slack_app.event("message")(_handle_message)
    _slack_app.event("app_mention")(_handle_message)

    # Register HITL action handlers (pattern matches action_id prefix)
    _slack_app.action({"action_id": "hitl_allow_"})(_handle_hitl_action)
    _slack_app.action({"action_id": "hitl_deny_"})(_handle_hitl_action)
    _slack_app.action({"action_id": "hitl_ban_"})(_handle_hitl_action)

    _socket_handler = AsyncSocketModeHandler(_slack_app, app_token)
    await _socket_handler.connect_async()

    logger.info("Slack bot started — Socket Mode")


async def stop_slack_bot() -> None:
    """Stop the Slack bot gracefully."""
    global _slack_app, _socket_handler
    if _socket_handler:
        try:
            await _socket_handler.close_async()
        except Exception as exc:
            logger.warning("Error stopping Slack socket handler: %s", exc)
        _socket_handler = None
    _slack_app = None
    logger.info("Slack bot stopped")
