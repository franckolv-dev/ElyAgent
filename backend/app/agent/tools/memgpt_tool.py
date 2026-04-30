# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/memgpt_tool.py
# @brief      MemGPT-style hierarchical memory tools (active recall)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""MemGPT-style memory tools — active recall via function calling.

Philosophy (inspired by MemGPT / Letta):
The LLM treats memory as an *operating system* :
    - RAM     = current context window (5-10 last messages)
    - Disk    = long-term Qdrant store (unlimited archives)
    - CPU     = the LLM itself, which issues `memory_*` tool calls to
                swap facts between RAM and Disk as needed.

Three tools exposed to the agent :
    1. `memory_archive`  — append a new durable fact
    2. `memory_search`   — semantic search over the archive
    3. `memory_recent`   — top-N last facts of a given category

Unlike the static memory injection (get_relevant_memories) which is pushed
into every prompt and inflates the token count, these tools are pulled on
demand only when the LLM decides it needs the information. This keeps the
system prompt lean — especially important for small local models (Qwen
2.5-VL 7B, Phi-4, etc.) that get confused by verbose prompts.

The three tools write/read to the same Qdrant collection (`memories`)
already used by the legacy path, so no schema migration is needed.
Categories use a dedicated payload field `category` for fast filtering.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.memory_manager import get_memory_manager

logger = logging.getLogger(__name__)


# Allowed categories — kept short to avoid model confusion on free-form input.
_ALLOWED_CATEGORIES = frozenset({
    "fact",          # factual info about the user
    "preference",    # communication style, habits
    "project",       # work/personal projects
    "contact",       # people the user mentions
    "task",          # pending or recurring tasks
    "event",         # upcoming or past events
    "constraint",    # rules the user has set
    "other",         # anything else
})


@tool
async def memory_archive(
    fact: str,
    category: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Archive un fait durable dans la mémoire long-terme (Qdrant).

    Utilise cet outil quand un fait mérite d'être RETROUVABLE plus tard via
    recherche sémantique mais n'a PAS besoin d'être injecté dans chaque prompt.
    Exemples :
    - Anniversaires, dates importantes
    - Noms de proches, collègues, projets
    - Préférences fines (ex: "préfère le café filtre")
    - Faits techniques appris en conversation

    Pour les **préférences de communication** (ton, format, emojis, langue),
    utilise plutôt `save_user_preference` — celles-ci sont injectées à chaque
    prompt automatiquement car elles doivent être appliquées partout.

    Args:
        fact: Formulation claire et complète (1-2 phrases max, <200 caractères).
        category: Une de : fact, preference, project, contact, task, event, constraint, other.
    """
    # Guard against empty / unauthenticated caller.
    if not user_id:
        return "Échec : identification utilisateur requise."
    if not fact or not str(fact).strip():
        return "Échec : le fait ne peut pas être vide."
    fact = str(fact).strip()[:400]

    cat = (str(category) if category is not None else "other").strip().lower()
    if cat not in _ALLOWED_CATEGORIES:
        cat = "other"

    try:
        memory = get_memory_manager()
        # Store via the existing memory infrastructure (embedding + FTS + Qdrant),
        # extending the payload with our MemGPT metadata (category + source).
        # `conversation_id="memgpt"` marks entries coming from active recall,
        # not from the passive extraction path.
        await memory.store_memory(
            content=fact,
            user_id=user_id,
            conversation_id="memgpt",
            extra_payload={"category": cat, "source": "memgpt_archive"},
        )
        logger.info("memory_archive: user=%s cat=%s fact=%.60s", user_id, cat, fact)
        return f"✓ Archivé (catégorie {cat}): {fact[:80]}"
    except Exception as exc:
        logger.warning("memory_archive failed: %s", exc)
        return f"Échec de l'archivage : {exc}"


def _safe_int(value, default: int, lo: int, hi: int) -> int:
    """Coerce an LLM-provided numeric arg (may be str or None) to a clamped int."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


@tool
async def memory_search(
    query: str,
    user_id: Annotated[str, InjectedToolArg],
    limit: int = 5,
) -> str:
    """Cherche dans la mémoire long-terme par similarité sémantique.

    Utilise cet outil quand tu as besoin d'un contexte que tu ne retrouves
    pas dans les derniers messages. Exemples :
    - "Quand est l'anniversaire de ma femme ?"
    - "Quel était le nom du projet dont je t'avais parlé en mars ?"
    - "Retrouve-moi les contacts liés à mon dossier X"

    La recherche est sémantique — une requête en langage naturel ramène les
    faits les plus proches, même s'ils n'utilisent pas les mêmes mots exacts.

    Args:
        query: Description libre de ce que tu cherches (en français ou anglais).
        limit: Nombre max de résultats (1-10). Défaut : 5.
    """
    if not user_id:
        return "Échec : identification utilisateur requise."
    if not query or not str(query).strip():
        return "Échec : la requête ne peut pas être vide."
    limit = _safe_int(limit, default=5, lo=1, hi=10)

    try:
        memory = get_memory_manager()
        hits = await memory.get_relevant_memories(
            query=str(query).strip(),
            user_id=user_id,
            limit=limit,
        )
        if not hits:
            return "Aucun résultat en mémoire pour cette requête."
        lines = [f"{len(hits)} résultat(s) pour « {str(query)[:60]} » :"]
        for i, fact in enumerate(hits, 1):
            lines.append(f"{i}. {fact[:200]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("memory_search failed: %s", exc)
        return f"Échec de la recherche : {exc}"


@tool
async def memory_recent(
    category: str,
    user_id: Annotated[str, InjectedToolArg],
    limit: int = 5,
) -> str:
    """Retrieve the last N archived facts in a given category.

    Useful for reviewing a category without a specific semantic query.
    Examples:
    - "What are my latest preferences?" → category="preference"
    - "List my ongoing projects" → category="project"
    - "Who are the recently mentioned contacts?" → category="contact"

    Args:
        category: One of: fact, preference, project, contact, task, event, constraint, other.
        limit: Max number of results (1-20). Default: 5.
    """
    if not user_id:
        return "Échec : identification utilisateur requise."
    cat = (str(category) if category is not None else "").strip().lower()
    if cat not in _ALLOWED_CATEGORIES:
        return (
            f"Catégorie inconnue « {category} ». "
            f"Valeurs acceptées : {', '.join(sorted(_ALLOWED_CATEGORIES))}."
        )
    limit = _safe_int(limit, default=5, lo=1, hi=20)

    try:
        import asyncio
        memory = get_memory_manager()
        # Scroll the Qdrant collection by user_id + category, newest first.
        # NOTE : `client.scroll()` is synchronous (blocking HTTP). Wrap it in
        # `asyncio.to_thread` so it does not freeze the FastAPI event loop.
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        flt = Filter(must=[
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="category", match=MatchValue(value=cat)),
        ])
        result = await asyncio.to_thread(
            memory.client.scroll,
            collection_name="memories",
            scroll_filter=flt,
            limit=limit,
            with_payload=True,
        )
        points = result[0] if result else []
        if not points:
            return f"Aucun fait archivé dans la catégorie « {cat} »."

        # Sort by created_at descending (newest first). `created_at` is now
        # always present thanks to `store_memory` writing it systematically.
        points.sort(
            key=lambda p: (p.payload or {}).get("created_at", ""),
            reverse=True,
        )
        lines = [f"{len(points)} fait(s) récent(s) dans « {cat} » :"]
        for i, p in enumerate(points, 1):
            # Real payload key is `content` (not `summary`). Display it.
            content = (p.payload or {}).get("content", "?")[:180]
            lines.append(f"{i}. {content}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("memory_recent failed: %s", exc)
        return f"Échec de la récupération : {exc}"
