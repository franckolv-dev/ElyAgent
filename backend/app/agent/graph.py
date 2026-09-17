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
# =============================================================================
"""Agent graph — builds and returns the compiled LangGraph.

Un seul agent, un graphe plat :
  agent → tools → agent → verify → fin
                             └─ écarts → agent
  budget d'itérations épuisé → force_summary → fin

Le superviseur et ses spécialistes ont existé et ont été retirés après un
banc A/B (voir ``docs/architecture.md``). ``build_agent_graph()`` est l'API
publique ; ``build_simple_agent_graph()`` est le même graphe, gardé sous son
nom historique pour les appelants qui le construisent eux-mêmes.
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


class CompteGoogleDeconnecte(RuntimeError):
    """Une tâche sans humain a besoin de Google, et le compte est déconnecté."""


def route_after_tools(state: AgentState) -> str:
    """Après les outils : on retourne à l'agent, sauf compte Google déconnecté
    pendant une tâche AUTOMATISÉE.

    « Traitement factures » (17/09/2026) : jeton révoqué dès la première
    action, puis cinq minutes de contournements par le navigateur jusqu'à
    « Recursion limit of 60 ». Personne ne lit une tâche planifiée pendant
    qu'elle tourne ; la laisser chercher une autre porte brûle du temps et des
    tokens pour un résultat qui ne peut pas arriver. En CHAT on ne coupe pas :
    quelqu'un lit, le conseil de reprise suffit, et le reste de la demande
    peut encore être traité.
    """
    if not state.get("automated_task"):
        return "agent"
    from langchain_core.messages import ToolMessage

    from app.agent.recovery import dit_compte_google_deconnecte

    for message in reversed(state.get("messages") or []):
        if not isinstance(message, ToolMessage):
            break   # on ne regarde que les retours des outils qui viennent de tourner
        if dit_compte_google_deconnecte(message.content):
            return "compte_deconnecte"
    return "agent"


async def compte_deconnecte_node(state: AgentState) -> dict:
    """Arrête la tâche en LEVANT : le planificateur écrit ``Erreur: {exc}`` sur
    la tâche, et c'est ce texte que la page affiche."""
    from app.agent.recovery import MESSAGE_COMPTE_GOOGLE_DECONNECTE

    raise CompteGoogleDeconnecte(MESSAGE_COMPTE_GOOGLE_DECONNECTE)


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
        {"agent": "agent", "tools": "tools", "end": END},
    )
    graph.add_node("compte_deconnecte", compte_deconnecte_node)
    graph.add_conditional_edges(
        "tools",
        route_after_tools,
        {"agent": "agent", "compte_deconnecte": "compte_deconnecte"},
    )
    graph.add_edge("compte_deconnecte", END)
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
