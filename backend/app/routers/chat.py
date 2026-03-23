import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.auth.jwt import decode_token
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter
from app.services import ws_registry

logger = logging.getLogger(__name__)

router = APIRouter()

# One graph instance shared across all connections
_agent_graph = None

# One SecurityFilter per conversation (persists placeholders within a session)
_filters: dict[str, SecurityFilter] = {}


def get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    # NOTE: websocket.accept() MUST be called before websocket.close().
    # Calling close() on an unaccepted WebSocket raises a protocol error
    # which manifests as an immediate disconnect in the logs.
    # All auth rejections must therefore accept first, then close.

    token = websocket.query_params.get("token")
    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.accept()
            await websocket.close(code=4001, reason="User not found")
            return

    await websocket.accept()
    ws_registry.register(user_id, websocket)

    conversation_id: str | None = None

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Malformed JSON from user %s (ignored): %.200s", user_id, data)
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Message invalide — JSON mal formé.",
                }))
                continue

            user_content = msg.get("content", "")
            conversation_id = msg.get("conversation_id") or conversation_id

            async with async_session() as db:
                # Re-read user on each message to pick up latest google_credentials
                u_result = await db.execute(select(User).where(User.id == user_id))
                fresh_user = u_result.scalar_one_or_none()
                google_credentials = fresh_user.google_credentials if fresh_user else None

                if not conversation_id:
                    conv = Conversation(user_id=user_id, title=user_content[:50])
                    db.add(conv)
                    await db.flush()
                    conversation_id = str(conv.id)
                    await db.commit()

                user_msg = Message(
                    conversation_id=conversation_id, role="user", content=user_content
                )
                db.add(user_msg)
                await db.commit()

            # Anonymize input through per-conversation filter
            sf = _filters.setdefault(conversation_id, SecurityFilter())
            clean_content = sf.anonymize(user_content)

            # Load conversation history (last 20 exchanges = 40 messages max)
            async with async_session() as db:
                hist_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.asc())
                )
                history_rows = hist_result.scalars().all()

            # Build LangChain message list from DB history (exclude the just-saved user msg)
            _MAX_HISTORY = 40
            history_msgs = []
            for row in history_rows[:-1]:  # skip current user message already saved
                if row.role == "user":
                    history_msgs.append(HumanMessage(content=sf.anonymize(row.content)))
                elif row.role == "assistant":
                    history_msgs.append(AIMessage(content=row.content))
            # Keep only last _MAX_HISTORY messages to stay within context limits
            history_msgs = history_msgs[-_MAX_HISTORY:]
            history_msgs.append(HumanMessage(content=clean_content))

            agent = get_agent()
            await websocket.send_text(json.dumps({
                "type": "start",
                "conversation_id": conversation_id,
            }))

            invoke_result = await agent.ainvoke({
                "messages": history_msgs,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "google_credentials": google_credentials or "",
            })

            ai_content = invoke_result["messages"][-1].content
            # Restore real values in the response
            ai_content = sf.deanonymize(ai_content)

            async with async_session() as db:
                ai_msg = Message(
                    conversation_id=conversation_id, role="assistant", content=ai_content
                )
                db.add(ai_msg)
                await db.commit()

            memory = get_memory_manager()
            await memory.store_interaction(
                user_msg=user_content,
                assistant_msg=ai_content,
                user_id=user_id,
                conversation_id=str(conversation_id),
            )

            await websocket.send_text(json.dumps({
                "type": "message",
                "role": "assistant",
                "content": ai_content,
                "conversation_id": conversation_id,
            }))

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for user %s", user_id)
    except Exception as e:
        logger.exception("Unexpected error in WebSocket handler for user %s", user_id)
        try:
            await websocket.send_text(json.dumps({"type": "error", "content": str(e)}))
        except Exception:
            pass  # Socket may already be closed; swallow the secondary error
    finally:
        ws_registry.unregister(user_id)
        # On disconnect: summarize conversation into long-term memory
        if conversation_id:
            asyncio.create_task(
                _summarize_conversation(conversation_id, user_id)
            )
        _filters.pop(conversation_id, None) if conversation_id else None


async def _summarize_conversation(conversation_id: str, user_id: str) -> None:
    """Generate a summary + extract user profile facts; store both in Qdrant + FTS5.

    Called on WebSocket disconnect so it never blocks the active session.
    Skipped when the conversation has fewer than 4 messages (2 exchanges).

    Two LLM calls are run in parallel:
    1. Holistic summary  — 3-6 sentences about what happened / was learned.
    2. Profile facts     — JSON list of durable facts about the user
                           (name, preferences, habits, family, work, etc.).

    Each extracted fact is stored as an individual memory entry so it can
    be retrieved independently by semantic + keyword search later.
    """
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
            msgs = result.scalars().all()

        if len(msgs) < 4:
            return  # Too short to summarize

        # Compact transcript — last 30 messages, 300 chars per message
        transcript = "\n".join(
            f"{'Utilisateur' if m.role == 'user' else 'ELY'}: {m.content[:300]}"
            for m in msgs[-30:]
        )

        from app.services.llm_provider import get_llm
        llm = get_llm()

        summary_prompt = (
            "Résume en 3 à 6 phrases les informations importantes apprises sur l'utilisateur "
            "dans cette conversation : ses préférences, habitudes, événements mentionnés, "
            "personnes importantes, contexte de vie et de travail. "
            "Formule au présent ('L'utilisateur a un chien nommé...', 'Il travaille sur...', etc.).\n\n"
            f"Conversation :\n{transcript}"
        )

        facts_prompt = (
            "À partir de cette conversation, extrais les faits durables et importants sur "
            "l'utilisateur (prénom/nom, âge, localisation, préférences, habitudes, famille, "
            "amis, travail, projets, outils utilisés, abonnements, etc.).\n"
            "Réponds UNIQUEMENT avec un tableau JSON de phrases courtes au présent, "
            "une par fait. Exemple :\n"
            '[\"L\'utilisateur s\'appelle Franck\", \"Il vit en France\", '
            '"Il travaille sur un projet d\'IA nommé ELY"]\n'
            "Retourne [] si aucun fait nouveau n'est clairement identifiable.\n\n"
            f"Conversation :\n{transcript}"
        )

        # Run both LLM calls concurrently to minimise latency
        summary_resp, facts_resp = await asyncio.gather(
            llm.ainvoke([{"role": "user", "content": summary_prompt}]),
            llm.ainvoke([{"role": "user", "content": facts_prompt}]),
        )

        memory = get_memory_manager()

        # ── 1. Store holistic summary ────────────────────────────────────
        summary = summary_resp.content.strip()
        if summary:
            await memory.store_memory(
                content=summary,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            logger.info("Conversation %s summarized into long-term memory", conversation_id)

        # ── 2. Store individual profile facts ────────────────────────────
        import json as _json
        raw = facts_resp.content.strip()
        # Strip markdown code fences if the model wrapped the JSON
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        try:
            facts = _json.loads(raw)
        except (_json.JSONDecodeError, ValueError):
            facts = []

        if isinstance(facts, list):
            stored_count = 0
            for fact in facts[:12]:  # safety cap
                if isinstance(fact, str) and len(fact) > 10:
                    await memory.store_memory(
                        content=fact,
                        user_id=user_id,
                        conversation_id=conversation_id,
                    )
                    stored_count += 1
            if stored_count:
                logger.info(
                    "Extracted %d profile fact(s) from conversation %s",
                    stored_count,
                    conversation_id,
                )

    except Exception as exc:
        logger.warning("Failed to summarize conversation %s: %s", conversation_id, exc)
