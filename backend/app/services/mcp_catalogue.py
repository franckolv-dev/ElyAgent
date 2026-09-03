# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mcp_catalogue.py
# @brief      Persistance du catalogue d'outils MCP découverts (table mcp_tools).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Catalogue local des outils découverts sur un serveur MCP.

Conserve le JSON Schema **complet** (in + out), les annotations (non fiables)
et un ``definition_hash``. Règles (cadrage §11.1, §14.2) :

* un outil **nouveau** arrive ``enabled=False`` (découvert ≠ activé) ;
* un outil dont la **définition change** repasse ``enabled=False`` (l'ancienne
  autorisation ne vaut plus) ;
* un outil **disparu** est retiré du catalogue ;
* le ``risk_level`` est déduit du nom/description/schéma — **pas** des
  annotations du serveur, considérées non fiables.

La persistance est best-effort : elle ne doit jamais faire échouer la charge
d'un serveur (chemin chaud du boot).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Heuristique de risque — mots-clés (nom + description). Conservateur :
# en cas de doute on classe plus haut, jamais plus bas.
_CRITICAL = re.compile(
    r"\b(delete|remove|destroy|drop|wipe|purge|pay|payment|charge|transfer|"
    r"refund|grant|revoke|exec|execute|shell|sudo|sql|deploy|shutdown)\b", re.I)
_HIGH = re.compile(
    r"\b(write|create|update|edit|insert|send|post|publish|email|message|"
    r"upload|push|merge|approve|invite|set|move|rename)\b", re.I)
_LOW = re.compile(
    r"\b(get|list|read|search|find|fetch|view|show|time|weather|status|"
    r"ping|echo|count)\b", re.I)


def classify_risk(remote_name: str, description: str | None, input_schema: dict | None) -> str:
    """Niveau de risque local : low | medium | high | critical."""
    # Normalise les séparateurs (snake_case/kebab) en espaces : sinon les
    # limites de mots \b ne s'amorcent pas (« delete_file » ≠ « delete »).
    blob = re.sub(r"[^a-z0-9]+", " ", f"{remote_name} {description or ''}".lower())
    if _CRITICAL.search(blob):
        return "critical"
    if _HIGH.search(blob):
        return "high"
    # Paramètres sensibles → au moins medium même si le nom paraît anodin.
    props = (input_schema or {}).get("properties", {}) if isinstance(input_schema, dict) else {}
    sensitive = {"path", "command", "cmd", "to", "recipient", "query", "sql", "url", "file"}
    if any(p.lower() in sensitive for p in props):
        return "medium"
    if _LOW.search(blob):
        return "low"
    return "medium"


async def persist_catalogue(server_id: str, slug: str, mcp_tools: list) -> None:
    """Upsert les outils découverts dans ``mcp_tools``. Best-effort."""
    try:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.mcp_server import MCPTool
        from app.services.mcp_client import namespaced_tool_name
        from app.services.mcp_schema import definition_hash

        async with async_session() as db:
            rows = (await db.execute(
                select(MCPTool).where(MCPTool.server_id == server_id)
            )).scalars().all()
            existing = {r.remote_name: r for r in rows}
            seen: set[str] = set()

            for t in mcp_tools:
                remote = getattr(t, "name", None)
                if not remote:
                    continue
                seen.add(remote)
                in_schema = getattr(t, "inputSchema", None)
                out_schema = getattr(t, "outputSchema", None)
                desc = getattr(t, "description", None)
                ann = getattr(t, "annotations", None)
                ann_json = None
                if ann is not None and hasattr(ann, "model_dump"):
                    try:
                        ann_json = json.dumps(ann.model_dump(exclude_none=True))
                    except Exception:
                        ann_json = None
                dh = definition_hash(remote, desc, in_schema, out_schema)
                local = namespaced_tool_name(slug, remote)
                risk = classify_risk(remote, desc, in_schema)

                row = existing.get(remote)
                if row is None:
                    # Nouvel outil → quarantaine (enabled=False).
                    row = MCPTool(server_id=server_id, remote_name=remote,
                                  local_name=local, enabled=False)
                    db.add(row)
                elif row.definition_hash != dh:
                    # Définition changée → re-quarantaine (l'autorisation chute).
                    row.enabled = False

                row.local_name = local
                row.title = getattr(t, "title", None)
                row.description = desc
                row.input_schema_json = json.dumps(in_schema) if in_schema else None
                row.output_schema_json = json.dumps(out_schema) if out_schema else None
                row.annotations_json = ann_json
                row.definition_hash = dh
                row.risk_level = risk

            # Outils disparus → retirés du catalogue.
            for remote, row in existing.items():
                if remote not in seen:
                    await db.delete(row)

            await db.commit()
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("MCP catalogue persist failed for %s: %s", slug, exc)
