# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/memgpt_tool.py
# @brief      MemGPT-style hierarchical memory tools (active recall)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
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

Sprint 2.5 Jalon 4 — explicit write routing
-------------------------------------------
`memory_archive` now writes via `get_semantic_user_store().store_fact(...)`
instead of the legacy `MemoryManager.store_memory(...)`. Routing is
visible at the call site. See ``app/services/memory/ROUTING.md``.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.memory import get_semantic_user_store
from app.services.memory._deprecated import log_deprecation
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
    """Enregistre DURABLEMENT une information que l'utilisateur demande de retenir.

    C'EST L'OUTIL À APPELER dès que l'utilisateur dit « retiens », « enregistre »,
    « souviens-toi », « mémorise », « garde en mémoire », « note pour plus tard »
    à propos d'une information factuelle. RÈGLE ABSOLUE : ne JAMAIS confirmer
    qu'une information est enregistrée sans avoir réellement appelé cet outil
    dans ce tour — une confirmation sans appel est un mensonge à l'utilisateur.

    Exemples de déclencheurs :
    - "Retiens mes profils sociaux : https://linkedin.com/in/x et https://x.com/y"
      → UN appel PAR profil, category="contact"
        (fact="Profil LinkedIn de l'utilisateur : https://linkedin.com/in/x")
    - "Souviens-toi que mon médecin est Dr Martin (doctolib.fr/...)" → category="contact"
    - "Mémorise que le serveur de prod s'appelle atlas" → category="fact"
    - "Mon anniversaire est le 12 mars, retiens-le" → category="event"
    - "Garde en mémoire que je préfère le café filtre" → category="preference"

    L'information devient RETROUVABLE dans toutes les conversations futures
    (via `memory_search`). Si l'utilisateur redonne une information déjà
    archivée, ré-archiver est sans danger (déduplication automatique).

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
        # Sprint 2.5 Jalon 4 — routing explicite:
        #     MemoryType  = SEMANTIC_USER (kind=fact)
        #     Store       = SemanticUserStore.store_fact
        #     Collection  = Qdrant `memories` (λ=0.01, ~69-day half-life)
        #     Rationale   = stable user knowledge, retrievable on demand
        # `conversation_id="memgpt"` marks entries coming from active recall,
        # not from the passive extraction path.
        await get_semantic_user_store().store_fact(
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


@tool
async def memory_view_profile(
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Affiche ce qui est enregistré en mémoire permanente sur l'utilisateur.

    Utilise cet outil quand l'utilisateur demande « affiche mes préférences »,
    « qu'est-ce que tu sais de moi ? », « montre ce que tu as retenu »,
    « vérifie que c'est bien enregistré ». C'est le moyen de PROUVER à
    l'utilisateur ce qui est réellement stocké — ne jamais répondre de
    mémoire à ces questions, toujours appeler cet outil.

    Retourne les préférences permanentes (injectées à chaque conversation).
    Pour retrouver un FAIT archivé précis (URL, contact, date…), utilise
    `memory_search` avec une requête ciblée.
    """
    if not user_id:
        return "Échec : identification utilisateur requise."
    try:
        prefs = await get_semantic_user_store().get_preferences(user_id, limit=50)
    except Exception as exc:
        logger.warning("memory_view_profile failed: %s", exc)
        return f"Échec de la lecture du profil : {exc}"
    if not prefs:
        return "Aucune préférence permanente enregistrée pour le moment."
    lines = "\n".join(f"- {p}" for p in prefs)
    return f"Préférences permanentes enregistrées ({len(prefs)}) :\n{lines}"


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
    """[DEPRECATED — utilise `memory_recall(query, memory_type="semantic_user")`]
    Cherche dans la mémoire long-terme par similarité sémantique.

    Sprint 2.5 Jalon 7 : ce tool reste fonctionnel pour la rétrocompat
    mais sera supprimé en V2. Le tool `memory_recall` couvre le même
    besoin avec une API typée explicite.

    Args:
        query: Description libre de ce que tu cherches (en français ou anglais).
        limit: Nombre max de résultats (1-10). Défaut : 5.
    """
    log_deprecation("memory_search", successor="memory_recall")
    if not user_id:
        return "Échec : identification utilisateur requise."
    if not query or not str(query).strip():
        return "Échec : la requête ne peut pas être vide."
    limit = _safe_int(limit, default=5, lo=1, hi=10)

    # Sprint 2.5 Jalon 7 — delegation to the new unified API. Single
    # source of truth for "what does recall mean", legacy formatting kept
    # on this tool's surface for stability of the LLM-visible output.
    try:
        from app.services.memory import get_memory_recall_service, MemoryType
        hits = await get_memory_recall_service().recall(
            memory_type=MemoryType.SEMANTIC_USER,
            query=str(query).strip(),
            user_id=user_id,
            limit=limit,
        )
        facts = [h.content for h in hits if h.metadata.get("kind") != "preference"]
        if not facts:
            return "Aucun résultat en mémoire pour cette requête."
        lines = [f"{len(facts)} résultat(s) pour « {str(query)[:60]} » :"]
        for i, fact in enumerate(facts, 1):
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
    """[DEPRECATED — utilise `memory_recall(memory_type="semantic_user")`]
    Retrieve the last N archived facts in a given category.

    Sprint 2.5 Jalon 7 : ce tool reste fonctionnel pour la rétrocompat
    mais sera supprimé en V2 ou V3. Le category-filter exact n'est pas
    encore couvert par `memory_recall` (prévu V2), donc on garde ce tool
    en attendant.

    Args:
        category: One of: fact, preference, project, contact, task, event, constraint, other.
        limit: Max number of results (1-20). Default: 5.
    """
    log_deprecation("memory_recent", successor="memory_recall")
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
