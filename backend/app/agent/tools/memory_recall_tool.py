# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/memory_recall_tool.py
# @brief      Unified `memory_recall(type, query)` tool — Sprint 2.5 Jalon 3.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.3.0
# =============================================================================
"""LangChain tool exposing the unified typed-memory recall API to the LLM.

The agent calls this tool to ask "what do I remember about X, of type Y?".
Replaces (over time) the fragmented set of legacy tools:
`memory_search`, `memory_recent`, `notes_search`, `save_user_preference`,
`search_past_conversations_tool` — all of which become deprecated aliases
in Jalon 7.

The return is a Markdown digest the LLM can quote in its reply. No JSON
structure (this is intentional — agents stitch prose better than they
juggle structured payloads, see docstring on `session_search_tool`).
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.services.memory.recall_service import get_memory_recall_service
from app.services.memory.types import MemoryType
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


_VALID_TYPES_TEXT = (
    "episodic | semantic_user | procedural | error | constraint | auto"
)


@register(
    domain=Domain.MEMORY,
    skill_name="memory_recall_unified",
    skill_display_name="Mémoire unifiée multi-typée",
    skill_description=(
        "Recall typé sur la mémoire cognitive d'ELY (épisodique, sémantique-user, "
        "procédurale, erreurs, contraintes). API unique remplaçant à terme les "
        "anciens tools memory_search / memory_recent / notes_search / etc."
    ),
    skill_icon="🧠",
    enabled_by_default=True,
    skill_version="0.1.0",
)
@tool
async def memory_recall(
    query: str,
    memory_type: str = "auto",
    limit: int = 5,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Recall typed memories matching *query*.

    USE THIS TOOL when you need to retrieve something the user has told you
    or that you've learned from past interactions, and you can be specific
    about WHICH type of memory you're after. When unsure, pass
    ``memory_type="auto"`` — the service fans out across all stores.

    The 5 typed memories
    --------------------
    - **episodic**       : past Q&A pairs from previous conversations.
                          "What did we say about X last week?"
    - **semantic_user**  : stable facts about the user (preferences, who
                          they are, projects, vocabulary).
                          "Does the user have a doctor?"
    - **procedural**     : reusable how-to recipes (sequences of tool calls
                          known to solve a class of mission). V1: stub —
                          will start returning results once Jalon 6 lands.
    - **error**          : past failures, for "I already tried that".
                          V1: write-only — recall returns []. Sprint 3.7
                          will surface them.
    - **constraint**     : user-imposed security rules
                          ("never delete without asking").
    - **auto**           : fan out across all of the above in parallel and
                          merge results by score.

    Args:
        query: free-text describing what you want to remember.
        memory_type: one of (``episodic | semantic_user | procedural |
                     error | constraint | auto``). Default ``auto``.
        limit: how many hits to return. Clamped to [1, 10].

    Returns:
        Markdown digest with 0 to *limit* sections. Prose only — feel
        free to quote or paraphrase directly into your reply.
    """
    if not user_id:
        return "Erreur interne : user_id manquant."
    if not query or not query.strip():
        return "Erreur : la requête est vide. Précise ce que tu cherches."

    try:
        mt = MemoryType.parse(memory_type)
    except ValueError:
        return (
            f"Erreur : memory_type={memory_type!r} invalide. "
            f"Valeurs acceptées : {_VALID_TYPES_TEXT}."
        )

    safe_limit = max(1, min(int(limit) if isinstance(limit, (int, float)) else 5, 10))

    try:
        hits = await get_memory_recall_service().recall(
            memory_type=mt,
            query=query,
            user_id=user_id,
            limit=safe_limit,
        )
    except Exception as exc:
        logger.warning("memory_recall failed: %s", exc, exc_info=True)
        return (
            "Je n'ai pas pu interroger ma mémoire (erreur technique côté serveur). "
            "Tu peux me redonner le contexte directement ?"
        )

    if not hits:
        if mt == MemoryType.ERROR:
            return (
                "La mémoire des erreurs n'est pas encore consultable dans cette "
                "version — elle est capturée pour le sprint d'auto-amélioration."
            )
        return (
            f"Aucun souvenir trouvé pour « {query} » (type={mt.value}). "
            "Cela peut signifier qu'on n'en a jamais parlé, ou que la "
            "formulation actuelle ne matche pas les mots utilisés à l'époque."
        )

    # Compose a prose digest — one paragraph per hit. Avoid JSON / tables.
    lines: list[str] = [
        f"J'ai retrouvé {len(hits)} souvenir{'s' if len(hits) > 1 else ''} "
        f"sur « {query} » :"
    ]
    for i, hit in enumerate(hits, 1):
        kind_label = {
            MemoryType.EPISODIC: "conversation passée",
            MemoryType.SEMANTIC_USER: "fait stable",
            MemoryType.PROCEDURAL: "procédure",
            MemoryType.CONSTRAINT: "règle",
            MemoryType.ERROR: "erreur passée",
            MemoryType.AUTO: "souvenir",
        }.get(hit.type, "souvenir")
        date_hint = ""
        if hit.created_at:
            date_hint = f" (~{hit.created_at[:10]})"
        lines.append(f"{i}. [{kind_label}{date_hint}] {hit.content}")
    return "\n".join(lines)
