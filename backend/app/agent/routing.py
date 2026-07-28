# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/routing.py
# @brief      Sprint refactor nodes.py Phase 2.1 — LangGraph routing
#             decision + iteration budget (Hermes Chantier 9).
# @license    Elastic License 2.0
# @version    1.7.1
# =============================================================================
"""Iteration budget — Hermes Chantier 9.

Why
---
On heavy multi-step tasks ("audit my last 30 days of mail and group by
category"), the agent can chain 25-50 tool calls. LangGraph's
``recursion_limit=100`` (set in chat.py) caps the loop, but when it's hit
it raises a hard exception → the user sees a generic error and the
whole conversation context is lost.

Hermes solution : count loops, and at ~80 iterations FORCE a final API
call without tools, asking the model "summarise what you did so far,
don't call any more tools". This guarantees the user always receives
textual output even on overrun tasks.

Numbers
-------
- ``MAX_AGENT_ITERATIONS = 80``  → trigger force_summary (counted in
  tool-calling *iterations*).
- ``CHAT_RECURSION_LIMIT`` → LangGraph hard cap, counted in *super-steps*.
  One iteration = agent_node + tool_node = 2 super-steps, so the cap is
  derived as ``MAX_AGENT_ITERATIONS * 2 + margin`` to guarantee
  force_summary fires BEFORE the cap raises GraphRecursionError.

  Bug fixed 2026-06-01 : the cap was hardcoded to 100 in chat.py while
  MAX_AGENT_ITERATIONS was 80. Since 80 iterations ≈ 160 super-steps, the
  100-step cap tripped at ~iteration 50 — long before force_summary's 80.
  A long web-research loop therefore crashed with « Une erreur interne est
  survenue » instead of degrading gracefully into a final summary.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


MAX_AGENT_ITERATIONS: int = 80


# ──────────────────────────────────────────────────────────────────────
# Branchement des outils
# ──────────────────────────────────────────────────────────────────────
#
# Historiquement dans la closure de ``create_agent_node``, avec cette règle :
# les outils n'étaient bindés que sur tier COMPLEX, ou si la demande matchait
# une regex de mots-clés. Justification d'origine : « the supervisor already
# routes tool-needing queries to sub-agents ». Le superviseur a été supprimé
# (mono-agent depuis le 26/07/2026) — la justification est tombée avec lui.
#
# La regex, elle, a été patchée à répétition, chaque fois après un incident
# du même type. Ses propres commentaires en portent l'aveu : « the LLM said
# "I have no tool for that" while browser_history_search … were sitting right
# there ». ``convertis`` et ``transforme`` n'y ont jamais figuré — la demande
# « Convertis ce PDF en Word » n'avait donc AUCUN outil branché.
#
# Depuis que ``classify_complexity`` rend COMPLEX pour toute demande
# utilisateur, la regex ne décide plus rien sur le chat. Elle reste le filet
# des appelants qui passent un autre tier (IMAGE : « génère une image et
# envoie-la par mail » doit garder ses outils).
#
# Promue ici en constante de module : c'est ce que réclamait le commentaire
# de ``tests/test_tool_kw_regex.py`` — « the regex should be promoted to a
# module-level constant and this test can use a direct import instead ».
TOOL_KEYWORDS: re.Pattern[str] = re.compile(
    r"\b("
    # Verbes d'action explicites
    r"envoie|envoy|crée|liste|cherche|recherche|trouve|génère|"
    r"exécute|lance|planifie|programme|enregistre|sauvegarde|"
    r"supprime|archive|copie|déplace|renomme|partage|"
    # Verbes de lecture / consultation / navigation
    r"regarde|regard|consulte|vérifie|vérific|verifie|ouvre|navigue|"
    r"affiche|montre|résume|résum|read|lis"
    # Domaines métiers
    r"|mail|email|courriel|calendrier|agenda|rendez.?vous|rdvs?|"
    r"réunions?|meetings?|drive|sheet|doc|tâche|rappel|note|"
    r"fichier|capture|screenshot|météo|news|traduis"
    # Réseaux sociaux + apps grand public
    r"|réseau(x)?\s*sociau(x)?|reseau(x)?\s*sociau(x)?|"
    r"social[\s-]*media|profil|profile|"
    r"linkedin|mastodon|twitter|x\.com|instagram|insta|"
    r"facebook|threads|bluesky|tiktok|youtube|"
    r"abonn[ée]s?|follower|followers|mention|mentions|"
    r"post|posts|tweet|tweets|publication|publications|"
    r"notif|notifs|notification|notifications|"
    # Sites de service souvent croisés
    r"doctolib|sncf|booking|amazon|leboncoin"
    # Chrome v2 read-only inspectors (Sprint 0.7, 2026-05-26).
    r"|historique|navigation|visit[eéès]?|"
    r"signets?|favori|favoris|bookmark|bookmarks|"
    r"t[ée]l[ée]charg\w*|download|downloads|"
    r"chrome|navigateur|browser|"
    # "site"/"sites" seul est trop générique (matche « le site de la
    # marque ») : on exige un voisin orienté navigation.
    r"sites?\s+(visit|web|internet|consult|all[ée]s?|fr[ée]quent)"
    r")\b",
    re.IGNORECASE,
)


def should_bind_tools(
    tier,
    *,
    has_profile: bool,
    automated_task: bool,
    user_query: str,
) -> bool:
    """Faut-il montrer ses outils au modèle pour ce tour ?

    Un profil collant branche toujours ses outils, même sur du bavardage : le
    modèle a besoin de voir le même catalogue à chaque tour pour l'apprendre
    (motif Hermes, Chantier 1). Une tâche automatisée aussi — sans quoi le
    briefing quotidien redit « outil non disponible » (régression 2026-05-31).

    Args:
        tier: le ``ComplexityTier`` retenu pour ce tour.
        has_profile: un ``toolset_profile`` est collé à la conversation.
        automated_task: tour lancé par le planificateur, pas par un humain.
        user_query: la demande, pour le filet de mots-clés.

    Returns:
        True s'il faut appeler ``bind_tools``.
    """
    from app.services.llm_provider import ComplexityTier

    if has_profile or automated_task:
        return True
    if tier == ComplexityTier.COMPLEX:
        return True
    return bool(user_query and TOOL_KEYWORDS.search(user_query))

# LangGraph's recursion_limit counts GRAPH SUPER-STEPS, not iterations.
# Derive it so force_summary (which fires at MAX_AGENT_ITERATIONS
# *iterations* ≈ 2× that in super-steps) is always reachable before the
# hard cap. See the module docstring for the 2026-06-01 incident.
_RECURSION_SAFETY_MARGIN: int = 20
CHAT_RECURSION_LIMIT: int = MAX_AGENT_ITERATIONS * 2 + _RECURSION_SAFETY_MARGIN


def should_continue(state: AgentState) -> str:
    """Routing decision after agent_node :
    - "force_summary" if the iteration budget is exhausted (Chantier 9)
    - "tools" if the model emitted tool_calls
    - "verify" if the turn produced something to confront to the request
    - "end" otherwise (final textual answer)

    ``verify`` s'intercale entre la dernière réponse et la fin du tour : le
    résultat est confronté à la demande, et l'agent est relancé avec les
    écarts nommés s'il n'y répond pas (cf. ``app.agent.conformity``). Un tour
    tronqué par ``force_summary`` n'y passe pas : il n'a rien à relancer, il a
    déjà épuisé son budget.
    """
    last_message = state["messages"][-1]
    iter_count = state.get("iteration_count", 0)

    if (
        isinstance(last_message, AIMessage)
        and last_message.tool_calls
        and iter_count >= MAX_AGENT_ITERATIONS
    ):
        logger.warning(
            "[iteration_budget] count=%d ≥ %d — forcing final summary "
            "without tools (Chantier 9)",
            iter_count, MAX_AGENT_ITERATIONS,
        )
        return "force_summary"

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    from app.agent.conformity import should_verify_conformity

    if should_verify_conformity(state):
        return "verify"
    return "end"
