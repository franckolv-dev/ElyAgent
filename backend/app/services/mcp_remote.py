# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_remote.py
# @brief      Connexion MCP distante À LA DEMANDE (chemin model-facing).
# @license    Elastic License 2.0
# =============================================================================
"""Connexion/découverte/appel distants à la demande, avec identité utilisateur.

Les serveurs ``scope=user`` ne sont PAS chargés dans le registre global
(partagé) : ils sont invoqués via les outils model-facing, qui ont le contexte
de l'utilisateur courant. Ce module ouvre une session à la demande, en
réutilisant la garde egress (J2), la normalisation des résultats et la
validation d'arguments (J3) et les credentials du Vault (J4).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _session(url: str, transport: str, headers: dict | None, allow_private: bool):
    """Ouvre une ClientSession MCP distante durcie (egress + pinning)."""
    from mcp import ClientSession

    from app.services.mcp_egress import build_guarded_http_factory, validate_egress_url

    validate_egress_url(url, allow_private=allow_private)
    factory = build_guarded_http_factory(allow_private=allow_private)

    if transport == "streamable_http":
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(url, headers=headers, httpx_client_factory=factory) as (r, w, _s):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session
    elif transport in ("sse", "legacy_sse"):
        from mcp.client.sse import sse_client
        async with sse_client(url, headers=headers, httpx_client_factory=factory) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session
    else:
        raise ValueError(f"transport distant non supporté : {transport}")


async def probe_remote(url: str, *, transport: str = "streamable_http",
                       allow_private: bool = False) -> list:
    """Valide la cible, se connecte et liste les outils (sans rien activer)."""
    from app.services.mcp_client import _collect_tools

    async with _session(url, transport, None, allow_private) as session:
        return await _collect_tools(session.list_tools)


async def remote_list_tools(srv, user_id: str) -> list:
    """Liste + persiste le catalogue d'un serveur distant pour son propriétaire."""
    from app.services.mcp_catalogue import persist_catalogue
    from app.services.mcp_client import _collect_tools
    from app.services.mcp_credentials import resolve_user_headers

    headers = await resolve_user_headers(user_id, srv)
    async with _session(srv.url, srv.transport, headers,
                        bool(getattr(srv, "allow_private_network", False))) as session:
        tools = await _collect_tools(session.list_tools)
    await persist_catalogue(srv.id, srv.slug, tools)
    return tools


async def remote_call_tool(srv, user_id: str, remote_tool: str, args: dict,
                           *, input_schema: dict | None = None,
                           local_name: str = "mcp") -> str:
    """Valide les args, connecte avec les credentials du propriétaire, appelle,
    normalise. La politique egress/ACL/outbound est appliquée par l'appelant."""
    from app.services.mcp_credentials import resolve_user_headers
    from app.services.mcp_results import normalize_call_result
    from app.services.mcp_schema import validate_arguments

    validate_arguments(input_schema, args)
    headers = await resolve_user_headers(user_id, srv)
    async with _session(srv.url, srv.transport, headers,
                        bool(getattr(srv, "allow_private_network", False))) as session:
        result = await session.call_tool(remote_tool, args)
    return normalize_call_result(result, local_name=local_name)
