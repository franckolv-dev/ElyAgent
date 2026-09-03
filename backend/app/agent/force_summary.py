# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/force_summary.py
# @brief      Sprint refactor nodes.py Phase 2.2 — final inference node
#             without tools, used when the iteration budget is exhausted
#             (Hermes Chantier 9).
# @license    MIT
# @version    1.7.1
# =============================================================================
"""Force summary node — Hermes Chantier 9.

Reached when ``iteration_count`` crosses ``MAX_AGENT_ITERATIONS`` (80).
The agent has burned its tool-call budget without converging, so we
do one last LLM call **without binding any tool** and ask the model to
summarise what it has done + what's missing + how the user can resume.
Guarantees the user always receives textual output even on overruns.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.agent.helpers.message_sanitizer import _sanitize_messages_for_mistral
from app.agent.routing import MAX_AGENT_ITERATIONS
from app.services.llm_deadline import ainvoke_with_deadline
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


async def force_summary_node(state: AgentState) -> dict:
    """Final inference WITHOUT tools, prompting the model to summarise
    what it has done so far. Reached when ``iteration_count`` crosses
    ``MAX_AGENT_ITERATIONS``.

    Strategy
    --------
    - Build the same system prompt + history as ``agent_node`` would, but
      DO NOT call ``bind_tools`` — the LLM physically cannot emit tool_calls.
    - Append a final user message that explicitly asks for a textual
      summary of the work done.
    - Return the resulting AIMessage as the conversation output.
    """
    messages = state["messages"]
    iter_count = state.get("iteration_count", 0)

    logger.warning(
        "[force_summary] entering : conv=%s iter=%d/%d, building summary…",
        (state.get("conversation_id", "") or "")[:8],
        iter_count,
        MAX_AGENT_ITERATIONS,
    )

    # Re-derive the user's original query to pick the right tier
    _last_human = next(
        (m for m in reversed(messages) if isinstance(m, HumanMessage)),
        None,
    )
    user_query = ""
    if _last_human is not None:
        _content = _last_human.content
        if isinstance(_content, str):
            user_query = _content
        elif isinstance(_content, list):
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _content
            )

    from app.services.llm_provider import (
        ComplexityTier,
        classify_complexity,
        get_llm_for_tier,
    )
    _tier = classify_complexity(user_query) if user_query else ComplexityTier.MEDIUM
    llm = get_llm_for_tier(_tier)

    # Append a strict instruction. We use a HumanMessage rather than a
    # SystemMessage to avoid Mistral's "single system message" constraint.
    forcing_msg = HumanMessage(content=(
        "[Système — limite d'itérations atteinte]\n\n"
        "Tu as utilisé toutes les itérations disponibles pour cette demande "
        f"({iter_count}/{MAX_AGENT_ITERATIONS} appels d'outils). N'appelle "
        "AUCUN nouvel outil. Donne maintenant à l'utilisateur, en français "
        "et en texte clair :\n"
        "1. Ce que tu as fait jusqu'ici (étapes complétées)\n"
        "2. Ce qu'il restait à faire\n"
        "3. Ce que l'utilisateur peut faire pour reprendre (ex : reformuler "
        "la demande de façon plus ciblée, scinder en plusieurs requêtes)\n\n"
        "Ne PROMETS pas d'action future, ne génère AUCUN tool_call, "
        "termine ta réponse par un point."
    ))

    _sanitized = _sanitize_messages_for_mistral(list(messages) + [forcing_msg])
    try:
        response = await ainvoke_with_deadline(llm, _sanitized, surface="force-summary")
        logger.warning(
            "[force_summary] success : produced %d chars of summary",
            len(getattr(response, "content", "") or ""),
        )
    except Exception as exc:
        # Even the summary call failed (network, billing…). Return a
        # synthesised AIMessage so the graph terminates cleanly.
        logger.error("[force_summary] failed (%s) — emitting fallback text", exc)
        from langchain_core.messages import AIMessage as _AIMessage
        response = _AIMessage(content=(
            f"J'ai atteint la limite de {MAX_AGENT_ITERATIONS} appels "
            "d'outils sur cette tâche et je n'ai pas pu produire de résumé "
            "automatiquement. Reformule ta demande en plusieurs étapes plus "
            "ciblées, ça aboutira plus rapidement."
        ))

    # Ce nœud clôt le tour au même titre que le nœud agent. Quand on arrive
    # ici, TOUTES les réponses du nœud agent portaient des ``tool_calls`` —
    # aucune n'a donc déclenché d'extraction de faits. Sans cet appel, un tour
    # qui épuise son budget d'itérations n'alimenterait jamais la mémoire.
    # La réponse produite ici ne porte jamais de ``tool_calls`` (l'appel se
    # fait sans ``bind_tools``, et le repli est un AIMessage textuel).
    from app.services.memory_service import maybe_spawn_fact_extraction

    maybe_spawn_fact_extraction(state.get("user_id", ""), messages, response)
    return {"messages": [response]}
