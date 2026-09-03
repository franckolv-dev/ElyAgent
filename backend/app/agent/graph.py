# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/graph.py
# @brief      Agent graph — builds and returns the compiled LangGraph
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Agent graph — builds and returns the compiled LangGraph.

The supervisor-based multi-agent architecture is used by default:
  router → {research | workspace | infra | general} → tools → (loop)

The old single-agent graph is kept as ``build_simple_agent_graph()`` for
testing and for channels (Telegram, scheduler) that build their
own graph instance and may want the simpler version.

``build_agent_graph()`` is the public API used by all callers.
"""
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.conformity import conformity_node, route_after_conformity
from app.agent.nodes import (
    create_agent_node,
    force_summary_node,
    should_continue,
    tool_node,
)


def build_simple_agent_graph() -> StateGraph:
    """Single-agent graph (original architecture).

    Useful for unit tests or when the supervisor overhead is not desired.

    Hermes Chantier 9 — adds the ``force_summary`` terminal node : when the
    iteration counter crosses ``MAX_AGENT_ITERATIONS``, ``should_continue``
    routes here instead of ``tools``. The agent makes one final API call
    without bound tools and returns a textual summary, then ends. This
    guarantees the user always receives output even on tasks that would
    otherwise hit LangGraph's recursion limit.
    """
    graph = StateGraph(AgentState)
    graph.add_node("agent", create_agent_node())
    graph.add_node("tools", tool_node)
    graph.add_node("force_summary", force_summary_node)
    # L3 — le résultat est confronté à la demande avant de rendre la main.
    # Conforme → END ; écart nommé → retour à ``agent`` avec la consigne.
    # ``force_summary`` ne passe PAS par là : un tour qui a épuisé son budget
    # d'itérations n'a rien à relancer.
    graph.add_node("verify", conformity_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "force_summary": "force_summary",
            "verify": "verify",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "verify",
        route_after_conformity,
        {"agent": "agent", "end": END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("force_summary", END)
    return graph.compile()


def build_agent_graph() -> StateGraph:
    """Graphe d'agent de production — un seul runtime (V1, 26/07).

    Historiquement, cette fonction rendait le graphe du SUPERVISEUR : un
    routeur classait la demande puis la confiait à l'un de 8 spécialistes.
    Le banc A/B (#248) a mesuré les deux architectures sur 20 demandes
    réellement formulées par les utilisateurs :

        tier B   p50 1 657 ms (mono) contre 2 713 ms — choix d'outil 85 / 78 %
        tier A   p50 3 431 ms        contre 13 082 ms — choix d'outil 100 / 62 %

    Le mono-agent gagne sur les quatre critères. Et la prémisse d'origine
    s'est révélée inversée : le superviseur avait été introduit pour soulager
    le tier A local, c'est là qu'il coûtait le plus cher — l'appel de routage
    tourne lui aussi sur le modèle local.

    Depuis le temps 1 (#249), toutes les surfaces passaient déjà un
    ``toolset_profile`` qui court-circuitait le routeur : les 8 branches de
    dispatch étaient enregistrées mais jamais entrées. Elles ont été
    supprimées avec ``supervisor.py`` et ``sub_agents/`` (~2 800 lignes).

    ``delegate`` reste : c'est un OUTIL de sous-tâches parallèles, pas une
    architecture.
    """
    return build_simple_agent_graph()
