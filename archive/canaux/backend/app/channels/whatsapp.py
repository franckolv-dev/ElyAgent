# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/channels/whatsapp.py
# @brief      WhatsApp channel adapter for ELY Agent via Meta Cloud API
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""WhatsApp channel adapter for ELY Agent via Meta Cloud API.

Setup:
  1. Create a Meta App at developers.facebook.com
  2. Add WhatsApp product, get a test phone number
  3. Set WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_WEBHOOK_VERIFY_TOKEN
  4. Configure webhook URL: https://your-domain/api/webhook/whatsapp
     (needs HTTPS — use ngrok for local dev: ngrok http 8000)

Security:
  - X-Hub-Signature-256 validation on every webhook
  - User must explicitly link their WA number via the admin UI
  - Same SecurityFilter + HITL as Web UI and Telegram
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select

from app.agent.helpers.message_content import content_to_text
from app.database import async_session
from app.models.user import User

logger = logging.getLogger(__name__)

# WhatsApp phone number (string) → ELY user_id mapping (loaded at startup)
_linked_users: dict[str, str] = {}

# WhatsApp phone number → conversation_id
_conversations: dict[str, str] = {}


# ── Startup ───────────────────────────────────────────────────────────────────

async def load_linked_whatsapp_users() -> None:
    """Load whatsapp_phone → user_id mappings from DB at startup."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.whatsapp_phone.isnot(None))
        )
        for user in result.scalars().all():
            _linked_users[user.whatsapp_phone] = user.id
    logger.info("Loaded %d linked WhatsApp users", len(_linked_users))


# ── Signature verification ─────────────────────────────────────────────────────

def verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 header."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Send message ──────────────────────────────────────────────────────────────

async def send_whatsapp_message(phone_number: str, text: str) -> bool:
    """Send a text message to a WhatsApp user.

    Two transports are tried in order :
      1. WhatsApp Web (neonize) — if the recipient's user has an active
         paired session. Uses the user's own WhatsApp account.
      2. Meta Cloud API — fallback when no WA Web session is available
         and the Meta credentials are configured.

    The caller (`process_whatsapp_message`) doesn't need to know which
    transport was used.
    """
    # ── Transport 1 : WhatsApp Web (neonize) ──────────────────────────
    # Look up the user_id linked to this phone. If that user has a live
    # neonize session, send via them — it's a single network hop to WhatsApp
    # and doesn't need a Meta Business setup.
    target_user_id = _linked_users.get(phone_number)
    if target_user_id:
        try:
            from app.channels.whatsapp_web import _sessions as _wa_web_sessions, send_text
            sess = _wa_web_sessions.get(target_user_id)
            if sess and sess.get("status") == "linked":
                ok = await send_text(phone_number, text, from_user_id=target_user_id)
                if ok:
                    return True
                # Fallthrough to Meta if neonize returned False
        except Exception as exc:
            logger.warning("WhatsApp Web send failed, falling back to Meta: %s", exc)

    # ── Transport 2 : Meta Cloud API ──────────────────────────────────
    from app.config import get_settings
    s = get_settings()

    if not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        logger.warning("WhatsApp not configured — cannot send message")
        return False

    url = f"https://graph.facebook.com/v21.0/{s.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {s.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Failed to send WhatsApp message to %s: %s", phone_number, exc)
        return False


# ── Message processing ────────────────────────────────────────────────────────

async def process_whatsapp_message(from_phone: str, message_text: str) -> None:
    """Process an incoming WhatsApp text message through the ELY agent."""
    from app.agent.graph import build_agent_graph
    from app.models.conversation import Conversation, Message
    from app.services.memory_manager import get_memory_manager
    from app.services.conversation_filters import get_filter
    from langchain_core.messages import HumanMessage, AIMessage

    # Check if user is linked
    if from_phone not in _linked_users:
        await send_whatsapp_message(
            from_phone,
            "Bonjour ! Je suis ELY, ton assistant personnel.\n\n"
            "Pour utiliser ELY via WhatsApp, demande à l'administrateur "
            "de lier ton numéro à ton compte via l'interface d'administration."
        )
        return

    user_id = _linked_users[from_phone]

    try:
        # Get or create conversation
        conversation_id = _conversations.get(from_phone)

        async with async_session() as db:
            u_result = await db.execute(select(User).where(User.id == user_id))
            user = u_result.scalar_one_or_none()
            google_credentials = user.google_credentials if user else None

            if not conversation_id:
                conv = Conversation(
                    user_id=user_id,
                    title=f"[WhatsApp] {message_text[:40]}"
                )
                db.add(conv)
                await db.flush()
                conversation_id = str(conv.id)
                _conversations[from_phone] = conversation_id
                await db.commit()

            db.add(Message(
                conversation_id=conversation_id,
                role="user",
                content=message_text,
            ))
            await db.commit()

        # Load history
        async with async_session() as db:
            from sqlalchemy import select as sa_select
            hist_result = await db.execute(
                sa_select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            history_rows = hist_result.scalars().all()

        # PII (C0) : filtre PARTAGÉ du registre (indexé conversation_id) — un
        # filtre jetable rendait les placeholders irrésolubles par tool_node
        # et les sous-agents (voir telegram_bot.py).
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
        history_msgs.append(HumanMessage(content=sf.anonymize(message_text)))

        # PII sovereignty — see chat.py for full rationale.
        # ⚠️ CE QUE ÇA CORRIGE (audit 02/09/2026) : ce canal ne posait pas le
        # ContextVar, un utilisateur en souveraineté stricte repartait donc
        # sur son fournisseur cloud habituel dès qu'il écrivait par WhatsApp.
        try:
            from app.services.sovereignty import SOVEREIGNTY_STRICT
            SOVEREIGNTY_STRICT.set(bool(getattr(user, "sovereignty_strict", False)))
        except Exception as _sov_exc:  # noqa: BLE001
            logger.debug("sovereignty ContextVar set skipped: %s", _sov_exc)

        # Invoke agent
        # Chrono démarré AVANT l'invocation : c'est le temps réellement attendu.
        _turn_started_at = time.monotonic()
        agent = build_agent_graph()
        # ⚠️ CE QUE ÇA CORRIGE (audit 02/09/2026) : WhatsApp était le seul
        # canal de conversation à invoquer le graphe SANS `toolset_profile`
        # (Telegram, Slack, Discord et la voix le passent depuis la vague 1).
        #
        # Ce que le profil apporte RÉELLEMENT aujourd'hui — il n'y a plus de
        # superviseur ni de sous-agents à court-circuiter depuis le temps 2,
        # WhatsApp tournait déjà sur l'unique nœud agent :
        #   - `routing.should_bind_tools` branche les outils dès qu'un profil
        #     est collé à la conversation. Sans lui, un tour hors tier COMPLEX
        #     ne voyait ses outils que si la demande contenait un mot-clé.
        #   - `nodes.agent_node` résout alors le catalogue par le profil de la
        #     conversation (tout au tier COMPLEX, `compact` ailleurs) au lieu
        #     de refiltrer par mots-clés à chaque tour : le catalogue devient
        #     STABLE d'une question à l'autre, donc apprenable par le modèle,
        #     et le préfixe du prompt cesse de bouger.
        #   - `usage_instrumentation.architecture_label` étiquette le tour
        #     « mono » au tableau de bord au lieu de « unknown ».
        # Les outils appris, le bloc <learned_skills>, le vecteur d'état et
        # les préférences ne dépendent PAS de ce champ : ils viennent de
        # `builders/memory_snapshot` à partir de l'utilisateur et arrivaient
        # déjà ici.
        # whatsapp_web.py (pont neonize) délègue ici : il héritait du trou.
        from app.agent.toolset_profiles import resolve_conversation_profile
        _profile = await resolve_conversation_profile(conversation_id, message_text)
        invoke_result = await agent.ainvoke({
            "messages": history_msgs,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "google_credentials": google_credentials or "",
            "toolset_profile": _profile,
        })

        # content_to_text AVANT deanonymize : sur tier codex (Responses API),
        # ``content`` arrive en liste de blocs — str.replace crasherait.
        ai_content = content_to_text(invoke_result["messages"][-1].content)
        ai_content = sf.deanonymize(ai_content)

        # ── Anti-hallucination completion guard (C3c) ──────────────────────
        # Verify before delivery, exactly as the web surface does (shared
        # OutcomeVerifier). Buffered surface → tools derived from the result
        # messages. One guard point covers both transports (Meta Cloud API +
        # neonize) since they funnel through send_whatsapp_message. Never
        # breaks delivery.
        try:
            from app.services.output_verifier import verify_outcome_from_result
            ai_content = verify_outcome_from_result(
                invoke_result, ai_content,
                surface="whatsapp",
                user_message=message_text,
                user_id=user_id,
                conversation_id=conversation_id,
            ).content
        except Exception as _guard_exc:
            logger.warning("completion_guard skipped (whatsapp): %s", _guard_exc)

        # Save response
        async with async_session() as db:
            db.add(Message(
                conversation_id=conversation_id,
                role="assistant",
                content=ai_content,
            ))
            await db.commit()

        # ⚠️ CE QUE ÇA CORRIGE (audit 02/09/2026) : ce canal n'écrivait AUCUNE
        # ligne d'usage — coût, latence et architecture des tours WhatsApp
        # étaient invisibles au tableau de bord, là où Telegram et Slack les
        # posent depuis la vague 2. Best-effort : l'analytique ne doit jamais
        # coûter une réponse déjà produite.
        try:
            from app.services.background_tasks import spawn
            from app.services.usage_instrumentation import record_turn_usage
            spawn(record_turn_usage(
                user_id=user_id,
                conversation_id=conversation_id,
                channel="whatsapp",
                result=invoke_result,
                started_at=_turn_started_at,
                toolset_profile=_profile,
            ), label="usage:whatsapp")
        except Exception as _usage_exc:
            logger.warning("usage accounting skipped (whatsapp): %s", _usage_exc)

        # Store in memory
        await get_memory_manager().store_interaction(
            user_msg=message_text,
            assistant_msg=ai_content,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        # Split long messages (WhatsApp limit 4096)
        for i in range(0, len(ai_content), 4096):
            await send_whatsapp_message(from_phone, ai_content[i:i+4096])

    except Exception as exc:
        logger.exception("Error processing WhatsApp message from %s", from_phone)
        await send_whatsapp_message(
            from_phone,
            "Désolé, une erreur s'est produite. Réessaie dans quelques instants."
        )
