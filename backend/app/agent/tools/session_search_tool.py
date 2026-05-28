# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/session_search_tool.py
# @brief      Agent tool: cross-conversation memory recall. Sprint 1, Phase 3.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Expose ``search_past_conversations`` to the agent as a LangChain tool.

This is the user-facing layer of Sprint 1 — Memory recall. The agent
can now answer questions like:

    « tu te souviens de ce qu'on s'est dit sur Bestway ? »
    « on en était où avec Doctolib la semaine dernière ? »
    « qu'est-ce que j'avais validé sur la roadmap ? »

…by calling this tool, getting back 1-3 conversation summaries (with
date, title, focused summary), and weaving them into its reply.

Implementation notes
--------------------
- Backed entirely by ``app.services.session_search`` (Phase 1 + 2).
- The summariser runs on the SIMPLE tier (Ministral 3B local in
  Franck's default setup) — coût marginal LLM zéro pour cette
  capacité, ce qui débloque son usage agressif par l'agent sans peur
  de gonfler la facture.
- The output is a Markdown-formatted string, ready to be quoted by
  the agent in its own reply. We deliberately avoid JSON output here:
  agents stitch human prose better than they juggle JSON.
- ``user_id`` is injected by the agent runtime via ``InjectedToolArg``
  so the LLM never sees / cannot tamper with the scope of the search.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.services.memory._deprecated import log_deprecation
from app.services.session_search import search_past_conversations
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


def _format_date(iso_str: str | None) -> str:
    """ISO datetime → user-friendly French short date.

    Falls back to the raw string if parsing fails — better than crashing
    the tool on a stale row.
    """
    if not iso_str:
        return "date inconnue"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str)
        # Months in French (1..12)
        months = ["", "janvier", "février", "mars", "avril", "mai", "juin",
                  "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        return f"{dt.day} {months[dt.month]} {dt.year}"
    except Exception:
        return iso_str


@register(
    domain=Domain.MEMORY,
    skill_name="memory_recall",
    skill_display_name="Mémoire transversale entre conversations",
    skill_description=(
        "Recherche dans tout l'historique des conversations passées du user, "
        "groupe par session, charge le contexte autour des matchs et résume "
        "chaque conversation pertinente via un LLM local. Permet à l'agent de "
        "se souvenir de discussions précédentes sans que le user ait à les "
        "réintroduire en contexte."
    ),
    skill_icon="🧭",
    enabled_by_default=True,
)
@tool
async def search_past_conversations_tool(
    query: str,
    user_id: Annotated[str, InjectedToolArg] = "",
    limit: int = 3,
) -> str:
    """Search across the user's past conversations and summarise the most relevant ones.

    USE THIS TOOL WHENEVER the user references a previous discussion,
    asks "do you remember…", "what did we say about…", "what was the
    outcome of…", or otherwise implies that the answer lives in their
    conversation history rather than in the current turn.

    The tool searches the user's entire history (every conversation
    they've ever had with ELY), groups the matches by conversation,
    and returns 1-3 focused summaries — each with a title, a date, and
    a 2-4 sentence recap focused on the query. Powered by a local LLM
    (Ministral 3B on the user's hardware in the default setup), so
    coût marginal is zero — feel free to call it whenever it might help.

    Examples of when to call:
        - "tu te souviens de ce qu'on s'est dit sur Bestway ?"
        - "on en était où avec Doctolib la semaine dernière ?"
        - "what did we conclude about the roadmap?"
        - "did we already discuss this project ?"

    Examples of when NOT to call:
        - The query is purely about something happening *right now*
          ("envoie un mail à Alice") — no history needed.
        - The query is about facts/knowledge stored in the user's
          documents (use ``knowledge_search`` instead) or in their
          structured memory (use ``memory_search`` instead).

    Args:
        query: free-text describing what to look for in past conversations.
            Use the user's own words when possible — the FTS layer is
            tolerant to accents, conjugations and short forms.
        limit: how many past conversations to summarise. 3 is the default
            and rarely needs to change.

    Returns: a Markdown-formatted string with 1-3 sections, one per
        retrieved conversation. Empty string-equivalent "Aucune
        conversation passée pertinente trouvée." when nothing matches.

    Le retour est un paragraphe de prose conversationnelle directement
    quotable par toi (en français, déjà rédigé). Tu peux :
      - le citer tel quel
      - ou le paraphraser pour mieux coller à la question
    Pas de structure, pas de champs nommés, pas de blocs de code dans
    le retour : c'est délibéré pour que tu n'aies pas la tentation de
    le restructurer.

    Sprint 2.5 Jalon 7 — DEPRECATED : ce tool deviendra un alias de
    `memory_recall(memory_type="episodic")` en V2, quand l'EpisodicStore
    couvrira l'historique complet des messages (et plus seulement les
    Q&A pairs). En attendant, ce tool reste le plus mature pour la
    recherche cross-conversation.
    """
    log_deprecation("search_past_conversations_tool", successor="memory_recall")
    if not user_id:
        return "Erreur interne : user_id manquant."
    if not query or not query.strip():
        return "Erreur : la requête est vide. Précise ce que tu cherches dans les conversations passées."

    try:
        results = await search_past_conversations(
            user_id=user_id,
            query=query,
            limit=max(1, min(limit, 5)),  # safety clamp
        )
    except Exception as exc:
        logger.warning(
            "search_past_conversations_tool: service raised %s — returning user-friendly error",
            exc,
        )
        return (
            "Je n'ai pas pu interroger ma mémoire des conversations passées "
            "(erreur technique côté serveur). Tu peux me redonner le contexte ?"
        )

    if not results:
        return (
            f"Aucune conversation passée pertinente trouvée pour « {query} ». "
            "Cela peut signifier soit qu'on n'en a jamais parlé, soit que la "
            "formulation actuelle ne matche pas les mots-clés utilisés à "
            "l'époque — tu peux reformuler avec d'autres termes."
        )

    # Build a conversational, prose-only digest. NO Markdown headings,
    # NO ``` code fences, NO key:value structure — anything that looks
    # "structured" tempts the calling LLM (DeepSeek-v4-pro especially)
    # to re-serialise the tool result as a JSON card in its reply to
    # the user. Model-agnostic fix: speak in narrative.
    n = len(results)
    if n == 1:
        opener = f"J'ai retrouvé une conversation passée à propos de « {query} »."
    else:
        opener = f"J'ai retrouvé {n} conversations passées à propos de « {query} »."

    sentences: list[str] = [opener]
    for i, r in enumerate(results, 1):
        date = _format_date(r.get("date"))
        title = (r.get("title") or "Conversation").strip().rstrip(".")
        summary = (r.get("summary") or "(résumé indisponible)").strip()

        # Connector word — keeps the paragraph flowing naturally
        if n == 1 or i == 1:
            connector = "D'abord" if n > 1 else "Voilà"
        elif i == n:
            connector = "Et enfin"
        else:
            connector = "Ensuite"

        sentences.append(
            f"{connector}, le {date}, on a parlé de « {title} » : {summary}"
        )

    return " ".join(sentences)
