# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/chat.py
# @brief      Chat WebSocket and REST endpoints
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
import asyncio
import base64
import json
import logging
import time
import uuid
from pathlib import Path

# orjson is 2-5× faster than stdlib json for serialization on the WS hot path.
# Fallback to stdlib if not available for any reason.
try:
    import orjson as _orjson
    def _dumps(obj: dict) -> str:
        return _orjson.dumps(obj).decode("utf-8")
    def _loads(data: str) -> dict:
        return _orjson.loads(data)
except ImportError:
    _dumps = json.dumps
    _loads = json.loads

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
from sqlalchemy import select

from app.agent.graph import build_agent_graph
from app.agent.routing import CHAT_RECURSION_LIMIT
from app.auth.jwt import decode_token
from app.database import async_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.background_tasks import spawn
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter
from app.services import ws_registry

logger = logging.getLogger(__name__)

router = APIRouter()

# One graph instance shared across all connections
_agent_graph = None

# One SecurityFilter per conversation (bounded LRU to prevent unbounded memory growth)
from collections import OrderedDict


# Per-conversation SecurityFilter registry — moved to a shared services
# module so tool_node (nodes.py) can deanonymize tool args using the same
# vault as the user-input anonymization. See services/conversation_filters.py.
from app.services.conversation_filters import (
    discard_filter as _discard_filter,
    get_filter as _get_filter,
)


class _FiltersProxy:
    """Tiny shim so legacy ``_filters.setdefault(...)`` and
    ``_filters.pop(...)`` calls keep working while we migrate to the
    dedicated registry module."""

    def setdefault(self, conversation_id: str, _default=None):
        return _get_filter(conversation_id)

    def get(self, conversation_id: str, default=None):
        # C0 (audit 16/07 P0) : factory.py appelait ``get`` qui n'existait
        # pas — AttributeError avalée → couture PII morte. Même sémantique
        # get-or-create que le registre (un filtre vide désanonymise no-op).
        return _get_filter(conversation_id)

    def pop(self, conversation_id: str, default=None):
        _discard_filter(conversation_id)
        return default


_filters = _FiltersProxy()


def get_agent():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


async def _notify_turn_done_offline(
    user_id: str, conversation_id: str | None, ai_content: str,
) -> None:
    """Push « c'est prêt » quand le tour s'est terminé sans client connecté.

    Incident 24/07 : une traduction de 2 h 52 a abouti alors que l'onglet était
    fermé depuis longtemps — la réponse était en base, mais rien ne le disait.
    Best-effort intégral (pas de NTFY_URL → no-op silencieux) ; le corps ne
    contient qu'un extrait court, jamais la conversation entière.
    """
    try:
        extract = " ".join((ai_content or "").split())[:180]
        from app.services.learning.candidate_notify import _push
        await _push(
            "Ely - ta demande est terminee",
            (f"{extract}…\n\n" if extract else "")
            + "Rouvre Ely pour voir la réponse complète.",
            tags="white_check_mark",
        )
        logger.info(
            "chat: push hors-ligne envoyé (user=%s conv=%s)",
            user_id[:8] if user_id else "?", (conversation_id or "?")[:8],
        )
    except Exception as exc:  # noqa: BLE001 — la notification ne casse rien
        logger.debug("chat: push hors-ligne ignoré (%s)", exc)


async def _assert_owns_conversation(db, conversation_id: str, user_id: str) -> bool:
    """True iff the conversation exists AND belongs to ``user_id``.

    WS counterpart of ``conversations._get_owned_conversation`` (IDOR fix
    A-1, revue 2026-06-10) — here the caller closes the socket with code
    4003 instead of raising HTTPException. "Not found" and "owned by
    someone else" are deliberately indistinguishable so the close never
    confirms that a conversation id exists.
    """
    result = await db.execute(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


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
        data = _loads(handshake)
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

    # Load google_credentials into the server-side store (SEC-1 — credentials
    # must never travel through the agent graph state or appear in logs).
    # We keep a local TTL and refresh from DB every 5 min (PERF-1).
    import time as _time
    from app.services.credential_store import get_credential_store as _get_cred_store
    _cred_store = _get_cred_store()
    _cred_store.set(user_id, user.google_credentials)
    _google_creds_ts: float = _time.monotonic()
    _CREDS_TTL = 300.0  # seconds

    # ── Client parti ≠ stop demandé (incident 24/07) ─────────────────────────
    # Une tâche longue (traduction d'un PDF de 395 pages : 2 h 52) survit
    # rarement à l'onglet de l'utilisateur. Jusqu'ici, la disparition du client
    # levait le MÊME drapeau qu'un clic « stop » : le tour était tué à la
    # première occasion — le travail réussi partait à la poubelle et Ely
    # ignorait son propre succès. Désormais le tour CONTINUE côté serveur
    # (il reste borné par recursion_limit + les échéances LLM), la réponse
    # finale est persistée, et l'utilisateur est notifié par push.
    client_gone = asyncio.Event()

    async def _ws_send(text: str) -> bool:
        """Envoi best-effort. False = personne au bout du fil (on continue)."""
        if client_gone.is_set():
            return False
        try:
            await websocket.send_text(text)
            return True
        except (RuntimeError, WebSocketDisconnect) as _send_exc:
            client_gone.set()
            logger.info(
                "chat: client parti pendant le tour — livraison différée "
                "(user=%s): %s", user_id, _send_exc,
            )
            return False

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = _loads(data)
            except json.JSONDecodeError:
                logger.warning("Malformed JSON from user %s (ignored): %.200s", user_id, data)
                await _ws_send(_dumps({
                    "type": "error",
                    "content": "Message invalide — JSON mal formé.",
                }))
                continue

            # Stop signal with no agent running. The user clicked stop after
            # the agent had already finished — a common race when React batches
            # the `isLoading=false` flip after the final "message" event and
            # the next keystroke catches the stale truthy value. Without an
            # explicit acknowledgement, the frontend stays stuck thinking the
            # agent is still running (red square locked). Send a `"done"`
            # event so the frontend can force-reset its loading state.
            if msg.get("type") == "stop":
                await _ws_send(_dumps({"type": "done"}))
                continue

            user_content = msg.get("content", "")

            # IDOR fix A-1 (revue 2026-06-10) — a client-supplied
            # conversation_id must belong to the authenticated user,
            # otherwise any logged-in user could write into (and have the
            # agent read from) another user's conversation by replaying
            # its UUID. Validate at the single ingestion point, BEFORE
            # assigning the loop variable: every downstream use (slash
            # commands, message persistence, toolset profile, summarize
            # on disconnect) then only ever sees an owned or
            # server-created id.
            _client_conv_id = msg.get("conversation_id")
            if _client_conv_id and _client_conv_id != conversation_id:
                async with async_session() as db:
                    _owned = await _assert_owns_conversation(
                        db, str(_client_conv_id), user_id
                    )
                if not _owned:
                    logger.warning(
                        "WS chat: user %s sent conversation_id %s they don't "
                        "own — closing (4003)",
                        user_id, _client_conv_id,
                    )
                    await websocket.close(code=4003, reason="Conversation not found")
                    return
            conversation_id = _client_conv_id or conversation_id

            # Enrich content with attached file paths so the agent can process them
            attachments = msg.get("attachments") or []
            if attachments:
                file_lines = []
                for a in attachments:
                    if not a.get("path"):
                        continue
                    fname = a.get("filename", "?")
                    fpath = a.get("path", "?")
                    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    if ext == "pdf":
                        hint = " [PDF — utilise pdf_analyze_with_vision pour analyser la mise en page, les tableaux et les données structurées]"
                    elif ext in ("jpg", "jpeg", "png", "gif", "webp"):
                        hint = " [Image — utilise vision_analyze_image]"
                    else:
                        hint = ""
                    file_lines.append(f"• {fname} → {fpath}{hint}")
                if file_lines:
                    user_content = f"{user_content}\n\n📎 Fichiers joints :\n" + "\n".join(file_lines)
                    user_content = user_content.strip()

            # Screen capture — save base64 PNG to uploads dir, inject path into content
            screen_b64 = msg.get("screen_capture")
            if screen_b64:
                try:
                    upload_dir = Path(__file__).parents[2] / "uploads" / user_id
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    screen_path = upload_dir / f"screen_{uuid.uuid4().hex[:8]}.png"
                    screen_path.write_bytes(base64.b64decode(screen_b64))
                    user_content = (
                        f"{user_content}\n\n📸 Capture d'écran partagée → {screen_path}"
                    ).strip()
                    logger.debug("Screen capture saved to %s", screen_path)
                except Exception as exc:
                    logger.warning("Failed to save screen capture: %s", exc)

            # Refresh google_credentials in the store every 5 min
            now = _time.monotonic()
            if now - _google_creds_ts > _CREDS_TTL:
                async with async_session() as _creds_db:
                    _u = await _creds_db.execute(select(User).where(User.id == user_id))
                    _fresh = _u.scalar_one_or_none()
                    if _fresh:
                        _cred_store.set(user_id, _fresh.google_credentials)
                _google_creds_ts = now

            # ── Slash command handler (must run BEFORE persisting + agent) ──
            # Currently only `/profile [name]` (Hermes Chantier 1). Returns
            # immediately with a system-style assistant message and skips
            # the agent run.
            _stripped = (user_content or "").strip()
            if _stripped.startswith("/profile"):
                _parts = _stripped.split(maxsplit=1)
                from app.agent.toolset_profiles import (
                    list_profiles, is_valid_profile, DEFAULT_PROFILE,
                )
                _reply: str
                if len(_parts) == 1:
                    # Show current + available
                    _current = "(non défini)"
                    if conversation_id:
                        async with async_session() as _pdb:
                            _conv = await _pdb.get(Conversation, conversation_id)
                            if _conv and _conv.toolset_profile:
                                _current = _conv.toolset_profile
                    _reply = (
                        f"Profil actuel : **{_current}**\n"
                        f"Profils disponibles : {', '.join(list_profiles())}\n"
                        f"Pour changer : `/profile <nom>`"
                    )
                else:
                    _new = _parts[1].strip()
                    if not is_valid_profile(_new):
                        _reply = (
                            f"❌ Profil inconnu : `{_new}`. "
                            f"Disponibles : {', '.join(list_profiles())}"
                        )
                    else:
                        if not conversation_id:
                            # Need a conversation row first — create empty
                            async with async_session() as _pdb:
                                _conv = Conversation(
                                    user_id=user_id,
                                    title=f"/profile {_new}",
                                    toolset_profile=_new,
                                )
                                _pdb.add(_conv)
                                await _pdb.flush()
                                conversation_id = str(_conv.id)
                                await _pdb.commit()
                        else:
                            async with async_session() as _pdb:
                                _conv = await _pdb.get(Conversation, conversation_id)
                                if _conv:
                                    _conv.toolset_profile = _new
                                    await _pdb.commit()
                        # Hermes Chantier 2 — toolset profile changed.
                        # Invalidate the system prompt cache so the next turn
                        # rebuilds with the new profile in mind. (Today the
                        # cacheable text doesn't depend on the profile, but
                        # this guards against future profile-specific text.)
                        try:
                            from app.services.system_prompt_cache import (
                                invalidate as _spc_invalidate,
                            )
                            _spc_invalidate(conversation_id)
                        except Exception:
                            pass
                        _reply = f"✅ Profil de cette conversation : **{_new}**"
                # Echo back to the user as an assistant message (no DB persist
                # needed — slash commands don't need to live in history)
                from datetime import datetime as _dt2, timezone as _tz2
                await _ws_send(_dumps({
                    "type": "message",
                    "role": "assistant",
                    "content": _reply,
                    "conversation_id": conversation_id,
                    "created_at": _dt2.now(_tz2.utc).isoformat(),
                }))
                continue

            _is_new_conv = False
            async with async_session() as db:
                if not conversation_id:
                    _is_new_conv = True
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

            # ── Toolset profile resolution (Hermes Chantier 1) ─────────────
            # If the conversation has no profile yet (NULL), auto-detect from
            # the current user message and persist. Subsequent turns reuse
            # the same profile — the catalog stays stable for the model.
            # V1 temps 1 — résolution EXTRAITE dans toolset_profiles pour
            # que les canaux et la voix utilisent exactement la même. Trois
            # copies auraient dérivé.
            from app.agent.toolset_profiles import resolve_conversation_profile
            _toolset_profile: str = await resolve_conversation_profile(
                str(conversation_id), user_content or ""
            )

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
                    # Assistant messages are STORED deanonymized (real values,
                    # for display) — so re-anonymize before feeding them back to
                    # the LLM, exactly like the user history above. Without this,
                    # any PII the assistant restated leaked to the model (cloud
                    # incl.) on every subsequent turn.
                    # ner_detection=False : contenu machine — la PII connue
                    # (vault) reste masquée, pas de détection fraîche.
                    history_msgs.append(AIMessage(content=sf.anonymize(row.content, ner_detection=False)))
            # Keep only last _MAX_HISTORY messages to stay within context limits
            history_msgs = history_msgs[-_MAX_HISTORY:]
            history_msgs.append(HumanMessage(content=clean_content))

            # PII sovereignty (2026-06-07) — when the user opted in, force the
            # tier B/C routing to the EU Mistral chain instead of the default
            # cloud provider (DeepSeek). ContextVars propagate per asyncio task,
            # so downstream get_tier_config() in get_llm_for_tier sees the flag
            # for THIS turn only — no cross-user leakage.
            try:
                from app.services.sovereignty import SOVEREIGNTY_STRICT
                SOVEREIGNTY_STRICT.set(bool(getattr(user, "sovereignty_strict", False)))
            except Exception as _sov_exc:  # noqa: BLE001
                logger.debug("sovereignty ContextVar set skipped: %s", _sov_exc)

            agent = get_agent()
            await _ws_send(_dumps({
                "type": "start",
                "conversation_id": conversation_id,
            }))

            ai_content = ""
            # Contenu du tour COURANT du modèle. Réinitialisé à chaque
            # ``on_tool_start`` : ce qui précède un appel d'outil est un
            # "préambule" (raisonnement, et avec GPT-5.5 le script orchestrate
            # complet) redondant avec l'indicateur d'outil affiché à part. À la
            # fin, si des outils ont tourné, on ne garde que ce dernier tour =
            # la vraie réponse (cf. réassignation après la boucle de streaming).
            _answer_content = ""
            model_used_out: str = ""
            routing_score_out: int | None = None
            input_tokens_total: int = 0
            output_tokens_total: int = 0
            tools_called: list[str] = []   # track tool invocations for analytics
            # V2-1 — latence de bout en bout du tour (vague 2). Prise ICI,
            # avant l'invocation du graphe : c'est le temps que l'utilisateur
            # attend réellement, pas celui d'un appel LLM isolé.
            _turn_started_at = time.monotonic()

            # ── Stop-signal watcher ──────────────────────────────────────────────
            # Run a parallel task that listens for {"type":"stop"} from the client
            # while the agent stream is in progress.
            stop_event = asyncio.Event()

            async def _watch_for_stop() -> None:
                while not stop_event.is_set() and not client_gone.is_set():
                    try:
                        raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                        inner = _loads(raw)
                        if inner.get("type") == "stop":
                            stop_event.set()   # geste DÉLIBÉRÉ : on arrête tout
                            return
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        # Le client a disparu (onglet fermé, veille, réseau) —
                        # ce n'est PAS un ordre d'arrêt. On note la déconnexion
                        # et on laisse le tour finir son travail (incident
                        # 24/07 : 2 h 52 de traduction réussie jetées ici).
                        client_gone.set()
                        return

            # A-6b — budget LLM quotidien par user (opt-in,
            # ELY_USER_DAILY_BUDGET_USD ; 0 = désactivé). Refus doux :
            # le message du user est déjà persisté, l'agent ne tourne pas.
            from app.services.budget_guard import check_user_budget
            _budget_refusal = await check_user_budget(user_id)
            if _budget_refusal:
                await _ws_send(_dumps({
                    "type": "error",
                    "content": _budget_refusal,
                }))
                continue

            # B-15 (revue 2026-06-10) — cap de runs agent concurrents par
            # user : au-delà de ELY_MAX_AGENT_RUNS_PER_USER (2), les runs
            # supplémentaires du même user font la queue ici.
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
                    "toolset_profile": _toolset_profile,
                    # google_credentials intentionally omitted — stored server-side
                    # in credential_store, looked up by user_id at tool exec (SEC-1)
                },
                version="v2",
                # Derived from MAX_AGENT_ITERATIONS so force_summary always
                # fires before this hard cap (2026-06-01 fix — see routing.py).
                config={"recursion_limit": CHAT_RECURSION_LIMIT},
              ):
                if stop_event.is_set():
                    break
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
                            _answer_content += token
                            # B-14 (revue 2026-06-10) — un client lent ou
                            # zombie ne doit pas bloquer la consommation du
                            # stream LLM (connexion provider maintenue
                            # ouverte, tokens facturés). Au-delà de 10 s
                            # d'envoi on traite la socket comme morte.
                            try:
                                await asyncio.wait_for(
                                    _ws_send(_dumps({
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
                        # Le contenu déjà streamé sur ce tour était un préambule
                        # menant à cet appel d'outil — on le retire de la réponse
                        # finale (il restera affiché en live jusqu'au tool_start
                        # côté frontend, qui le purge aussi).
                        _answer_content = ""
                        await _ws_send(_dumps({
                            "type": "tool_start",
                            "tool": tool_name,
                        }))
                elif event["event"] == "on_tool_end":
                    tool_name = event.get("name", "")
                    tool_output = event.get("data", {}).get("output", "")
                    # Sprint 2.7 §4.4 — when ``orchestrate`` finishes, its
                    # meta header lists the tools dispatched inside the
                    # sandbox. Add them to ``tools_called`` so the
                    # completion_guard sees the union and doesn't flag a
                    # destructive action driven via the sandbox as
                    # unbacked. (Today the sandbox is read-only — so this
                    # is mostly preparation for V2 — but it's also harmless
                    # for read-only tools.)
                    if tool_name == "orchestrate":
                        try:
                            from app.services.orchestrate_runner import (
                                parse_dispatched_from_result,
                            )
                            _output_str = (
                                tool_output
                                if isinstance(tool_output, str)
                                else getattr(tool_output, "content", "") or ""
                            )
                            _dispatched = parse_dispatched_from_result(_output_str)
                            if _dispatched:
                                tools_called.extend(_dispatched)
                                logger.debug(
                                    "completion_guard: union'd %d sandbox tools "
                                    "from orchestrate result",
                                    len(_dispatched),
                                )
                        except Exception as _orch_parse_exc:
                            logger.debug(
                                "orchestrate tools_dispatched parse skipped: %s",
                                _orch_parse_exc,
                            )
                    # Detect image results from tools (e.g. qrcode_generate, generate_image)
                    _image_payload: dict | None = None
                    if isinstance(tool_output, str) and tool_output.startswith("{"):
                        try:
                            _parsed = _loads(tool_output)
                            if isinstance(_parsed, dict) and _parsed.get("type") == "image":
                                _image_payload = _parsed
                        except (json.JSONDecodeError, ValueError):
                            pass
                    _msg: dict = {"type": "tool_end", "tool": tool_name}
                    if _image_payload:
                        _msg["image"] = _image_payload
                    await _ws_send(_dumps(_msg))
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

            finally:
                _run_sem.release()  # B-15 — libère le slot de run du user
                # Always clean up the stop watcher, whether agent finished or was interrupted
                stop_event.set()
                watcher_task.cancel()
                try:
                    await watcher_task
                except asyncio.CancelledError:
                    pass

            # Hermes Chantier 4 — drain provider.switched events emitted by
            # the FallbackManager during this turn and forward them to the
            # frontend (it can show a discreet toast). We do this AFTER the
            # streaming loop so events fire AFTER the assistant's response
            # text is on screen — the toast lands in context, not before.
            try:
                from app.services.fallback_manager import drain_events as _fb_drain
                if conversation_id:
                    for _ev in _fb_drain(conversation_id):
                        await _ws_send(_dumps(_ev))
            except Exception as _fb_exc:
                logger.debug("fallback.drain_events skipped: %s", _fb_exc)

            was_stopped = stop_event.is_set() and not ai_content

            # If interrupted with no content, notify client and skip saving
            if was_stopped:
                # 2026-07-18 — this path also fires when the CLIENT vanished
                # (network cut → the watcher's receive_text() raised →
                # stop_event set). Sending on the closed socket raises
                # RuntimeError ("Unexpected ASGI message 'websocket.send',
                # after sending 'websocket.close'") which the generic handler
                # below logged as ERROR + traceback. Nobody is listening —
                # guard the pair so ERROR logs stay meaningful.
                try:
                    await _ws_send(_dumps({"type": "stopped"}))
                    # Always emit `"done"` to flip isLoading=false on the frontend
                    # (paired with "stopped" so the UI handles either reliably).
                    await _ws_send(_dumps({"type": "done"}))
                except (RuntimeError, WebSocketDisconnect) as _stop_send_exc:
                    logger.debug(
                        "stopped/done events skipped — socket already closed "
                        "(user=%s): %s", user_id, _stop_send_exc,
                    )
                continue

            # Si des outils ont tourné, ne garder que le contenu du DERNIER tour
            # (la réponse de synthèse), pas les préambules des tours qui
            # appelaient un outil — c'est là que GPT-5.5 recopiait son script
            # orchestrate dans la réponse visible. Filet de sécurité : si le
            # dernier tour n'a produit aucun texte (rare — le modèle finit sur un
            # appel d'outil sans synthèse), on retombe sur le contenu complet
            # plutôt que d'afficher un message vide.
            if tools_called and _answer_content.strip():
                ai_content = _answer_content

            # Restore real values in the response
            ai_content = sf.deanonymize(ai_content)

            # Enforce user preferences as a safety net (strip emojis / markdown
            # if the user has asked for it). Small LLMs often fail on negative
            # constraints like "do not use emojis" even when the rule is in the
            # system prompt — this deterministic post-filter is the reliable
            # fallback.
            try:
                from app.services.response_filter import apply_user_preferences
                _mm = get_memory_manager()
                _prefs = await _mm.get_user_preferences(user_id)
                ai_content = apply_user_preferences(ai_content, _prefs)
            except Exception as _filter_exc:
                logger.debug("Response filter skipped: %s", _filter_exc)

            # ── Anti self-dialogue (audit 2026-05-07) ──────────────────────
            # Ministral 3 8B and other small instruct LLMs sometimes continue
            # the conversation past their own turn ("C'est ça ? \n Oui exactement.
            # \n Toi… / Moi…"). Stop tokens at the LLM provider level catch most
            # cases but a few slip through. Trim them as the last response-text
            # post-processor before media_router and DB persistence.
            try:
                from app.services.anti_self_dialogue import trim_self_dialogue
                ai_content, _trimmed = trim_self_dialogue(ai_content)
                if _trimmed:
                    logger.warning(
                        "anti_self_dialogue: trimmed self-dialogue from response (user=%s)",
                        user_id,
                    )
            except Exception as _asd_exc:
                logger.debug("anti_self_dialogue skipped: %s", _asd_exc)

            # ── Media router (Hermes-style sentinel parser, audit 2026-05-06) ──
            # Extract MEDIA:<path> sentinels and bare references to whitelisted
            # attachment dirs. This catches the case where the LLM mentioned
            # a screenshot file but forgot to call gmail_send_with_local_attachment
            # or drive_create_file — at least the user gets the file inline.
            _extracted_attachments: list[dict] = []
            try:
                from app.services.media_router import extract_media
                _media_result = extract_media(ai_content)
                ai_content = _media_result.cleaned_text
                _extracted_attachments = _media_result.attachments
                if _extracted_attachments:
                    logger.warning(
                        "media_router: extracted %d attachment(s) from response (user=%s)",
                        len(_extracted_attachments), user_id,
                    )
            except Exception as _media_exc:
                logger.warning("media_router skipped: %s", _media_exc)

            # ── Anti-hallucination completion guard (incident 2026-05-17) ──
            # After 4-5 cycles of "user asks delete → tool_call → tool_result
            # → assistant 'supprimé'", every LLM (DeepSeek v4-flash, Mistral
            # Small 4, etc.) starts shortcutting: it outputs the final
            # 'supprimé' text WITHOUT the tool_call in between. Nothing is
            # actually deleted but the user thinks the action happened.
            # This is the worst-class bug for ELY (silent break of the HITL
            # promise), so we gate hard server-side regardless of the model.
            #
            # C3c — the verification itself now lives in the shared
            # OutcomeVerifier (services/output_verifier.py): it runs the same
            # completion guard, logs, and records the learning signal, so
            # channels / scheduler / voice can verify identically before
            # delivery. The web surface keeps its own `hallucination_blocked`
            # websocket event on top of the returned verdict (UI-only).
            try:
                from app.services.output_verifier import verify_outcome
                _verified = verify_outcome(
                    ai_content,
                    tools_invoked=tools_called,
                    surface="web",
                    # 2026-05-23 — pass the user's last message so the guard
                    # recognises memory-recall questions ("qu'as-tu enregistré
                    # sur X ?") and bypasses the false positive otherwise
                    # triggered by the assistant's honest reply.
                    user_message=user_content,
                    locale="fr",
                    user_id=user_id,
                    conversation_id=conversation_id,
                    model_used=model_used_out or "unknown",
                )
                if _verified.blocked:
                    # Surface to the frontend so the UI can show a red badge
                    # next to the assistant message (and so a future analytics
                    # event collector can count occurrences per model/tier).
                    try:
                        await _ws_send(_dumps({
                            "type": "hallucination_blocked",
                            "reason": _verified.verdict.reason,
                            "matched_patterns": _verified.verdict.matched_patterns,
                            "tools_in_turn": _verified.verdict.tools_invoked,
                        }))
                    except Exception as _wse:
                        logger.debug("hallucination_blocked event skipped: %s", _wse)
                # Replace the lying content with the honest warning (or keep the
                # original text untouched when nothing was blocked). Persisted
                # as-is so the conversation history shows the incident
                # (auditability) and the user can reference it later in support.
                ai_content = _verified.content
            except Exception as _guard_exc:
                # Never let the guard itself break the response delivery.
                logger.warning("completion_guard skipped: %s", _guard_exc)

            # If interrupted but partial content exists, send it as a normal message
            if stop_event.is_set() and ai_content:
                ai_content = ai_content.rstrip() + " …"

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

            # J4 — replace the naive ``user_content[:50]`` title with a concise
            # LLM-generated one after the first exchange (best-effort, once).
            if _is_new_conv:
                spawn(_maybe_generate_title(
                    conversation_id, user_id, user_content, ai_content,
                ))

            memory = get_memory_manager()
            await memory.store_interaction(
                user_msg=user_content,
                assistant_msg=ai_content,
                user_id=user_id,
                conversation_id=str(conversation_id),
            )

            from datetime import datetime as _dt, timezone as _tz
            payload: dict = {
                "type": "message",
                "role": "assistant",
                "content": ai_content,
                "conversation_id": conversation_id,
                "created_at": _dt.now(_tz.utc).isoformat(),
            }
            if model_used_out:
                payload["model_used"] = model_used_out
            if routing_score_out is not None:
                payload["routing_score"] = routing_score_out
            # Inline attachments extracted from MEDIA:<path> sentinels — let
            # the frontend render them next to the assistant message even when
            # the LLM forgot to trigger a delivery tool.
            if _extracted_attachments:
                payload["attachments"] = _extracted_attachments
            _delivered = await _ws_send(_dumps(payload))
            # Explicit turn-end signal so the frontend can flip `isLoading=false`
            # synchronously (the React state batched on the `"message"` event
            # could otherwise still be truthy when the next keystroke fires —
            # causing Enter to be interpreted as "stop", not "send"). Pairs
            # with the frontend handler in chat/page.tsx.
            await _ws_send(_dumps({"type": "done"}))

            # Personne au bout du fil (onglet fermé pendant une tâche longue) :
            # la réponse est en base, mais l'utilisateur ne le sait pas. Un push
            # le lui dit — c'est la différence entre « Ely a planté » et « c'est
            # prêt, reviens voir » (incident 24/07). Best-effort, jamais bloquant.
            if not _delivered:
                spawn(
                    _notify_turn_done_offline(user_id, conversation_id, ai_content),
                    label="chat-offline-notify",
                )

            # ── Log usage for analytics ─────────────────────────────────────────
            if model_used_out:
                try:
                    from app.services.analytics_service import log_usage
                    from app.services.usage_instrumentation import architecture_label
                    # model_used_out is "llm:<provider>/<model>+tools?" or "slm:<model>"
                    # describe_llm() in nodes.py now resolves the real provider name
                    # (lm_studio, qwen_api, anthropic, …) so this split works for all
                    # chains incl. LM Studio + OpenAI-compatible local servers.
                    _strip_suffix = model_used_out.split("+", 1)[0]  # drop "+tools"
                    _parts = _strip_suffix.split(":", 1)
                    _type = _parts[0]  # "llm" or "slm"
                    _rest = _parts[1] if len(_parts) > 1 else model_used_out
                    if "/" in _rest:
                        _provider, _model = _rest.split("/", 1)
                    else:
                        _provider, _model = ("ollama" if _type == "slm" else "unknown"), _rest
                    # ── Token fallback estimation ─────────────────────────
                    # LM Studio (OpenAI-compatible local) often doesn't ship
                    # usage_metadata in streaming responses, leaving the
                    # totals at 0. Estimate via 4-chars-per-token heuristic
                    # so the dashboard isn't dead — flagged as estimate via
                    # input_tokens_total being computed AFTER, but stored
                    # opaquely (cost calc handles 0-cost local models anyway).
                    if input_tokens_total == 0 and user_content:
                        _uc = user_content if isinstance(user_content, str) else str(user_content)
                        input_tokens_total = max(1, len(_uc) // 4)
                    if output_tokens_total == 0 and ai_content:
                        output_tokens_total = max(1, len(ai_content) // 4)
                    # skill_used = most frequently called tool, or first if tie
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
                        channel="web",
                        latency_ms=int((time.monotonic() - _turn_started_at) * 1000),
                        # Le chat web passe un toolset_profile → le routeur est
                        # court-circuité (supervisor.py) → mono-agent.
                        architecture=architecture_label(
                            toolset_profile=_toolset_profile or None,
                        ),
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
            await _ws_send(_dumps({
                "type": "error",
                "content": "Une erreur interne s'est produite. Veuillez réessayer.",
            }))
        except Exception:
            pass  # Socket may already be closed; swallow the secondary error
    finally:
        ws_registry.unregister(user_id, websocket)
        # On disconnect: summarize conversation into long-term memory
        if conversation_id:
            spawn(_summarize_conversation(conversation_id, user_id))
            # Sprint 2.5 Jalon 6 — event-driven rapid maintenance:
            # extract 3-5 salient facts via Ministral 3B local and write
            # them directly into the typed SemanticUserStore. Runs in
            # parallel with the legacy summarisation above. Skippable
            # via env MAINTENANCE_RAPID_DISABLED on weak hardware — the
            # nightly cron (consolidate_user_memory) compensates.
            try:
                from app.services.memory.maintenance_rapid import (
                    schedule_consolidation as _mr_schedule,
                )
                _mr_schedule(conversation_id, user_id)
            except Exception:
                # Never let the maintenance scheduling break disconnect.
                pass
        _filters.pop(conversation_id, None) if conversation_id else None
        # Hermes Chantier 4 — drop fallback state on disconnect so the next
        # session for this user starts on the primary again. (Stickiness is
        # PER conversation, not per user.)
        # Hermes Chantier 2 — drop frozen memory snapshot + system prompt
        # cache so the next session reads fresh memory (mid-session writes
        # like memory_archive will surface in the new snapshot).
        if conversation_id:
            try:
                from app.services.fallback_manager import discard as _fb_discard
                from app.services.system_prompt_cache import discard as _spc_discard
                from app.services.frozen_memory import discard as _fm_discard
                _fb_discard(conversation_id)
                _spc_discard(conversation_id)
                _fm_discard(conversation_id)
            except Exception:
                pass


def _clean_title(raw: str) -> str:
    """Strip quotes / markdown / a leading 'Titre :' / trailing punctuation
    from an LLM-generated title, keep a single line, cap to ~10 words."""
    import re as _re
    t = (raw or "").strip().strip('"\'`*').strip()
    t = _re.sub(r"^(titre|title)\s*[:\-]\s*", "", t, flags=_re.IGNORECASE).strip()
    t = t.splitlines()[0].strip() if t else ""
    t = t.strip('"\'`*').rstrip(".").strip()
    words = t.split()
    if len(words) > 10:
        t = " ".join(words[:10])
    return t


async def _maybe_generate_title(
    conversation_id: str,
    user_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """Replace the naive ``user_content[:50]`` title with a concise LLM title
    after the first exchange. Best-effort, runs once per conversation (only
    when exactly one assistant reply exists), uses the MAINTENANCE tier (local)
    so it never disturbs the user's active model."""
    try:
        async with async_session() as db:
            msgs = (await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )).scalars().all()
        # Title once, on the first completed exchange — never overwrite a
        # later, richer title.
        if sum(1 for m in msgs if m.role == "assistant") != 1:
            return

        from app.services.llm_provider import get_llm_for_tier, ComplexityTier
        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)
        prompt = (
            "Génère un titre TRÈS court (3 à 7 mots, sans guillemets, sans "
            "point final) qui résume le sujet de cet échange. Réponds "
            "UNIQUEMENT par le titre, rien d'autre.\n\n"
            f"Utilisateur : {user_text[:500]}\n"
            f"Ely : {assistant_text[:500]}"
        )
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        title = _clean_title(raw)
        if not title:
            return
        async with async_session() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv is not None:
                conv.title = title[:255]
                await db.commit()
        logger.debug("conversation %s auto-titled: %s", conversation_id, title)
    except Exception as exc:
        logger.debug("title generation failed (swallowed): %s", exc)


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

        # FIX 2026-05-06 (audit H-2): summarisation et extraction de faits
        # sont des tâches MAINTENANCE — elles doivent respecter le tier
        # configuré par l'utilisateur dans Settings → Routage, pas piocher
        # dans `get_llm()` qui retombe sur la conf globale env/settings.
        # Avant ce fix, le summarizer chargeait silencieusement le modèle
        # actif (potentiellement Devstral / Ministral selon historique
        # `_runtime`), causant des cascades de chargements LM Studio
        # quand l'utilisateur attendait que son tier B fasse son boulot.
        from app.services.llm_provider import get_llm_for_tier, ComplexityTier
        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)

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

        # A-6b — ces 3 appels n'étaient pas comptés dans UsageLog : la
        # facture par user était sous-estimée sur un chemin qui tourne à
        # CHAQUE fin de conversation.
        try:
            from app.services.analytics_service import log_response_usage
            for _resp in (summary_resp, facts_resp, prefs_resp):
                await log_response_usage(
                    user_id, _resp,
                    skill_used="conversation_summary",
                    conversation_id=conversation_id,
                )
        except Exception:
            pass

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
