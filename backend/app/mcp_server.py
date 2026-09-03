# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/mcp_server.py
# @brief      ELY exposed AS an MCP server (Streamable-HTTP, API-key auth).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""ELY's own MCP server — lets external MCP clients (Claude Desktop, …) use
ELY's capabilities over an authenticated Streamable-HTTP endpoint.

Mounted on the FastAPI app at ``/api/mcp`` (J2). Auth is a personal API key
(J1, ``ely_api_…``) sent as ``Authorization: Bearer``; an ASGI middleware
resolves it to a user and stashes the id in a ContextVar the tools read.

v1 tools:
    - ely_chat                 — run one agent turn (autonomous-safe)
    - ely_list_scheduled_tasks — list the caller's scheduled tasks
    - ely_create_scheduled_task— create a scheduled task
    - ely_memory_search        — semantic search over the caller's memory
"""
from __future__ import annotations

import contextvars
import json
import logging
from typing import Annotated

from pydantic import Field

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

# Set per-request by the auth middleware; read by the tools. Empty when the
# caller is unauthenticated (the middleware rejects those before they reach a
# tool, so a tool seeing "" means it was called outside the HTTP path).
MCP_USER_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_user_id", default="")


def _require_user_id() -> str:
    uid = MCP_USER_ID.get()
    if not uid:
        raise ValueError("Non authentifié : clé API manquante ou invalide.")
    return uid


mcp = FastMCP(
    "ely_mcp",
    instructions=(
        "ELY — l'agent personnel souverain de l'utilisateur. Utilise ely_chat "
        "pour lui poser une question ou lui confier une tâche (il a accès à la "
        "mémoire, aux comptes Google et aux outils de l'utilisateur, en mode "
        "autonome-sûr : les actions irréversibles comme l'envoi d'e-mail ou la "
        "suppression sont bloquées). ely_memory_search pour retrouver ce qu'ELY "
        "sait de l'utilisateur. ely_list_scheduled_tasks / "
        "ely_create_scheduled_task pour piloter ses tâches planifiées."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    # DNS-rebinding protection (Host/Origin allow-listing) targets LOCAL servers
    # reachable by a victim's browser. ELY's MCP endpoint is REMOTE, behind
    # nginx/Cloudflare, and gated by a personal API key (a browser never holds
    # one) — so the Host header (which varies with the deploy) isn't the auth
    # boundary, the key is. Disabling avoids spurious 421s behind the proxy.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ─────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="ely_chat",
    annotations={
        "title": "Parler à ELY",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ely_chat(
    message: Annotated[str, Field(description="Le message / la question pour ELY", min_length=1, max_length=8000)],
    conversation_id: Annotated[str, Field(description="ID de conversation à continuer (optionnel ; vide = nouvelle conversation)")] = "",
) -> str:
    """Envoie un message à ELY et renvoie sa réponse (un tour complet).

    ELY tourne en mode **autonome-sûr** (``automated_task``) : il peut lire,
    chercher, analyser et rédiger avec ses outils, sa mémoire et les comptes
    Google de l'utilisateur, mais les actions **irréversibles** (envoi d'e-mail,
    suppression, SSH…) sont bloquées — il n'y a pas d'humain pour valider via
    un client MCP.

    Args:
        message: le texte à envoyer à ELY.
        conversation_id: pour enchaîner sur une conversation existante.

    Returns:
        La réponse texte d'ELY, suivie d'une ligne ``[conversation_id=…]`` que
        tu peux repasser pour continuer le fil.
    """
    user_id = _require_user_id()

    from langchain_core.messages import AIMessage, HumanMessage
    from sqlalchemy import select

    from app.agent.graph import build_simple_agent_graph
    from app.config import get_settings
    from app.database import async_session
    from app.models.conversation import Conversation, Message
    from app.models.user import User

    # Resolve the user's default Google credentials + (optionally) prior history.
    history: list = []
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            return "Erreur : utilisateur introuvable."
        google_credentials = user.google_credentials or ""

        conv = None
        if conversation_id:
            conv = (await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )).scalar_one_or_none()
            if conv is not None:
                rows = (await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at.desc())
                    .limit(20)
                )).scalars().all()
                for m in reversed(rows):
                    history.append(
                        HumanMessage(content=m.content) if m.role == "user"
                        else AIMessage(content=m.content)
                    )
        if conv is None:
            conv = Conversation(user_id=user_id, title=f"[MCP] {message[:60]}")
            db.add(conv)
            await db.flush()
        conv_id = str(conv.id)
        db.add(Message(conversation_id=conv_id, role="user", content=message))
        await db.commit()

    agent = build_simple_agent_graph()
    try:
        result = await agent.ainvoke(
            {
                "messages": [*history, HumanMessage(content=message)],
                "user_id": user_id,
                "conversation_id": conv_id,
                "google_credentials": google_credentials,
                "automated_task": True,
            },
            config={"recursion_limit": get_settings().scheduler_recursion_limit},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("ely_chat failed for user=%s", user_id)
        return f"Erreur pendant le traitement par ELY : {type(exc).__name__}: {exc}"

    raw = result["messages"][-1].content
    if isinstance(raw, list):
        answer = " ".join(
            (b.get("text", "") if isinstance(b, dict) else str(b)) for b in raw
        )
    else:
        answer = str(raw or "")

    # ── Anti-hallucination completion guard (C3d-1) ────────────────────────
    # Même vérification que les 7 autres surfaces (OutcomeVerifier commun),
    # au MÊME point : après l'aplatissement, AVANT persistance/livraison.
    # Consommateur machine ou pas, une action revendiquée sans outil exécuté
    # ce tour doit être remplacée par l'avertissement honnête — un agent MCP
    # amont propagerait la fausse affirmation encore plus loin qu'un humain.
    # Surface bufferisée → outils dérivés du result. Jamais bloquant.
    try:
        from app.services.output_verifier import verify_outcome_from_result
        answer = verify_outcome_from_result(
            result, answer,
            surface="mcp",
            user_message=message,
            user_id=user_id,
            conversation_id=conv_id,
        ).content
    except Exception as _guard_exc:  # noqa: BLE001
        logger.warning("completion_guard skipped (mcp): %s", _guard_exc)

    async with async_session() as db:
        db.add(Message(conversation_id=conv_id, role="assistant", content=answer))
        await db.commit()

    return f"{answer}\n\n[conversation_id={conv_id}]"


@mcp.tool(
    name="ely_list_scheduled_tasks",
    annotations={
        "title": "Lister les tâches planifiées",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ely_list_scheduled_tasks() -> str:
    """Liste les tâches planifiées de l'utilisateur.

    Returns:
        JSON : ``{"count": int, "tasks": [{"id","name","cron","prompt",
        "enabled","last_status","last_run_at"}]}``.
    """
    user_id = _require_user_id()
    from sqlalchemy import select

    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask

    async with async_session() as db:
        rows = (await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .order_by(ScheduledTask.created_at.desc())
        )).scalars().all()

    tasks = [
        {
            "id": t.id,
            "name": t.name,
            "cron": t.cron_expression,
            "prompt": t.prompt,
            "enabled": t.enabled,
            "last_status": t.last_status,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        }
        for t in rows
    ]
    return json.dumps({"count": len(tasks), "tasks": tasks}, ensure_ascii=False, indent=2)


@mcp.tool(
    name="ely_create_scheduled_task",
    annotations={
        "title": "Créer une tâche planifiée",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def ely_create_scheduled_task(
    name: Annotated[str, Field(description="Nom court de la tâche", min_length=1, max_length=255)],
    prompt: Annotated[str, Field(description="L'instruction qu'ELY exécutera à chaque déclenchement", min_length=1)],
    cron: Annotated[str, Field(description="Expression cron (ex. '0 8 * * 1' = lundi 8h) OU '@once <ISO>' pour un déclenchement unique")],
) -> str:
    """Crée (et programme) une tâche planifiée pour l'utilisateur.

    Args:
        name: nom court de la tâche.
        prompt: l'instruction exécutée par ELY à chaque déclenchement.
        cron: expression cron classique, ou ``@once <ISO8601>`` pour un one-shot.

    Returns:
        Un message de confirmation avec l'ID de la tâche, ou une erreur si
        l'expression cron est invalide.
    """
    user_id = _require_user_id()
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    from app.services.scheduler import schedule_task

    async with async_session() as db:
        task = ScheduledTask(
            user_id=user_id,
            name=name.strip(),
            prompt=prompt.strip(),
            cron_expression=cron.strip(),
            channel="web",
            enabled=True,
        )
        if not schedule_task(task):
            return (
                f"Erreur : expression cron invalide : '{cron}'. "
                "Exemples valides : '0 8 * * 1' (lundi 8h), '*/30 * * * *' "
                "(toutes les 30 min), '@once 2026-07-01T09:00'."
            )
        db.add(task)
        await db.commit()
        return f"Tâche planifiée créée : '{task.name}' (id={task.id}, cron='{task.cron_expression}')."


@mcp.tool(
    name="ely_memory_search",
    annotations={
        "title": "Chercher dans la mémoire d'ELY",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ely_memory_search(
    query: Annotated[str, Field(description="Ce que tu cherches dans la mémoire d'ELY", min_length=1, max_length=500)],
    limit: Annotated[int, Field(description="Nombre maximum de souvenirs à retourner", ge=1, le=20)] = 5,
) -> str:
    """Recherche sémantique dans la mémoire typée d'ELY (faits sur l'utilisateur).

    Args:
        query: la requête de recherche.
        limit: nombre maximum de résultats (1-20, défaut 5).

    Returns:
        Une liste des souvenirs pertinents, ou un message indiquant qu'aucun
        souvenir ne correspond.
    """
    user_id = _require_user_id()
    from app.services.memory_manager import get_memory_manager

    facts = await get_memory_manager().get_relevant_memories(query, user_id, limit)
    if not facts:
        return f"Aucun souvenir pertinent pour « {query} »."
    lines = [f"{len(facts)} souvenir(s) pour « {query} » :", ""]
    lines.extend(f"- {f}" for f in facts)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Auth middleware (API key → MCP_USER_ID) + mount builder
# ─────────────────────────────────────────────────────────────────────────

def _send_401():
    body = json.dumps(
        {"error": "unauthorized",
         "message": "Clé API manquante ou invalide. En-tête attendu : "
                    "'Authorization: Bearer ely_api_…' (générez une clé dans "
                    "Réglages → Clés API)."}
    ).encode("utf-8")

    async def _asgi(send) -> None:
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    return _asgi


class MCPAuthMiddleware:
    """ASGI middleware: authenticate the personal API key, set MCP_USER_ID.

    Wraps the FastMCP Streamable-HTTP app. Rejects any request without a valid
    ``Authorization: Bearer ely_api_…`` header with a 401 before it reaches the
    MCP protocol layer.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
        auth = headers.get(b"authorization", b"").decode("latin-1")
        key = auth[7:].strip() if auth[:7].lower() == "bearer " else ""

        user = None
        if key:
            from app.database import async_session
            from app.routers.api_keys import authenticate_api_key
            try:
                async with async_session() as db:
                    user = await authenticate_api_key(key, db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP auth lookup failed: %s", exc)
                user = None

        if user is None:
            await _send_401()(send)
            return

        token = MCP_USER_ID.set(str(user.id))
        try:
            await self.app(scope, receive, send)
        finally:
            MCP_USER_ID.reset(token)


def build_mcp_app():
    """Build the auth-wrapped Streamable-HTTP ASGI app to mount at /api/mcp.

    Calling ``streamable_http_app()`` here (once) also creates the lazy
    ``mcp.session_manager`` that ``main.py``'s lifespan must run.
    """
    return MCPAuthMiddleware(mcp.streamable_http_app())
