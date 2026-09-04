# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/state.py
# @brief      LangGraph agent state schema
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    # google_credentials removed — credentials are kept server-side in
    # app.services.credential_store (SEC-1) and looked up by user_id at
    # tool execution time. They never travel through the graph state.
    domain: str        # routing field: "research" | "workspace" | "infra" | "general"
    model_used: str    # "slm:<model>" or "llm:<model>" — set by agent_node for feedback
    routing_score: int # IntentRouter score 0-100 — stored for Phase 2 training
    # P2 — ventilation du contexte, posée par agent_node quand la requête est
    # complète, lue par le caller qui écrit dans `usage_logs`. Voyage par
    # l'ÉTAT et non par une ContextVar : LangGraph exécute chaque nœud dans une
    # tâche asyncio distincte, et une ContextVar ne remonte jamais de l'enfant
    # vers le parent — c'est ce qui rendait #255 muet (0 ligne ventilée).
    context_breakdown: str
    # Hermes-style sticky toolset profile (Chantier 1, 2026-05-07).
    # Set once per conversation by the chat router (auto-detect on first
    # message or `/profile <name>` slash command). agent_node reads this
    # to bind the same ~30-tool catalog every turn — no per-turn keyword
    # filtering. Empty string ("") = fall back to the legacy keyword
    # filter (graceful migration: existing conversations created before
    # this column have NULL → "" → legacy behaviour).
    toolset_profile: str
    # Hermes Chantier 9 — iteration budget guard.
    # Incremented by ``agent_node`` each time it returns a response carrying
    # tool_calls (i.e. the loop will go back through ``tool_node`` and
    # bounce here for another inference). When the count crosses
    # ``MAX_AGENT_ITERATIONS`` (~80, defined in nodes.py), ``should_continue``
    # routes to ``force_summary`` instead of ``tools`` — the agent makes
    # ONE final API call WITHOUT tools and produces a textual summary so
    # the user always gets something even on tasks that exhaust the budget.
    iteration_count: int
    # L3 (28/07/2026) — nombre de relances déjà déclenchées par la
    # vérification de conformité sur ce tour. Le nœud ``verify`` confronte le
    # résultat aux exigences de la demande et, s'il manque quelque chose,
    # renvoie l'agent au travail avec l'écart nommé. Plafonné par
    # ``conformity.MAX_CONFORMITY_RETRIES`` : sans plafond, deux modèles se
    # renvoient la balle sur une exigence qu'aucun ne sait satisfaire.
    conformity_retries: int
    # Nombre d'écarts relevés au tour de vérification PRÉCÉDENT. C'est lui qui
    # décide de continuer ou d'arrêter : on ne relance que si la liste recule
    # (``conformity.is_making_progress``). Un compte identique ou en hausse
    # signifie que la reprise n'a rien apporté — insister brûlerait du budget
    # et du temps pour rien.
    conformity_gap_count: int
    # Scheduled / automated execution flag (2026-05-31).
    # Set to True by the scheduler when it runs a task prompt on the FLAT
    # (non-supervisor) graph. The supervisor routes a whole prompt to ONE
    # sub-agent, so a multi-domain scheduled prompt (e.g. a daily briefing
    # touching calendar + gmail + system) lost every tool outside the chosen
    # sub-agent's domain. When this flag is set, ``create_agent_node`` :
    #   - skips the local SLM (unattended runs need the reliable cloud tier),
    #   - always binds tools (no keyword gate), and
    #   - unions in every tool whose exact name appears in the prompt, so the
    #     agent binds all the tools it was explicitly told to call.
    # Absent / False for every interactive chat turn — no behaviour change there.
    automated_task: bool
    # 03/09/2026 — « complex » épingle le tier du tour : la boucle des
    # missions le pose, sinon `classify_complexity` (mots-clés) envoyait un
    # tour de mission sur le tier IMAGE dès qu'une page lue parlait d'image.
    # Absent pour un tour de chat : le routage par la demande reste entier.
    tier_pin: str
    # 04/09/2026 — les outils d'une MISSION : les familles choisies au premier
    # passage par le petit modèle local, plus le noyau (cf.
    # `agent.missions.outillage`). Vide ou absent = pas de restriction, tout
    # le profil. Le nœud d'outils l'élargit quand `find_tool` découvre.
    mission_tools: list[str]
