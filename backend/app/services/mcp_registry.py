# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_registry.py
# @brief      Recherche dans le registre MCP officiel (découverte uniquement).
# @license    MIT
# =============================================================================
"""Recherche de serveurs dans le registre MCP officiel.

⚠️ **Zéro confiance implicite.** Le registre ne fait que de la *découverte* :
il fournit des suggestions (nom, description, config d'installation). Choisir
une entrée ne connecte rien et n'accorde aucune confiance. La connexion passe
ensuite par le chemin de consentement normal :

* serveur **distant** → ``mcp_connect`` (garde egress + HITL) ;
* serveur **local** → ``mcp_propose_server`` (quarantaine + approbation humaine).

Les descriptions du registre sont des **entrées non fiables** : on les borne.
La fonction ``search_registry`` accepte un ``fetch`` injectable pour les tests
(aucun réseau).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, NamedTuple, Optional

logger = logging.getLogger(__name__)

# Borne anti tool-poisoning sur les textes du registre.
_MAX_DESC = 280

# Dérivation d'une commande locale à partir d'un paquet du registre.
_RUNTIME_BY_REGISTRY = {
    "npm": ("npx", ["-y"]),
    "pypi": ("uvx", []),
    "oci": ("docker", ["run", "--rm", "-i"]),
}


class RegistryEntry(NamedTuple):
    name: str
    description: str          # borné, non fiable
    kind: str                 # "remote" | "local" | "unknown"
    url: Optional[str]        # remote
    command: Optional[str]    # local (suggestion)
    args: list[str]           # local (suggestion)
    source: str = "mcp-registry"


def _clean(text: object) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s[:_MAX_DESC]


def _parse_entry(raw: dict) -> Optional[RegistryEntry]:
    if not isinstance(raw, dict):
        return None
    name = _clean(raw.get("name"))
    if not name:
        return None
    desc = _clean(raw.get("description"))

    remotes = raw.get("remotes") or []
    if isinstance(remotes, list) and remotes and isinstance(remotes[0], dict):
        url = remotes[0].get("url")
        if isinstance(url, str) and url:
            return RegistryEntry(name, desc, "remote", url, None, [])

    packages = raw.get("packages") or []
    if isinstance(packages, list) and packages and isinstance(packages[0], dict):
        pkg = packages[0]
        reg = (pkg.get("registry_type") or pkg.get("registry_name") or "").lower()
        ident = pkg.get("identifier") or pkg.get("name") or ""
        runtime = _RUNTIME_BY_REGISTRY.get(reg)
        if runtime and ident:
            cmd, base_args = runtime
            return RegistryEntry(name, desc, "local", None, cmd, [*base_args, str(ident)])

    return RegistryEntry(name, desc, "unknown", None, None, [])


def _extract_list(payload: object) -> list:
    if isinstance(payload, dict):
        for key in ("servers", "data", "results", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    if isinstance(payload, list):
        return payload
    return []


async def _default_fetch(query: str, limit: int) -> object:
    """GET sur le registre officiel (endpoint configurable)."""
    import httpx

    from app.config import get_settings

    base = (getattr(get_settings(), "mcp_registry_url", "") or
            "https://registry.modelcontextprotocol.io").rstrip("/")
    url = f"{base}/v0/servers"
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.get(url, params={"search": query, "limit": limit})
        resp.raise_for_status()
        return resp.json()


async def search_registry(
    query: str,
    *,
    limit: int = 10,
    fetch: Callable[[str, int], Awaitable[object]] | None = None,
) -> list[RegistryEntry]:
    """Cherche des serveurs dans le registre. Renvoie des SUGGESTIONS (data),
    jamais une connexion."""
    fetch = fetch or _default_fetch
    try:
        payload = await fetch(query, limit)
    except Exception as exc:
        logger.warning("MCP registry search failed: %s", exc)
        return []
    entries: list[RegistryEntry] = []
    for raw in _extract_list(payload)[:limit]:
        parsed = _parse_entry(raw)
        if parsed is not None:
            entries.append(parsed)
    return entries
