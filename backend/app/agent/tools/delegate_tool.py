# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/delegate_tool.py
# @brief      Tool ``delegate`` — délégation parallèle de sous-tâches
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tool ``delegate`` — exécute plusieurs sous-tâches indépendantes EN PARALLÈLE.

Inspiré de ``delegate_task`` de Hermes Agent, adapté à ELY. Au lieu de threads
+ sous-agents isolés, on réutilise le graphe agent existant d'ELY en mode
**autonome** (``automated_task=True`` — le même chemin que les tâches
planifiées) lancé via ``asyncio.gather`` (ELY est full-async). Seuls les
**résumés** des enfants remontent au contexte du parent.

Invariants de sécurité :
  - Chaque enfant tourne en mode autonome → les outils irréversibles
    (``NEVER_AUTONOMOUS_TOOLS`` : envoi mail, suppression, SSH…) sont
    **bloqués** dans l'enfant (pas d'humain pour valider). L'enfant rapporte
    ce qu'il ferait ; le parent (avec HITL) agit ensuite si besoin.
  - **Pas de délégation imbriquée** : un enfant ne peut pas re-déléguer
    (garde de profondeur via ContextVar, MAX_DEPTH=1).
  - Nombre de sous-tâches plafonné (``MAX_TASKS``) ; timeout par enfant.
  - Les résumés sont des *self-reports* de l'enfant, pas une vérité absolue.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import InjectedToolArg, tool

from app.agent.tool_context import CURRENT_CONVERSATION_ID
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)

MAX_TASKS = 6
MAX_DEPTH = 1
_CHILD_RECURSION_LIMIT = 40
_CHILD_TIMEOUT_S = 240.0

# Depth guard — propagates into each child's asyncio Task context so a
# delegated child that tries to call ``delegate`` again is refused.
_DELEGATE_DEPTH: ContextVar[int] = ContextVar("delegate_depth", default=0)


async def _run_one(task: str, user_id: str, conversation_id: str, depth: int) -> dict:
    """Run one sub-task as an autonomous (HITL-blocked) agent. Never raises."""
    from app.agent.graph import build_simple_agent_graph

    token = _DELEGATE_DEPTH.set(depth + 1)
    try:
        agent = build_simple_agent_graph()
        result = await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [HumanMessage(content=task)],
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "automated_task": True,  # blocks NEVER_AUTONOMOUS_TOOLS
                },
                config={"recursion_limit": _CHILD_RECURSION_LIMIT},
            ),
            timeout=_CHILD_TIMEOUT_S,
        )
        msgs = result.get("messages") if isinstance(result, dict) else None
        raw = msgs[-1].content if msgs else ""
        if isinstance(raw, list):  # multimodal content blocks
            raw = " ".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in raw
            )
        return {"task": task, "summary": str(raw or "").strip(), "ok": True}
    except asyncio.TimeoutError:
        return {"task": task, "summary": "(délai dépassé)", "ok": False}
    except Exception as exc:  # noqa: BLE001 — best-effort, one child must not sink the batch
        logger.warning("delegate child failed for %r: %s", task[:60], exc)
        return {"task": task, "summary": f"(échec : {exc})", "ok": False}
    finally:
        _DELEGATE_DEPTH.reset(token)


@register(
    domain=Domain.UNIVERSAL,
    skill_name="delegate",
    skill_display_name="Délégation parallèle",
    skill_description=(
        "Exécute 2 à 6 sous-tâches INDÉPENDANTES en parallèle via des "
        "sous-agents autonomes, et renvoie une synthèse de leurs résultats. "
        "Idéal quand une demande se découpe en morceaux qui ne dépendent pas "
        "les uns des autres (rechercher plusieurs entreprises, résumer "
        "plusieurs documents, vérifier plusieurs sources à la fois)."
    ),
    skill_icon="🧵",
    enabled_by_default=True,
    skill_version="1.0.0",
)
@tool
async def delegate(
    tasks: list[str],
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Run 2 to 6 INDEPENDENT sub-tasks IN PARALLEL and return a synthesis.

    Use this when a request naturally splits into pieces that **don't depend
    on each other** — e.g. "research these 4 companies", "summarise each of
    these 3 documents", "check the price on these 5 sites". Each sub-task runs
    in its own autonomous sub-agent at the same time, and you get back a
    labelled summary of every result in one shot.

    IMPORTANT:
    - Only for INDEPENDENT sub-tasks. If step 2 needs step 1's result, do them
      yourself in sequence instead — don't delegate.
    - Each sub-task runs **autonomously**: irreversible actions (sending an
      email, deleting a file, SSH…) are **blocked** inside it. A sub-task can
      research, read, search, analyse and report — but if something needs to be
      sent or written, it will report it back and YOU do it (with the user's
      confirmation).
    - Give each sub-task as a **self-contained** instruction (it has no memory
      of the others).

    Args:
        tasks: 2 to 6 independent, self-contained instructions.
    """
    if _DELEGATE_DEPTH.get() >= MAX_DEPTH:
        return (
            "Délégation imbriquée non autorisée — exécute ces sous-tâches "
            "toi-même, tu es déjà dans une sous-tâche déléguée."
        )

    clean = [t.strip() for t in (tasks or []) if isinstance(t, str) and t.strip()]
    if len(clean) < 2:
        return (
            "`delegate` sert à paralléliser : fournis au moins 2 sous-tâches "
            "INDÉPENDANTES. Pour une seule tâche, exécute-la toi-même."
        )

    truncated = 0
    if len(clean) > MAX_TASKS:
        truncated = len(clean) - MAX_TASKS
        clean = clean[:MAX_TASKS]

    conversation_id = CURRENT_CONVERSATION_ID.get()
    depth = _DELEGATE_DEPTH.get()

    logger.info("delegate: lancement de %d sous-tâches en parallèle", len(clean))
    results = await asyncio.gather(
        *[_run_one(t, user_id, conversation_id, depth) for t in clean]
    )

    ok = sum(1 for r in results if r["ok"])
    out = [f"Synthèse de {len(results)} sous-tâches déléguées (parallèle, {ok} OK) :", ""]
    for i, r in enumerate(results, 1):
        mark = "✅" if r["ok"] else "⚠️"
        out.append(f"{mark} **Sous-tâche {i}** — {r['task']}")
        out.append(r["summary"] or "(aucun résultat)")
        out.append("")
    if truncated:
        out.append(f"⚠️ {truncated} sous-tâche(s) ignorée(s) — maximum {MAX_TASKS} par appel.")
    return "\n".join(out).strip()
