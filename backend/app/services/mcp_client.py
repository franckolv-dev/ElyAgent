# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_client.py
# @brief      MCPClientManager — connexion dynamique à des serveurs MCP externes
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""MCPClientManager — connexion dynamique à des serveurs MCP externes.

Charge les configurations depuis la base de données au démarrage et crée
des LangChain StructuredTools pour chaque outil exposé par les serveurs.

Deux transports :
  - stdio  : processus local maintenu vivant avec reconnexion auto
  - sse    : reconnexion par appel (HTTP SSE, léger)

Architecture
------------
- Un MCPServer DB config  →  une Skill dans le SkillRegistry
- `reload_all()`         →  appelé au démarrage (lifespan)
- `load_server(config)`  →  appelé après création d'un nouveau serveur via l'API
- `unload_server(slug)`  →  appelé après suppression
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from functools import lru_cache

logger = logging.getLogger(__name__)

# B-12 (revue 2026-06-10) — slug serveur → noms d'outils exposés. Permet à
# tool_acl de réserver les outils MCP (lancés avec les secrets admin) au
# rôle admin sans coupler tool_node au cycle de vie MCP.
_MCP_TOOL_NAMES: dict[str, set[str]] = {}


def mcp_tool_names() -> set[str]:
    """Noms de TOUS les outils MCP actuellement chargés."""
    names: set[str] = set()
    for tool_set in _MCP_TOOL_NAMES.values():
        names |= tool_set
    return names


# ── Env scrubbing constants for the spawned MCP process ─────────────────────
#
# Same defense-in-depth model as orchestrate_runner: block every variable
# whose name contains a secret substring, allow only whitelisted prefixes
# through, then layer the per-server `env_json` overrides on top.
#
# MCP-specific additions vs the orchestrate list:
#   - UV_  : uv (Astral) needs UV_TOOL_DIR / UV_CACHE_DIR / UV_PYTHON, all
#            harmless and required to run `uv tool run mcp-server-*` from
#            within the container (see J1.5d, docker-compose.yml).
#   - NPM_ / NODE_ : npx / node based MCP servers (filesystem, fetch,
#            puppeteer, …) need them to find their global install.
#   - DEBIAN_FRONTEND : silences apt prompts in some servers' wrappers.
_MCP_SAFE_ENV_PREFIXES: tuple[str, ...] = (
    "PATH", "HOME", "USER", "LANG", "LC_", "TERM",
    "TMPDIR", "TMP", "TEMP", "SHELL", "LOGNAME",
    "XDG_", "TZ",
    "ELY_",
    "UV_",
    "NPM_", "NODE_",
    "DEBIAN_FRONTEND",
)

_MCP_SECRET_SUBSTRINGS: tuple[str, ...] = (
    "KEY", "TOKEN", "SECRET", "PASSWORD",
    "CREDENTIAL", "PASSWD", "AUTH",
)


def _build_mcp_env(env_json: str | None) -> dict[str, str]:
    """Build the env passed to a stdio MCP server subprocess.

    Step 1: filter ``os.environ`` through the prefix whitelist + secret
    blocklist (so we never accidentally leak ``ANTHROPIC_API_KEY`` or
    ``GITHUB_TOKEN`` into a 3rd-party MCP server).

    Step 2: layer the admin-supplied JSON env on top — those are
    explicit overrides chosen via the admin UI (e.g. setting a fresh
    ``GITHUB_PERSONAL_ACCESS_TOKEN`` for an MCP-GitHub server). Admin
    intent wins over the blocklist because if the admin types it into
    the form, they know what they're doing.
    """
    from app.services.env_filter import filter_safe_env

    env = filter_safe_env(
        safe_prefixes=_MCP_SAFE_ENV_PREFIXES,
        secret_substrings=_MCP_SECRET_SUBSTRINGS,
    )
    if env_json:
        try:
            overrides = json.loads(env_json)
            if isinstance(overrides, dict):
                # Only keep string values — MCP server env must be {str: str}.
                for k, v in overrides.items():
                    if isinstance(v, str):
                        env[str(k)] = v
            else:
                logger.warning("MCP env_json is not a JSON object — ignoring")
        except json.JSONDecodeError as exc:
            logger.warning("MCP env_json parse failed (%s) — ignoring", exc)
    return env


class _StdioConnection:
    """Connexion stdio persistante vers un processus MCP (reconnexion auto).

    Lifecycle pattern (Sprint 4a J1.5b, 2026-05-27)
    -----------------------------------------------
    The MCP SDK uses anyio under the hood. ``stdio_client`` and
    ``ClientSession`` open anyio TaskGroups whose CancelScopes are
    **task-bound** — calling ``__aexit__`` from a different asyncio task
    than ``__aenter__`` raises ``RuntimeError: Attempted to exit cancel
    scope in a different task than it was entered in``.

    Previously we entered the context managers from whichever task first
    invoked ``call_tool`` and tried to exit them from whoever called
    ``close`` (the admin router task, typically) — that crashed.

    We now run the entire ``async with stdio_client(...) as ...: async
    with ClientSession(...) as session: ... await _shutdown.wait()``
    block inside a dedicated long-lived task (``_lifecycle``). External
    callers operate on ``self._session`` via the session's anyio
    memory object streams (which are safely task-shareable). The
    lifecycle task owns enter and exit, so both run in the same task
    and no cancel scope ever crosses a task boundary.
    """

    def __init__(self, command: str, env: dict | None = None):
        self.command = command
        self.env = env
        self._lock = asyncio.Lock()
        self._session = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._init_error: BaseException | None = None

    async def _lifecycle(self) -> None:
        """Own ``stdio_client`` + ``ClientSession`` entry+exit in one task."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            parts = shlex.split(self.command)
            # `self.env` was already scrubbed by `_build_mcp_env` in the
            # caller (`_build_tools`). Falls back to None for backward-
            # compat callsites that pass a pre-scrubbed dict directly.
            params = StdioServerParameters(
                command=parts[0],
                args=parts[1:],
                env=self.env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    # Park here until close() flips the shutdown event.
                    # External tasks use `self._session` for I/O during
                    # this window — that's safe because anyio memory
                    # object streams are task-shareable for send/recv.
                    await self._shutdown.wait()
        except BaseException as exc:  # noqa: BLE001 — funnel all init failures
            logger.error("MCP stdio lifecycle failed (%s): %s", self.command, exc)
            self._init_error = exc
            # Unblock any task waiting in _connect; it will re-raise.
            self._ready.set()
        finally:
            self._session = None

    async def _connect(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._ready.clear()
        self._shutdown.clear()
        self._init_error = None
        self._task = asyncio.create_task(
            self._lifecycle(),
            name=f"mcp-stdio:{self.command[:32]}",
        )
        await self._ready.wait()
        if self._init_error is not None:
            err = self._init_error
            # Make sure the dead task is reaped before we re-raise.
            await self._reap_task()
            raise err

    async def _reap_task(self) -> None:
        """Best-effort awaits the lifecycle task without re-raising."""
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001
                pass
        except BaseException:  # noqa: BLE001
            pass
        finally:
            self._task = None

    async def close(self) -> None:
        """Idempotent shutdown — safe to call from any task."""
        self._shutdown.set()
        await self._reap_task()
        self._session = None

    async def call_tool(self, tool_name: str, arguments: dict):
        async with self._lock:
            for attempt in range(2):
                try:
                    if self._session is None:
                        await self._connect()
                    result = await self._session.call_tool(tool_name, arguments)
                    return result
                except Exception as exc:
                    if attempt == 0:
                        logger.warning("MCP call failed, reconnecting: %s", exc)
                        await self.close()
                    else:
                        raise

    async def list_tools(self):
        """Return the raw mcp.types.ListToolsResult."""
        async with self._lock:
            if self._session is None:
                await self._connect()
            return await self._session.list_tools()


class MCPClientManager:
    """Singleton chargé de connecter ELY aux serveurs MCP et d'exposer leurs outils."""

    def __init__(self) -> None:
        self._connections: dict[str, _StdioConnection] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def reload_all(self) -> None:
        """Charge tous les serveurs MCP activés depuis la base de données."""
        try:
            from app.database import async_session
            from app.models.mcp_server import MCPServer
            from sqlalchemy import select

            async with async_session() as db:
                result = await db.execute(
                    select(MCPServer).where(MCPServer.enabled == True)
                )
                servers = result.scalars().all()

            for srv in servers:
                try:
                    await self.load_server(srv)
                except Exception as exc:
                    logger.warning("Failed to load MCP server %s: %s", srv.slug, exc)
        except Exception as exc:
            logger.warning("MCPClientManager.reload_all failed: %s", exc)

    async def load_server(self, srv) -> None:
        """Charge les outils d'un MCPServer et les enregistre dans le SkillRegistry."""
        try:
            tools = await self._build_tools(srv)
            if not tools:
                logger.warning("MCP server %s exposed 0 tools — skipping", srv.slug)
                return

            from app.skills.base import Skill
            from app.skills.registry import get_skill_registry

            skill = Skill(
                name=f"mcp_{srv.slug}",
                display_name=srv.name,
                description=srv.description or f"Outils MCP : {srv.name}",
                icon="🔌",
                scopes=["mcp"],
                tools=tools,
                author="mcp",
            )
            get_skill_registry().register_or_replace(skill)
            # B-12 — les outils MCP tournent avec les secrets env_json de
            # l'admin : tool_acl les réserve au rôle admin via ce registre.
            _MCP_TOOL_NAMES[srv.slug] = {t.name for t in tools}
            logger.info("MCP skill loaded: %s (%d tools)", srv.slug, len(tools))
        except Exception as exc:
            logger.error("Failed to load MCP server %s: %s", srv.slug, exc)
            raise

    async def unload_server(self, slug: str) -> None:
        """Supprime la Skill MCP du registry et ferme la connexion."""
        from app.skills.registry import get_skill_registry
        get_skill_registry().unregister(f"mcp_{slug}")
        _MCP_TOOL_NAMES.pop(slug, None)

        conn = self._connections.pop(slug, None)
        if conn:
            await conn.close()
        logger.info("MCP skill unloaded: %s", slug)

    # ------------------------------------------------------------------ #
    # Tool building                                                        #
    # ------------------------------------------------------------------ #

    async def _build_tools(self, srv) -> list:
        """Crée les LangChain StructuredTool pour chaque outil du serveur."""
        try:
            from mcp.types import Tool as MCPTool

            if srv.transport == "stdio":
                env = _build_mcp_env(srv.env_json)
                conn = _StdioConnection(srv.command, env)
                self._connections[srv.slug] = conn
                result = await conn.list_tools()
                mcp_tools: list[MCPTool] = result.tools
                return [self._wrap_tool(t, conn) for t in mcp_tools]

            elif srv.transport == "sse":
                return await self._build_sse_tools(srv)
            else:
                logger.warning("Unknown MCP transport: %s", srv.transport)
                return []

        except ImportError:
            logger.warning(
                "mcp/langchain-mcp-adapters not installed — MCP tools unavailable. "
                "Rebuild the Docker image to activate: make build"
            )
            return []

    def _wrap_tool(self, mcp_tool, conn: _StdioConnection):
        """Enveloppe un MCPTool dans un LangChain StructuredTool (reconnexion auto)."""
        from langchain_core.tools import StructuredTool

        tool_name = mcp_tool.name
        tool_desc = mcp_tool.description or tool_name
        raw_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}

        # Build a Pydantic model from the JSON schema
        args_schema = _json_schema_to_pydantic(tool_name, raw_schema)

        async def _call(**kwargs) -> str:
            try:
                result = await conn.call_tool(tool_name, kwargs)
                # Extract text content from MCP result
                if hasattr(result, "content") and result.content:
                    parts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                        elif hasattr(block, "data"):
                            parts.append(f"[binary:{block.mimeType}]")
                    return "\n".join(parts) if parts else str(result)
                return str(result)
            except Exception as exc:
                return f"Erreur MCP ({tool_name}): {exc}"

        return StructuredTool(
            name=tool_name,
            description=tool_desc,
            coroutine=_call,
            args_schema=args_schema,
        )

    async def _build_sse_tools(self, srv) -> list:
        """Charge les outils depuis un serveur MCP SSE (HTTP)."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from langchain_core.tools import StructuredTool

        url = srv.url
        tools = []

        try:
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    mcp_tools = result.tools

            # Build per-call reconnecting tools for SSE
            for mcp_tool in mcp_tools:
                tool_name = mcp_tool.name
                tool_desc = mcp_tool.description or tool_name
                raw_schema = mcp_tool.inputSchema or {}
                args_schema = _json_schema_to_pydantic(tool_name, raw_schema)

                async def _call(_url=url, _name=tool_name, **kwargs) -> str:
                    try:
                        async with sse_client(_url) as (r, w):
                            async with ClientSession(r, w) as sess:
                                await sess.initialize()
                                result = await sess.call_tool(_name, kwargs)
                                if hasattr(result, "content") and result.content:
                                    return "\n".join(
                                        b.text for b in result.content if hasattr(b, "text")
                                    )
                        return str(result)
                    except Exception as exc:
                        return f"Erreur MCP SSE ({_name}): {exc}"

                tools.append(StructuredTool(
                    name=tool_name,
                    description=tool_desc,
                    coroutine=_call,
                    args_schema=args_schema,
                ))
        except Exception as exc:
            logger.error("SSE MCP connect failed (%s): %s", url, exc)

        return tools


# ------------------------------------------------------------------ #
# JSON Schema → Pydantic helper                                        #
# ------------------------------------------------------------------ #

def _json_schema_to_pydantic(tool_name: str, schema: dict):
    """Convertit un JSON Schema (dict) en modèle Pydantic dynamique."""
    from pydantic import BaseModel, Field, create_model
    from typing import Any, Optional

    props: dict = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    fields: dict = {}
    for prop_name, prop_schema in props.items():
        type_str = prop_schema.get("type", "string")
        description = prop_schema.get("description", "")

        # Map JSON Schema types to Python types
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        py_type = type_map.get(type_str, Any)

        if prop_name in required:
            fields[prop_name] = (py_type, Field(description=description))
        else:
            fields[prop_name] = (Optional[py_type], Field(default=None, description=description))

    model_name = f"MCPArgs_{tool_name}"
    return create_model(model_name, **fields)


@lru_cache(maxsize=1)
def get_mcp_client_manager() -> MCPClientManager:
    return MCPClientManager()
