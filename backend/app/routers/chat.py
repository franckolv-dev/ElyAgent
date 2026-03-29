import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path

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

# One SecurityFilter per conversation (bounded LRU to prevent unbounded memory growth)
from collections import OrderedDict


class _BoundedDict(OrderedDict):
    def __init__(self, maxsize: int = 1000):
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)


_filters: _BoundedDict = _BoundedDict(maxsize=1000)


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
    #
    # Token is received as the first message (JSON handshake) after accept,
    # NOT as a URL query param, to avoid the token appearing in server logs.

    await websocket.accept()

    try:
        handshake = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        data = json.loads(handshake)
        token = data.get("token", "")
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError):
        await websocket.close(code=1008)
        return

    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return
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

            # Enrich content with attached file paths so the agent can process them
            attachments = msg.get("attachments") or []
            if attachments:
                file_lines = "\n".join(
                    f"• {a.get('filename', '?')} → {a.get('path', '?')}"
                    for a in attachments
                    if a.get("path")
                )
                user_content = f"{user_content}\n\n📎 Fichiers joints :\n{file_lines}".strip()

            # Screen capture — save base64 PNG to uploads dir, inject path into content
            screen_b64 = msg.get("screen_capture")
            if screen_b64:
                try:
                    upload_dir = Path("/app/uploads") / user_id
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    screen_path = upload_dir / f"screen_{uuid.uuid4().hex[:8]}.png"
                    screen_path.write_bytes(base64.b64decode(screen_b64))
                    user_content = (
                        f"{user_content}\n\n📸 Capture d'écran partagée → {screen_path}"
                    ).strip()
                    logger.debug("Screen capture saved to %s", screen_path)
                except Exception as exc:
                    logger.warning("Failed to save screen capture: %s", exc)

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
            _MAX_HISTORY = 40
            async with async_session() as db:
                hist_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(_MAX_HISTORY + 2)
                )
                history_rows = list(reversed(hist_result.scalars().all()))
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

            ai_content = ""
            model_used_out: str = ""
            routing_score_out: int | None = None
            input_tokens_total: int = 0
            output_tokens_total: int = 0
            async for event in agent.astream_events(
                {
                    "messages": history_msgs,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "google_credentials": google_credentials or "",
                },
                version="v2",
                config={"recursion_limit": 100},
            ):
                if event["event"] == "on_chat_model_stream":
                    # Only stream tokens from specialist nodes, not the router
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node == "router":
                        continue
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        raw = chunk.content
                        # content can be a list of blocks (tool calls, text) or a plain string
                        if isinstance(raw, list):
                            token = "".join(
                                b.get("text", "") if isinstance(b, dict) else ""
                                for b in raw
                            )
                        else:
                            token = str(raw)
                        if token:
                            ai_content += token
                            await websocket.send_text(json.dumps({
                                "type": "token",
                                "content": token,
                            }))
                elif event["event"] == "on_chat_model_end":
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node != "router":
                        ai_msg_out = event.get("data", {}).get("output", None)
                        if ai_msg_out is not None and hasattr(ai_msg_out, "usage_metadata") and ai_msg_out.usage_metadata:
                            um = ai_msg_out.usage_metadata
                            input_tokens_total += um.get("input_tokens", 0)
                            output_tokens_total += um.get("output_tokens", 0)
                elif event["event"] == "on_chain_end" and event.get("name") == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    model_used_out = output.get("model_used", "") or model_used_out
                    routing_score_out = output.get("routing_score", routing_score_out)
                    # Only use on_chain_end content as a fallback when streaming
                    # produced nothing (non-streaming models like Ollama).
                    # NEVER overwrite content already accumulated via token streaming —
                    # the last message may be a ToolMessage or an AIMessage with
                    # content=None/="" (sanitized for Mistral), which would wipe the
                    # visible response with an empty string.
                    if not ai_content:
                        msgs = output.get("messages", [])
                        # Walk backwards to find the last AIMessage with real text
                        for _msg in reversed(msgs):
                            if not isinstance(_msg, AIMessage):
                                continue
                            raw = _msg.content
                            if raw is None:
                                continue
                            if isinstance(raw, list):
                                _candidate = "".join(
                                    b.get("text", "") if isinstance(b, dict) else ""
                                    for b in raw
                                )
                            else:
                                _candidate = str(raw)
                            if _candidate and _candidate not in ("None", ""):
                                ai_content = _candidate
                                break

            # Restore real values in the response
            ai_content = sf.deanonymize(ai_content)

            async with async_session() as db:
                ai_msg = Message(
                    conversation_id=conversation_id, role="assistant", content=ai_content
                )
                db.add(ai_msg)
                # Touch updated_at so the conversation floats to the top of recent list
                from datetime import datetime, timezone
                conv_row = await db.get(Conversation, conversation_id)
                if conv_row:
                    conv_row.updated_at = datetime.now(timezone.utc)
                await db.commit()

            memory = get_memory_manager()
            await memory.store_interaction(
                user_msg=user_content,
                assistant_msg=ai_content,
                user_id=user_id,
                conversation_id=str(conversation_id),
            )

            payload: dict = {
                "type": "message",
                "role": "assistant",
                "content": ai_content,
                "conversation_id": conversation_id,
            }
            if model_used_out:
                payload["model_used"] = model_used_out
            if routing_score_out is not None:
                payload["routing_score"] = routing_score_out
            await websocket.send_text(json.dumps(payload))

            # ── Log usage for analytics ─────────────────────────────────────────
            if model_used_out:
                try:
                    from app.services.analytics_service import log_usage
                    # model_used_out is "llm:anthropic/claude-haiku-..." or "slm:qwen2.5:3b"
                    _parts = model_used_out.split(":", 1)
                    _type = _parts[0]  # "llm" or "slm"
                    _rest = _parts[1] if len(_parts) > 1 else model_used_out
                    if "/" in _rest:
                        _provider, _model = _rest.split("/", 1)
                    else:
                        _provider, _model = ("ollama" if _type == "slm" else "unknown"), _rest
                    asyncio.create_task(log_usage(
                        user_id=user_id,
                        model=_model,
                        provider=_provider,
                        input_tokens=input_tokens_total,
                        output_tokens=output_tokens_total,
                        conversation_id=str(conversation_id) if conversation_id else None,
                        channel="web",
                    ))
                except Exception:
                    pass  # analytics non-critical

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for user %s", user_id)
    except Exception as e:
        logger.error(
            "WebSocket error for user %s: %s", user_id, str(e), exc_info=True
        )
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "Une erreur interne s'est produite. Veuillez réessayer.",
            }))
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

        prefs_prompt = (
            "À partir de cette conversation, identifie les préférences de communication "
            "et comportements récurrents de l'utilisateur : ton préféré, niveau de détail "
            "souhaité, sujets de prédilection, façon de formuler ses demandes, préférences "
            "de format de réponse, utilisation de l'humour, rythme d'interaction, etc.\n"
            "Réponds UNIQUEMENT avec un tableau JSON de phrases courtes décrivant ses "
            "préférences, une par entrée. Exemple :\n"
            '["L\'utilisateur préfère des réponses courtes et directes", '
            '"Il apprécie l\'humour léger dans les échanges", '
            '"Il préfère le tutoiement"]\n'
            "Retourne [] si aucune préférence n'est clairement identifiable.\n\n"
            f"Conversation :\n{transcript}"
        )

        # Run all 3 LLM calls concurrently to minimise latency
        summary_resp, facts_resp, prefs_resp = await asyncio.gather(
            llm.ainvoke([{"role": "user", "content": summary_prompt}]),
            llm.ainvoke([{"role": "user", "content": facts_prompt}]),
            llm.ainvoke([{"role": "user", "content": prefs_prompt}]),
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

        # ── 3. Store individual user preferences ─────────────────────────
        raw_prefs = prefs_resp.content.strip()
        if "```" in raw_prefs:
            raw_prefs = raw_prefs.split("```")[1].lstrip("json").strip()
        try:
            prefs = _json.loads(raw_prefs)
        except (_json.JSONDecodeError, ValueError):
            prefs = []

        if isinstance(prefs, list):
            pref_count = 0
            for pref in prefs[:8]:  # safety cap
                if isinstance(pref, str) and len(pref) > 10:
                    await memory.store_preference(
                        preference=pref,
                        user_id=user_id,
                    )
                    pref_count += 1
            if pref_count:
                logger.info(
                    "Stored %d preference(s) from conversation %s",
                    pref_count,
                    conversation_id,
                )

    except Exception as exc:
        logger.warning("Failed to summarize conversation %s: %s", conversation_id, exc)
