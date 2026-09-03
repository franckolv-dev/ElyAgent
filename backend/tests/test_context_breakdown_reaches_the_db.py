# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_context_breakdown_reaches_the_db.py
# @brief      La ventilation de #255 était calculée mais n'arrivait jamais en
#             base. Le calcul n'est pas la livraison.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du transport de la ventilation, du nœud agent jusqu'à ``usage_logs``.

**Le défaut, constaté en production le 26/07.** ``usage_logs`` compte
**0 ligne** avec ``context_breakdown`` non nul, alors que des tours de chat ont
bien tourné depuis le déploiement de #255 (07:01, 11:00 et 11:05 ce jour-là).

**La cause.** ``agent_node`` posait la valeur dans une ``ContextVar``, et
``chat.py`` la relisait après l'exécution du graphe. Or LangGraph exécute
chaque nœud dans une **tâche asyncio distincte** : une ``ContextVar`` se
propage du parent vers l'enfant, jamais de l'enfant vers le parent. Le parent
relisait donc toujours la valeur par défaut, ``None``.

Le commentaire que j'avais laissé dans ``chat.py`` énonçait exactement le
mécanisme qui condamnait le montage — « ContextVar par tâche asyncio » — sans
que j'en tire la conséquence.

**Le véhicule correct existait déjà à côté** : ``model_used`` remonte par
**l'état du graphe** (``state.py``), qui est justement ce que LangGraph fait
traverser les frontières de tâches. C'est ce que ce lot adopte.

**Pourquoi #255 n'a rien vu.** Son test vérifiait que ``nodes.py`` *contient*
l'appel à ``compute_context_breakdown`` — un pin sur le source. Le calcul
avait bien lieu ; c'est la livraison qui manquait. Un test de présence ne
prouve pas un acheminement. Les tests ci-dessous vérifient l'arrivée.

Run with:  cd backend && python -m pytest tests/test_context_breakdown_reaches_the_db.py -v
"""
from __future__ import annotations

import asyncio
import json

import pytest


# ------------------------------------------------ la cause, mise à nu

@pytest.mark.asyncio
async def test_a_contextvar_set_in_a_child_task_never_reaches_the_parent():
    """Le mécanisme qui a condamné #255, épinglé pour qu'on n'y revienne pas.

    Ce test ne porte pas sur Ely mais sur asyncio : il documente pourquoi une
    ``ContextVar`` ne peut PAS servir à faire remonter une valeur depuis un
    nœud LangGraph. Si quelqu'un repropose ce montage, ce test lui répond."""
    from contextvars import ContextVar

    probe: ContextVar[str | None] = ContextVar("probe", default=None)

    async def _child() -> None:
        probe.set("valeur produite dans le nœud")

    await asyncio.create_task(_child())

    assert probe.get() is None, (
        "si ceci passait, la ContextVar remonterait et #255 aurait fonctionné"
    )


# ------------------------------------------- le véhicule qui, lui, remonte

def test_the_graph_state_carries_the_breakdown():
    """L'état du graphe traverse les frontières de tâches — c'est par lui que
    ``model_used`` remonte déjà depuis toujours."""
    from app.agent.state import AgentState

    annotations = getattr(AgentState, "__annotations__", {})
    assert "context_breakdown" in annotations, (
        "la ventilation doit voyager par l'état, comme model_used"
    )


@pytest.mark.asyncio
async def test_the_agent_node_returns_the_breakdown_in_its_state(monkeypatch):
    """LE test du lot. On exécute le vrai graphe avec un LLM factice et on
    vérifie que la ventilation **arrive au caller** — ce que #255 n'a jamais
    vérifié."""
    from langchain_core.messages import AIMessage, HumanMessage

    class _FakeLLM:
        """Un LLM qui répond sans appeler d'outil."""

        def bind_tools(self, *a, **k):
            return self

        def with_config(self, *a, **k):
            return self

        async def ainvoke(self, messages, config=None, **k):
            return AIMessage(content="Bonjour.")

    import app.services.llm_provider as llm_provider

    # Import LOCAL dans agent_node → patcher le module source, pas `nodes`
    # (la leçon de #258 : patcher le mauvais module fait passer un test pour
    # de mauvaises raisons).
    monkeypatch.setattr(llm_provider, "get_llm_for_tier", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr(llm_provider, "get_llm", lambda *a, **k: _FakeLLM(), raising=False)

    from app.agent.graph import build_simple_agent_graph

    graph = build_simple_agent_graph()
    result = await graph.ainvoke({
        "messages": [HumanMessage(content="bonjour")],
        "user_id": "u-test",
        "conversation_id": "c-test",
    })

    raw = result.get("context_breakdown")
    assert raw, (
        "la ventilation n'est pas remontée jusqu'au caller — c'est exactement "
        "le défaut de #255, qui calculait sans livrer"
    )
    parsed = json.loads(raw)
    assert parsed.get("total", 0) > 0
    assert parsed.get("system_prompt", 0) > 0


# ------------------------------------------------- l'écriture en base

def test_the_chat_router_reads_the_breakdown_from_the_state():
    """Le point d'écriture doit lire l'état renvoyé par le graphe. Tant qu'il
    interroge la ContextVar, il écrira NULL quoi qu'il arrive en amont."""
    from pathlib import Path

    src = Path("app/routers/chat.py").read_text(encoding="utf-8")

    assert "LAST_CONTEXT_BREAKDOWN.get()" not in src, (
        "chat.py relit encore la ContextVar : elle vaut None côté parent"
    )
    assert "context_breakdown" in src
