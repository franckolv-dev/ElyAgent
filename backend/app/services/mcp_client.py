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
import re
import shlex
from functools import lru_cache

logger = logging.getLogger(__name__)

# B-12 (revue 2026-06-10) — slug serveur → noms d'outils exposés. Permet à
# tool_acl de réserver les outils MCP (lancés avec les secrets admin) au
# rôle admin sans coupler tool_node au cycle de vie MCP.
_MCP_TOOL_NAMES: dict[str, set[str]] = {}


def mcp_tool_names() -> set[str]:
    """Noms (namespacés) de TOUS les outils MCP actuellement chargés."""
    names: set[str] = set()
    for tool_set in _MCP_TOOL_NAMES.values():
        names |= tool_set
    return names


# ── Namespace mcp__<slug>__<tool> ───────────────────────────────────────────
#
# Le nom local envoyé au modèle est INDÉPENDANT du nom distant. Garanties :
#   - aucun outil MCP ne peut masquer un outil natif d'ELY (préfixe réservé) ;
#   - deux serveurs exposant un homonyme (`search`) coexistent sans collision ;
#   - le routeur conserve la correspondance local → distant pour l'appel réel.
_NS_SEP = "__"
_NS_PREFIX = "mcp"
_NS_MAX_LEN = 128
_NS_VALID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def namespaced_tool_name(slug: str, remote_name: str) -> str:
    """``mcp__<slug>__<remote>`` — normalisé, borné, sans caractère hostile.

    Les noms d'outils exposés au modèle doivent matcher ``[a-zA-Z0-9_-]+``.
    On normalise le nom distant (entrée NON fiable du serveur) sans toucher
    le slug (déjà validé kebab-case côté création)."""
    safe_remote = _NS_VALID_RE.sub("_", remote_name or "")
    local = f"{_NS_PREFIX}{_NS_SEP}{slug}{_NS_SEP}{safe_remote}"
    return local[:_NS_MAX_LEN]


def _native_tool_names() -> set[str]:
    """Noms des outils NON-MCP actuellement enregistrés (garde anti-collision).

    Défensif : un nom local commençant par ``mcp__`` ne devrait jamais
    heurter un outil natif, mais on vérifie quand même — la sécurité ne
    repose pas sur une convention de nommage seule."""
    try:
        from app.skills.registry import get_skill_registry

        names: set[str] = set()
        for skill in get_skill_registry().list_skills():
            if "mcp" in (skill.scopes or ()):
                continue
            names.update(t.name for t in skill.tools)
        return names
    except Exception:  # pragma: no cover — defensive
        return set()


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

    def __init__(self, command: str, env: dict | None = None,
                 args: list[str] | None = None):
        # ``command`` est soit l'exécutable seul (quand ``args`` est fourni),
        # soit la ligne complète legacy (shlex.split dans _lifecycle). Aucun
        # passage par un shell dans les deux cas.
        self.command = command
        self.env = env
        self.args = args
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

            # Args explicites (V2) si fournis, sinon shlex.split de la ligne
            # legacy. Jamais de shell : StdioServerParameters exec direct.
            if self.args is not None:
                executable, args = self.command, list(self.args)
            else:
                parts = shlex.split(self.command)
                executable, args = parts[0], parts[1:]
            # `self.env` was already scrubbed by `_build_mcp_env` in the
            # caller (`_build_tools`). Falls back to None for backward-
            # compat callsites that pass a pre-scrubbed dict directly.
            params = StdioServerParameters(
                command=executable,
                args=args,
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
                    select(MCPServer).where(
                        MCPServer.enabled == True,            # noqa: E712
                        MCPServer.kill_switch == False,       # noqa: E712
                    )
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
        # Coupe-circuit par serveur : toujours honoré, indépendamment du
        # flag global. Un serveur kill-switché est déchargé, pas chargé.
        if getattr(srv, "kill_switch", False):
            logger.info("MCP server %s kill-switched — skipping load", srv.slug)
            await self.unload_server(srv.slug)
            return
        try:
            tools = await self._build_tools(srv)
            if not tools:
                logger.warning("MCP server %s exposed 0 tools — skipping", srv.slug)
                await _record_health(srv.slug, "degraded", "MCP_PROTOCOL_ERROR")
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
            await _record_health(srv.slug, "healthy", None, connected=True)
            logger.info("MCP skill loaded: %s (%d tools)", srv.slug, len(tools))
        except Exception as exc:
            logger.error("Failed to load MCP server %s: %s", srv.slug, exc)
            await _record_health(srv.slug, "offline", "MCP_CONNECT_FAILED")
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
                args = _parse_args_json(getattr(srv, "args_json", None))
                conn = _StdioConnection(srv.command, env, args=args)
                self._connections[srv.slug] = conn
                result = await conn.list_tools()
                mcp_tools: list[MCPTool] = result.tools
                wrapped = [self._wrap_tool(t, conn, srv.slug) for t in mcp_tools]
                return self._guard_collisions(srv.slug, wrapped)

            elif srv.transport == "streamable_http":
                return self._guard_collisions(
                    srv.slug, await self._build_streamable_http_tools(srv)
                )

            elif srv.transport in ("sse", "legacy_sse"):
                return self._guard_collisions(
                    srv.slug, await self._build_sse_tools(srv)
                )
            else:
                logger.warning("Unknown MCP transport: %s", srv.transport)
                return []

        except ImportError:
            logger.warning(
                "mcp/langchain-mcp-adapters not installed — MCP tools unavailable. "
                "Rebuild the Docker image to activate: make build"
            )
            return []

    def _wrap_tool(self, mcp_tool, conn: _StdioConnection, slug: str):
        """Enveloppe un MCPTool dans un LangChain StructuredTool (reconnexion auto).

        Le modèle voit le nom namespacé ``mcp__<slug>__<remote>`` ; l'appel
        réel ré-utilise le nom distant brut (``remote_name``)."""
        from langchain_core.tools import StructuredTool

        remote_name = mcp_tool.name
        local_name = namespaced_tool_name(slug, remote_name)
        tool_desc = mcp_tool.description or remote_name
        raw_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}

        # Build a Pydantic model from the JSON schema
        args_schema = _json_schema_to_pydantic(local_name, raw_schema)

        async def _call(**kwargs) -> str:
            try:
                result = await conn.call_tool(remote_name, kwargs)
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
                return f"Erreur MCP ({local_name}): {exc}"

        return StructuredTool(
            name=local_name,
            description=tool_desc,
            coroutine=_call,
            args_schema=args_schema,
        )

    async def _build_streamable_http_tools(self, srv) -> list:
        """Charge les outils d'un serveur MCP distant en Streamable HTTP.

        Transport MCP moderne. La connexion (initiale + chaque redirection)
        passe par la garde SSRF/rebinding ``mcp_egress`` : HTTPS imposé, IP
        validée et épinglée, cibles internes refusées."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        from langchain_core.tools import StructuredTool

        from app.services.mcp_egress import (
            MCPEgressBlocked,
            build_guarded_http_factory,
            validate_egress_url,
        )

        url = srv.url
        if not url:
            logger.warning("MCP streamable_http %s has no url", srv.slug)
            return []
        # LAN autorisé seulement via exception explicite (admin, hors V1).
        allow_private = bool(getattr(srv, "allow_private_network", False))

        # Validation AVANT toute connexion (clean early error). Le transport
        # re-valide et épingle de toute façon à chaque hop.
        try:
            validate_egress_url(url, allow_private=allow_private)
        except MCPEgressBlocked as exc:
            logger.warning("MCP streamable_http %s refusé (egress): %s", srv.slug, exc)
            return []

        factory = build_guarded_http_factory(allow_private=allow_private)
        headers = _remote_auth_headers(srv)   # J4 : credentials depuis le Vault
        tools = []

        try:
            async with streamablehttp_client(
                url, headers=headers, httpx_client_factory=factory,
            ) as (read, write, _get_sid):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    mcp_tools = result.tools

            for mcp_tool in mcp_tools:
                remote_name = mcp_tool.name
                local_name = namespaced_tool_name(srv.slug, remote_name)
                tool_desc = mcp_tool.description or remote_name
                raw_schema = mcp_tool.inputSchema or {}
                args_schema = _json_schema_to_pydantic(local_name, raw_schema)

                async def _call(_url=url, _name=remote_name, _local=local_name,
                                _factory=factory, _headers=headers, _ap=allow_private,
                                **kwargs) -> str:
                    try:
                        # Re-valider à chaque appel (la résolution DNS a pu
                        # changer) — le transport épingle ensuite.
                        validate_egress_url(_url, allow_private=_ap)
                        async with streamablehttp_client(
                            _url, headers=_headers, httpx_client_factory=_factory,
                        ) as (r, w, _s):
                            async with ClientSession(r, w) as sess:
                                await sess.initialize()
                                result = await sess.call_tool(_name, kwargs)
                                if hasattr(result, "content") and result.content:
                                    return "\n".join(
                                        b.text for b in result.content if hasattr(b, "text")
                                    )
                        return str(result)
                    except Exception as exc:
                        return f"Erreur MCP HTTP ({_local}): {exc}"

                tools.append(StructuredTool(
                    name=local_name,
                    description=tool_desc,
                    coroutine=_call,
                    args_schema=args_schema,
                ))
        except Exception as exc:
            logger.error("Streamable HTTP MCP connect failed (%s): %s", url, exc)

        return tools

    async def _build_sse_tools(self, srv) -> list:
        """Charge les outils depuis un serveur MCP SSE historique (legacy).

        Même garde egress que Streamable HTTP — un serveur SSE est distant."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from langchain_core.tools import StructuredTool

        from app.services.mcp_egress import (
            MCPEgressBlocked,
            build_guarded_http_factory,
            validate_egress_url,
        )

        url = srv.url
        tools = []
        if not url:
            logger.warning("MCP sse %s has no url", srv.slug)
            return []
        allow_private = bool(getattr(srv, "allow_private_network", False))
        try:
            validate_egress_url(url, allow_private=allow_private)
        except MCPEgressBlocked as exc:
            logger.warning("MCP sse %s refusé (egress): %s", srv.slug, exc)
            return []

        factory = build_guarded_http_factory(allow_private=allow_private)
        headers = _remote_auth_headers(srv)

        try:
            async with sse_client(url, headers=headers, httpx_client_factory=factory) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    mcp_tools = result.tools

            # Build per-call reconnecting tools for SSE
            for mcp_tool in mcp_tools:
                remote_name = mcp_tool.name
                local_name = namespaced_tool_name(srv.slug, remote_name)
                tool_desc = mcp_tool.description or remote_name
                raw_schema = mcp_tool.inputSchema or {}
                args_schema = _json_schema_to_pydantic(local_name, raw_schema)

                async def _call(_url=url, _name=remote_name, _local=local_name,
                                _factory=factory, _headers=headers, _ap=allow_private,
                                **kwargs) -> str:
                    try:
                        validate_egress_url(_url, allow_private=_ap)
                        async with sse_client(_url, headers=_headers, httpx_client_factory=_factory) as (r, w):
                            async with ClientSession(r, w) as sess:
                                await sess.initialize()
                                result = await sess.call_tool(_name, kwargs)
                                if hasattr(result, "content") and result.content:
                                    return "\n".join(
                                        b.text for b in result.content if hasattr(b, "text")
                                    )
                        return str(result)
                    except Exception as exc:
                        return f"Erreur MCP SSE ({_local}): {exc}"

                tools.append(StructuredTool(
                    name=local_name,
                    description=tool_desc,
                    coroutine=_call,
                    args_schema=args_schema,
                ))
        except Exception as exc:
            logger.error("SSE MCP connect failed (%s): %s", url, exc)

        return tools

    def _guard_collisions(self, slug: str, tools: list) -> list:
        """Écarte tout outil dont le nom local heurte un outil natif ou un
        autre serveur MCP déjà chargé. Fail-closed : en cas de doute, on
        n'expose PAS l'outil (mieux vaut un outil manquant qu'un natif
        masqué)."""
        if not tools:
            return tools
        native = _native_tool_names()
        other_mcp: set[str] = set()
        for other_slug, names in _MCP_TOOL_NAMES.items():
            if other_slug != slug:
                other_mcp |= names
        kept = []
        for t in tools:
            if t.name in native:
                logger.warning(
                    "MCP %s: outil '%s' écarté — collision avec un outil natif",
                    slug, t.name,
                )
                continue
            if t.name in other_mcp:
                logger.warning(
                    "MCP %s: outil '%s' écarté — collision avec un autre serveur MCP",
                    slug, t.name,
                )
                continue
            kept.append(t)
        return kept


# ------------------------------------------------------------------ #
# JSON Schema → Pydantic helper                                        #
# ------------------------------------------------------------------ #

def _remote_auth_headers(srv) -> dict[str, str] | None:
    """En-têtes d'authentification d'un serveur distant.

    J2 : serveurs publics (``auth_type=none``) → aucun en-tête. La récupération
    des credentials depuis le Vault (bearer / API key) est câblée en J4 — ce
    point d'entrée existe pour que le transport n'ait pas à changer ensuite."""
    return None


async def _record_health(slug: str, state: str, error_code: str | None,
                         *, connected: bool = False) -> None:
    """Best-effort : met à jour health_state / last_error_code / last_connected_at.

    N'échoue jamais la charge si l'écriture DB plante (chemin chaud du boot)."""
    try:
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.database import async_session
        from app.models.mcp_server import MCPServer

        values: dict = {"health_state": state, "last_error_code": error_code}
        if connected:
            values["last_connected_at"] = datetime.now(timezone.utc)
        async with async_session() as db:
            await db.execute(
                update(MCPServer).where(MCPServer.slug == slug).values(**values)
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover — observabilité, pas critique
        logger.debug("MCP health update failed for %s: %s", slug, exc)


def _parse_args_json(args_json: str | None) -> list[str] | None:
    """Liste d'arguments structurée → ``list[str]`` (ou None = legacy).

    Tout ce qui n'est pas une liste de chaînes est ignoré (retour None ⇒
    le connecteur retombe sur shlex.split de la ligne de commande)."""
    if not args_json:
        return None
    try:
        parsed = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("MCP args_json parse failed — falling back to command split")
        return None
    if isinstance(parsed, list) and all(isinstance(a, str) for a in parsed):
        return parsed
    logger.warning("MCP args_json is not a list[str] — ignoring")
    return None

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
