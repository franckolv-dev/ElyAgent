# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_node.py
# @brief      LangGraph tool execution node — itérateur du tour. Le pipeline
#             par appel (PII, vault, HITL, ACL, empreinte, idempotence,
#             journal réversible, exécution, signaux) vit dans le Tool
#             Gateway (services/tool_gateway.py) depuis C3a.
# @license    Elastic License 2.0
# @version    1.7.1
# =============================================================================
"""Tool node — executes the tool_calls emitted by ``agent_node``.

C3a (audit 16/07 §8.3) : ce nœud ne porte plus le pipeline d'exécution — il
prépare le TOUR (tool_map fusionnée avec les outils appris, filtre PII de la
conversation, ContextVars) puis délègue chaque tool_call à la passerelle
unique :func:`app.services.tool_gateway.execute_tool_call`. Les sous-agents
et les missions migrent sur la même passerelle en C3b — aucun chemin ne doit
exécuter un outil autrement.
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState
# Compat : historiquement défini ici — des tests/le code externe l'importent
# depuis tool_node. La définition vit désormais dans la passerelle.
from app.services.tool_gateway import _MCP_SELF_GATING_TOOLS  # noqa: F401
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import SecurityFilter

logger = logging.getLogger(__name__)


async def tool_node(state: AgentState) -> dict:
    from app.skills import get_skill_registry

    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    # Sprint 4b V2 J7b.2 — make the user's promoted python_tool skills
    # dispatchable. They're bound in agent_node but aren't in the global
    # registry (per-user, by design), so without this the invoke would miss
    # them. Merged WITHOUT shadowing a builtin. No-op when the flag is off.
    from app.services.learning.learned_tools_runtime import merge_into_tool_map
    await merge_into_tool_map(tool_map, user_id)
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

    # ── PII : filtre PARTAGÉ de la conversation (audit 2026-05-07 / C0) ──
    # Le vault de placeholders est le même que celui de chat.py — la
    # passerelle s'en sert pour désanonymiser les args et ré-anonymiser
    # les résultats.
    _conv_id = state.get("conversation_id") or ""
    _vault_sf = None
    if _conv_id:
        try:
            from app.services.conversation_filters import get_filter as _get_conv_filter
            _vault_sf = _get_conv_filter(_conv_id)
        except Exception as _vault_exc:
            logger.debug("conversation filter lookup failed: %s", _vault_exc)

    # Sprint 2.7 Jalon 6 — expose the conversation_id to the orchestrate
    # tool via a ContextVar so it can re-anonymize sandbox stdout/stderr
    # using the same SecurityFilter as the rest of the pipeline. The
    # ContextVar is set once for the whole turn and is automatically
    # scoped to this coroutine (no manual reset needed — asyncio
    # propagates ContextVars per task).
    try:
        from app.agent.tools.orchestrate_tool import ORCHESTRATE_CONVERSATION_ID
        ORCHESTRATE_CONVERSATION_ID.set(_conv_id)
    except Exception as _orch_ctx_exc:  # noqa: BLE001
        logger.debug("orchestrate ContextVar set skipped: %s", _orch_ctx_exc)

    # Sprint 4b V2 (composition) — expose the current user to call_tool so a
    # composition python_tool can re-inject Google creds / user_id when it
    # invokes another tool. Set once for the turn (ContextVars are per-task).
    try:
        from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID
        LEARNED_TOOL_USER_ID.set(user_id)
    except Exception as _lt_ctx_exc:  # noqa: BLE001
        logger.debug("learned-tool ContextVar set skipped: %s", _lt_ctx_exc)

    # Substrat de confiance (P1/J4) — corrélation des événements typés du tour.
    try:
        from app.config import get_settings as _get_settings
        if _get_settings().trust_substrate_enabled:
            from app.services.event_envelope import CORRELATION_ID
            CORRELATION_ID.set(_conv_id or f"turn:{id(last_message)}")
    except Exception as _corr_exc:  # noqa: BLE001
        logger.debug("correlation id set skipped: %s", _corr_exc)

    # ── C4-4 : session replay shadow pour cette conversation ? ──────────
    # Les conv_id de replay sont synthétiques (« replay-shadow-… ») — une
    # vraie conversation ne matche jamais. Best-effort : sans le module,
    # comportement inchangé.
    _shadow = None
    try:
        from app.services.learning.replay_engine import get_shadow_session
        _shadow = get_shadow_session(_conv_id)
    except Exception as _sh_exc:  # noqa: BLE001
        logger.debug("shadow session lookup skipped: %s", _sh_exc)

    # ── Délégation à la passerelle unique (C3a) ─────────────────────────
    from app.services.tool_gateway import GatewayContext, execute_tool_call
    # Le scheduler emprunte CE MÊME nœud (graphe simple + automated_task) :
    # c'est ce drapeau — pas une surface en dur — qui distingue « un humain
    # attend » de « ça tourne sans personne ». Un tour de chat est interactif,
    # une tâche planifiée ne l'est pas et a le droit d'attendre.
    _interactive = not bool(state.get("automated_task"))

    ctx = GatewayContext(
        user_id=user_id,
        conversation_id=_conv_id,
        pii_filter=_vault_sf,
        criticality_filter=sf,
        hitl=hitl,
        memory=memory,
        shadow_results=_shadow,
        interactive=_interactive,
    )
    for tool_call in last_message.tool_calls:
        results.append(await execute_tool_call(ctx, tool_call, tool_map))

    return {"messages": results}
