# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/session_search_tool.py
# @brief      Agent tool: cross-conversation memory recall. Sprint 1, Phase 3.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
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

from app.services.session_search import search_past_conversations

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
    """
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

    # Build a Markdown-ish digest the LLM can quote directly.
    lines: list[str] = [
        f"J'ai retrouvé {len(results)} conversation(s) passée(s) pertinente(s) "
        f"pour « {query} » :",
        "",
    ]
    for i, r in enumerate(results, 1):
        date = _format_date(r.get("date"))
        title = r.get("title") or "Conversation"
        summary = r.get("summary") or "(résumé indisponible)"
        n_matches = r.get("matched_messages", 0)
        via = r.get("via", "?")
        lines.append(f"### [{i}] {title}")
        lines.append(f"_{date} — {n_matches} message(s) correspondant(s)_")
        lines.append("")
        lines.append(summary)
        lines.append("")
        # Discreet provenance marker — helps debugging without polluting
        # the user-facing reply if the agent quotes verbatim.
        if via == "fallback":
            lines.append(
                "_(résumé limité — le contenu ci-dessus est un extrait brut, "
                "non synthétisé)_"
            )
            lines.append("")

    return "\n".join(lines).strip()
