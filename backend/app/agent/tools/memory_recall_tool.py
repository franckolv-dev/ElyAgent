# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/memory_recall_tool.py
# @brief      Unified `memory_recall(type, query)` tool — Sprint 2.5 Jalon 3.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
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

from app.services.memory.recall_service import (
    UnreadableMemoryType,
    get_memory_recall_service,
)
from app.services.memory.types import MemoryType
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


# `error` n'est PAS annoncé : écriture seule. L'annoncer poussait le modèle à
# l'interroger, et à lire la réponse vide comme « je n'ai jamais échoué
# là-dessus ». MemoryType.parse l'accepte encore (données existantes) — la
# réponse dit alors franchement que la mémoire n'est pas consultable.
#
# `procedural` est de retour (02/08) : il a désormais une lecture, servie par
# le registre d'outils via find_tool.
_VALID_TYPES_TEXT = (
    "episodic | semantic_user | procedural | constraint | auto"
)


@register(
    domain=Domain.MEMORY,
    skill_name="memory_recall_unified",
    skill_display_name="Mémoire unifiée multi-typée",
    skill_description=(
        "Recall typé sur la mémoire cognitive d'ELY (épisodique, sémantique-user, "
        "procédurale, contraintes). API unique remplaçant à terme les "
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
    - **procedural**     : HOW to do something — which of your own tools
                          covers a need ("how do I send an email?" →
                          ``gmail_send_email``). Read from the tool catalog,
                          so it is never out of date. The tools it names
                          become callable for the rest of the conversation.
    - **constraint**     : user-imposed security rules
                          ("never delete without asking").
    - **auto**           : fan out across episodic, semantic_user and
                          constraint, merging by score. ``procedural`` is
                          NOT in the fan-out — ask for it explicitly.

    One type exists but is NOT readable: ``error`` (write-only). Asking for it
    returns an explicit message, not an empty list — the distinction avoids
    concluding "nothing in memory" when the truth is "no read path".

    Args:
        query: free-text describing what you want to remember.
        memory_type: one of (``episodic | semantic_user | procedural |
                     constraint | auto``). Default ``auto``.
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
    except UnreadableMemoryType:
        # V0-5 — dire « ça ne se lit pas », jamais « il n'y a rien ». La
        # seconde formulation est une affirmation sur le monde que rien ne
        # justifie.
        return (
            f"Ce type de mémoire ({mt.value}) n'est pas consultable : rien ne "
            "le relit dans cette version. Ne conclus pas qu'il n'y a rien à "
            "s'en souvenir — je n'ai simplement aucun moyen de le savoir. "
            "Essaie episodic, semantic_user, constraint ou auto."
        )
    except Exception as exc:
        logger.warning("memory_recall failed: %s", exc, exc_info=True)
        return (
            "Je n'ai pas pu interroger ma mémoire (erreur technique côté serveur). "
            "Tu peux me redonner le contexte directement ?"
        )

    if not hits:
        if mt == MemoryType.PROCEDURAL:
            # Message DISTINCT : « aucun souvenir » n'a aucun sens ici. Un
            # catalogue muet dit « aucun outil ne couvre ça », ce qui appelle
            # report_missing_capability — pas « on n'en a jamais parlé ».
            return (
                f"Aucun outil du catalogue ne couvre « {query} ». Si le besoin "
                "est réel, signale-le avec report_missing_capability plutôt que "
                "de conclure que c'est impossible."
            )
        return (
            f"Aucun souvenir trouvé pour « {query} » (type={mt.value}). "
            "Cela peut signifier qu'on n'en a jamais parlé, ou que la "
            "formulation actuelle ne matche pas les mots utilisés à l'époque."
        )

    if mt == MemoryType.PROCEDURAL:
        # Nommer un outil sans le rendre appelable serait une façade : le
        # modèle lirait « gmail_send_email existe », l'appellerait, et ne le
        # trouverait pas dans son profil bindé. `find_tool` enregistre ses
        # trouvailles pour qu'`agent_node` les binde au tour suivant ; la
        # procédurale sert le MÊME classement, elle doit donc le faire aussi.
        try:
            from app.agent.discovered_tools import add_discovered
            from app.agent.tool_context import CURRENT_CONVERSATION_ID

            names = [
                h.metadata["tool_name"] for h in hits if h.metadata.get("tool_name")
            ]
            add_discovered(CURRENT_CONVERSATION_ID.get(), names)
        except Exception as exc:  # noqa: BLE001 — jamais casser le tour
            logger.debug("memory_recall: binding collant impossible: %s", exc)

    # Compose a prose digest — one paragraph per hit. Avoid JSON / tables.
    lines: list[str] = [
        f"J'ai retrouvé {len(hits)} souvenir{'s' if len(hits) > 1 else ''} "
        f"sur « {query} » :"
    ]
    for i, hit in enumerate(hits, 1):
        kind_label = {
            MemoryType.EPISODIC: "conversation passée",
            MemoryType.SEMANTIC_USER: "fait stable",
            MemoryType.PROCEDURAL: "outil disponible",
            MemoryType.CONSTRAINT: "règle",
            MemoryType.ERROR: "erreur passée",
            MemoryType.AUTO: "souvenir",
        }.get(hit.type, "souvenir")
        date_hint = ""
        if hit.created_at:
            date_hint = f" (~{hit.created_at[:10]})"
        lines.append(f"{i}. [{kind_label}{date_hint}] {hit.content}")
    return "\n".join(lines)
