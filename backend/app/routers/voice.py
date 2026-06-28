# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/voice.py
# @brief      WebSocket endpoint for voice conversations (/ws/voice)
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
"""WebSocket endpoint for voice conversations (/ws/voice).

Protocol
--------
Client connects, sends a JWT handshake (same as chat.py), then exchanges
JSON control messages:

Inbound (client -> server):
  {"type": "audio", "data": "<base64>", "format": "webm"}
  {"type": "text",  "content": "..."}
  {"type": "stop"}

Outbound (server -> client):
  {"type": "config",    ...}              — voice settings on connect
  {"type": "transcript","text": "..."}    — STT result
  {"type": "start",     "conversation_id": "..."}
  {"type": "token",     "content": "..."}
  {"type": "message",   "role":"assistant", "content":"...", "conversation_id":"..."}
  {"type": "tts_audio", "data": "<base64>", "format": "mp3"}
  {"type": "error",     "content": "..."}
  {"type": "stopped"}
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
from sqlalchemy import select

from app.agent.routing import CHAT_RECURSION_LIMIT
from app.auth.jwt import decode_token
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.routers.chat import get_agent
from app.services.background_tasks import spawn
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter
from app.services import ws_registry
from app.services.voice_service import (
    get_voice_config,
    voice_system_hint,
    DEFAULT_VOICE,
    DEFAULT_RATE,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-conversation security filters — registre PARTAGÉ avec chat.py et
# tool_node (B-7, revue 2026-06-10). voice.py avait son propre dict local :
# le vault PII du canal vocal était DIFFÉRENT de celui que tool_node
# utilise pour dé-anonymiser les arguments d'outils → un tool_call vocal
# avec [EMAIL_0] partait avec le placeholder littéral (le bug Gmail du
# 2026-05-07, version voix). Une seule source de vérité désormais.
from app.services.conversation_filters import (
    discard_filter as _discard_filter,
    get_filter as _get_filter,
)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _anonymized_history(history_rows, sf: SecurityFilter) -> list:
    """History rows → LangChain messages, PII-anonymized BOTH ways.

    Assistant messages are STORED deanonymized (real values, for display) —
    so they must be re-anonymized before being fed back to the LLM, exactly
    like chat.py does since fix #55. The voice channel skipped that step
    until 2026-06-10 (revue multi-utilisateurs, constat B-13): real emails /
    phones from past assistant replies leaked to cloud LLMs on every voice
    turn. The last row (the current user message) is excluded — the caller
    appends it separately with the voice hint.
    """
    msgs: list = []
    for row in history_rows[:-1]:
        if row.role == "user":
            msgs.append(HumanMessage(content=sf.anonymize(row.content)))
        elif row.role == "assistant":
            # ner_detection=False : contenu machine (cf. chat.py).
            msgs.append(AIMessage(content=sf.anonymize(row.content, ner_detection=False)))
    return msgs


async def _transcribe_audio(audio_b64: str, audio_format: str = "webm") -> str:
    """Transcribe base64-encoded audio to text using faster-whisper."""
    from app.routers.transcribe import TRANSCRIBE_SEMAPHORE, _transcribe_sync

    audio_bytes = base64.b64decode(audio_b64)
    with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        async with TRANSCRIBE_SEMAPHORE:
            text, _info = await asyncio.to_thread(_transcribe_sync, tmp_path)
        return text
    finally:
        os.unlink(tmp_path)


async def _generate_tts(text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> bytes:
    """Generate TTS audio and return raw mp3 bytes."""
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed — TTS unavailable")
        return b""

    from app.routers.tts import _strip_markdown

    clean = _strip_markdown(text)
    if not clean:
        return b""
    communicate = edge_tts.Communicate(clean, voice, rate=rate)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/voice")
async def websocket_voice(websocket: WebSocket):
    await websocket.accept()

    # ── JWT handshake (same pattern as chat.py) ──────────────────────────
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
            select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

    ws_registry.register(user_id, websocket)

    conversation_id: str | None = None

    # Google credentials (SEC-1 — same pattern as chat.py)
    import time as _time
    from app.services.credential_store import get_credential_store as _get_cred_store

    _cred_store = _get_cred_store()
    _cred_store.set(user_id, user.google_credentials)
    _google_creds_ts: float = _time.monotonic()
    _CREDS_TTL = 300.0

    # Send voice config on connect
    try:
        await websocket.send_text(json.dumps({
            "type": "config",
            **get_voice_config(),
        }))
    except Exception:
        pass

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.warning("Malformed JSON from user %s (voice, ignored): %.200s", user_id, raw_data)
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Message invalide — JSON mal formé.",
                }))
                continue

            msg_type = msg.get("type", "")

            # ── Stop signal ──────────────────────────────────────────────
            if msg_type == "stop":
                continue

            # ── Determine user text ──────────────────────────────────────
            user_text: str = ""

            if msg_type == "audio":
                audio_b64 = msg.get("data", "")
                audio_format = msg.get("format", "webm")
                if not audio_b64:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": "Données audio manquantes.",
                    }))
                    continue
                try:
                    user_text = await _transcribe_audio(audio_b64, audio_format)
                except Exception as exc:
                    logger.error("Transcription failed: %s", exc, exc_info=True)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": "Échec de la transcription audio.",
                    }))
                    continue

                if not user_text:
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": "",
                    }))
                    continue

                # Send transcription back to client
                await websocket.send_text(json.dumps({
                    "type": "transcript",
                    "text": user_text,
                }))

            elif msg_type == "text":
                user_text = msg.get("content", "").strip()
                if not user_text:
                    continue
            else:
                continue

            # ── Update conversation_id from message if provided ──────────
            conversation_id = msg.get("conversation_id") or conversation_id

            # ── Refresh google credentials every 5 min ───────────────────
            now = _time.monotonic()
            if now - _google_creds_ts > _CREDS_TTL:
                async with async_session() as _creds_db:
                    _u = await _creds_db.execute(select(User).where(User.id == user_id))
                    _fresh = _u.scalar_one_or_none()
                    if _fresh:
                        _cred_store.set(user_id, _fresh.google_credentials)
                _google_creds_ts = now

            # ── Persist user message ─────────────────────────────────────
            async with async_session() as db:
                if not conversation_id:
                    conv = Conversation(user_id=user_id, title=user_text[:50])
                    db.add(conv)
                    await db.flush()
                    conversation_id = str(conv.id)
                    await db.commit()

                user_msg = Message(
                    conversation_id=conversation_id, role="user", content=user_text
                )
                db.add(user_msg)
                await db.commit()

            # ── Anonymize ────────────────────────────────────────────────
            sf = _get_filter(conversation_id)
            clean_content = sf.anonymize(user_text)

            # ── Load conversation history ────────────────────────────────
            _MAX_HISTORY = 40
            async with async_session() as db:
                hist_result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(_MAX_HISTORY + 2)
                )
                history_rows = list(reversed(hist_result.scalars().all()))

            history_msgs = _anonymized_history(history_rows, sf)[-_MAX_HISTORY:]

            # Inject voice-optimized system hint into the user message
            voice_hint = voice_system_hint()
            augmented_content = f"[{voice_hint}]\n\n{clean_content}"
            history_msgs.append(HumanMessage(content=augmented_content))

            # PII sovereignty — see chat.py for full rationale.
            try:
                from app.services.sovereignty import SOVEREIGNTY_STRICT
                SOVEREIGNTY_STRICT.set(bool(getattr(user, "sovereignty_strict", False)))
            except Exception as _sov_exc:  # noqa: BLE001
                logger.debug("sovereignty ContextVar set skipped: %s", _sov_exc)

            # ── Run agent ────────────────────────────────────────────────
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
            tools_called: list[str] = []

            # Stop-signal watcher (same pattern as chat.py)
            stop_event = asyncio.Event()

            async def _watch_for_stop() -> None:
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                        inner = json.loads(raw)
                        if inner.get("type") == "stop":
                            stop_event.set()
                            return
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        stop_event.set()
                        return

            # A-6b — budget LLM quotidien par user (même garde que chat.py)
            from app.services.budget_guard import check_user_budget
            _budget_refusal = await check_user_budget(user_id)
            if _budget_refusal:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": _budget_refusal,
                }))
                continue

            # B-15 — même cap de runs concurrents par user que chat.py
            from app.services.run_gate import get_user_run_semaphore
            _run_sem = get_user_run_semaphore(user_id)
            await _run_sem.acquire()
            watcher_task = asyncio.create_task(_watch_for_stop())
            try:
                async for event in agent.astream_events(
                    {
                        "messages": history_msgs,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                    },
                    version="v2",
                    config={"recursion_limit": CHAT_RECURSION_LIMIT},
                ):
                    if stop_event.is_set():
                        break
                    if event["event"] == "on_chat_model_stream":
                        node = event.get("metadata", {}).get("langgraph_node", "")
                        if node == "router":
                            continue
                        chunk = event["data"]["chunk"]
                        if hasattr(chunk, "content") and chunk.content:
                            raw_tok = chunk.content
                            if isinstance(raw_tok, list):
                                token = "".join(
                                    b.get("text", "") if isinstance(b, dict) else ""
                                    for b in raw_tok
                                )
                            else:
                                token = str(raw_tok)
                            if token:
                                ai_content += token
                                # B-14 — même garde anti-backpressure que
                                # chat.py (client lent/zombie ≠ stream gelé).
                                try:
                                    await asyncio.wait_for(
                                        websocket.send_text(json.dumps({
                                            "type": "token",
                                            "content": token,
                                        })),
                                        timeout=10.0,
                                    )
                                except asyncio.TimeoutError:
                                    raise WebSocketDisconnect(code=1011)
                    elif event["event"] == "on_chat_model_end":
                        node = event.get("metadata", {}).get("langgraph_node", "")
                        if node != "router":
                            ai_msg_out = event.get("data", {}).get("output", None)
                            if ai_msg_out is not None and hasattr(ai_msg_out, "usage_metadata") and ai_msg_out.usage_metadata:
                                um = ai_msg_out.usage_metadata
                                input_tokens_total += um.get("input_tokens", 0)
                                output_tokens_total += um.get("output_tokens", 0)
                    elif event["event"] == "on_tool_start":
                        tool_name = event.get("name", "")
                        if tool_name:
                            tools_called.append(tool_name)
                            await websocket.send_text(json.dumps({
                                "type": "tool_start",
                                "tool": tool_name,
                            }))
                    elif event["event"] == "on_tool_end":
                        tool_name = event.get("name", "")
                        await websocket.send_text(json.dumps({
                            "type": "tool_end",
                            "tool": tool_name,
                        }))
                    elif event["event"] == "on_chain_end" and event.get("name") == "LangGraph":
                        output = event.get("data", {}).get("output", {})
                        model_used_out = output.get("model_used", "") or model_used_out
                        routing_score_out = output.get("routing_score", routing_score_out)
                        if not ai_content:
                            msgs = output.get("messages", [])
                            for _msg in reversed(msgs):
                                if not isinstance(_msg, AIMessage):
                                    continue
                                raw_c = _msg.content
                                if raw_c is None:
                                    continue
                                if isinstance(raw_c, list):
                                    _candidate = "".join(
                                        b.get("text", "") if isinstance(b, dict) else ""
                                        for b in raw_c
                                    )
                                else:
                                    _candidate = str(raw_c)
                                if _candidate and _candidate not in ("None", ""):
                                    ai_content = _candidate
                                    break
            finally:
                _run_sem.release()  # B-15 — libère le slot de run du user
                stop_event.set()
                watcher_task.cancel()
                try:
                    await watcher_task
                except asyncio.CancelledError:
                    pass

            was_stopped = stop_event.is_set() and not ai_content

            if was_stopped:
                await websocket.send_text(json.dumps({"type": "stopped"}))
                continue

            # Restore real values
            ai_content = sf.deanonymize(ai_content)

            # Enforce user preferences (strip emojis/markdown if asked)
            try:
                from app.services.response_filter import apply_user_preferences
                from app.services.memory_manager import get_memory_manager as _gmm
                _prefs = await _gmm().get_user_preferences(user_id)
                ai_content = apply_user_preferences(ai_content, _prefs)
            except Exception:
                pass

            if stop_event.is_set() and ai_content:
                ai_content = ai_content.rstrip()

            # ── Persist assistant message ────────────────────────────────
            async with async_session() as db:
                ai_msg = Message(
                    conversation_id=conversation_id, role="assistant", content=ai_content
                )
                db.add(ai_msg)
                from datetime import datetime, timezone
                conv_row = await db.get(Conversation, conversation_id)
                if conv_row:
                    conv_row.updated_at = datetime.now(timezone.utc)
                await db.commit()

            # ── Store in long-term memory ────────────────────────────────
            memory = get_memory_manager()
            await memory.store_interaction(
                user_msg=user_text,
                assistant_msg=ai_content,
                user_id=user_id,
                conversation_id=str(conversation_id),
            )

            # ── Send complete message ────────────────────────────────────
            msg_payload: dict = {
                "type": "message",
                "role": "assistant",
                "content": ai_content,
                "conversation_id": conversation_id,
            }
            if model_used_out:
                msg_payload["model_used"] = model_used_out
            if routing_score_out is not None:
                msg_payload["routing_score"] = routing_score_out
            await websocket.send_text(json.dumps(msg_payload))

            # ── Generate and send TTS audio ──────────────────────────────
            try:
                tts_bytes = await _generate_tts(ai_content)
                if tts_bytes:
                    tts_b64 = base64.b64encode(tts_bytes).decode("ascii")
                    await websocket.send_text(json.dumps({
                        "type": "tts_audio",
                        "data": tts_b64,
                        "format": "mp3",
                    }))
            except Exception as tts_exc:
                logger.warning("TTS generation failed: %s", tts_exc)
                # Non-critical — the text message was already sent

            # ── Analytics ────────────────────────────────────────────────
            if model_used_out:
                try:
                    from app.services.analytics_service import log_usage

                    _parts = model_used_out.split(":", 1)
                    _type = _parts[0]
                    _rest = _parts[1] if len(_parts) > 1 else model_used_out
                    if "/" in _rest:
                        _provider, _model = _rest.split("/", 1)
                    else:
                        _provider, _model = ("ollama" if _type == "slm" else "unknown"), _rest
                    _skill = (
                        max(set(tools_called), key=tools_called.count)
                        if tools_called else None
                    )
                    spawn(log_usage(
                        user_id=user_id,
                        model=_model,
                        provider=_provider,
                        input_tokens=input_tokens_total,
                        output_tokens=output_tokens_total,
                        conversation_id=str(conversation_id) if conversation_id else None,
                        skill_used=_skill,
                        channel="voice",
                    ))
                except Exception:
                    pass  # analytics non-critical

    except WebSocketDisconnect:
        logger.debug("Voice WebSocket disconnected for user %s", user_id)
    except Exception as e:
        logger.error("Voice WebSocket error for user %s: %s", user_id, str(e), exc_info=True)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "Une erreur interne s'est produite. Veuillez réessayer.",
            }))
        except Exception:
            pass
    finally:
        ws_registry.unregister(user_id, websocket)
        # Summarize conversation into long-term memory on disconnect
        if conversation_id:
            from app.routers.chat import _summarize_conversation
            spawn(_summarize_conversation(conversation_id, user_id))
        _discard_filter(conversation_id) if conversation_id else None
