# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_delegate_tool.py
# @brief      Tool ``delegate`` — délégation parallèle de sous-tâches
# @license    MIT
# =============================================================================
"""Tests for the parallel-delegation tool."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _patch_graph(monkeypatch, *, reply="OK", record=None, boom_on=None):
    """Patch build_simple_agent_graph with a fake that echoes the task."""
    import app.agent.graph as graph_mod

    class _FakeGraph:
        async def ainvoke(self, state, config=None):
            if record is not None:
                record.append(state)
            task = state["messages"][-1].content
            if boom_on and boom_on in task:
                raise RuntimeError("boom")
            return {"messages": [SimpleNamespace(content=f"{reply}: {task}")]}

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _FakeGraph())


# ── happy path ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delegate_runs_all_tasks(monkeypatch):
    from app.agent.tools.delegate_tool import delegate
    _patch_graph(monkeypatch, reply="résultat")
    out = await delegate.ainvoke({
        "tasks": ["Recherche entreprise A", "Recherche entreprise B", "Recherche entreprise C"],
        "user_id": "u1",
    })
    assert "3 sous-tâches" in out
    assert "entreprise A" in out and "entreprise B" in out and "entreprise C" in out
    assert out.count("✅") == 3


@pytest.mark.asyncio
async def test_delegate_children_run_autonomous(monkeypatch):
    """Each child must run with automated_task=True (HITL-blocked)."""
    from app.agent.tools.delegate_tool import delegate
    states = []
    _patch_graph(monkeypatch, record=states)
    await delegate.ainvoke({"tasks": ["t1", "t2"], "user_id": "u9"})
    assert len(states) == 2
    assert all(s.get("automated_task") is True for s in states)
    assert all(s.get("user_id") == "u9" for s in states)


# ── guards ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delegate_requires_two_tasks(monkeypatch):
    from app.agent.tools.delegate_tool import delegate
    _patch_graph(monkeypatch)
    out = await delegate.ainvoke({"tasks": ["seule tâche"], "user_id": "u1"})
    assert "au moins 2" in out
    out2 = await delegate.ainvoke({"tasks": [], "user_id": "u1"})
    assert "au moins 2" in out2


@pytest.mark.asyncio
async def test_delegate_caps_tasks(monkeypatch):
    from app.agent.tools.delegate_tool import delegate, MAX_TASKS
    states = []
    _patch_graph(monkeypatch, record=states)
    many = [f"tâche {i}" for i in range(MAX_TASKS + 3)]
    out = await delegate.ainvoke({"tasks": many, "user_id": "u1"})
    assert len(states) == MAX_TASKS          # only MAX_TASKS actually ran
    assert "ignorée" in out                  # the rest are reported as dropped


@pytest.mark.asyncio
async def test_delegate_no_nested_delegation(monkeypatch):
    from app.agent.tools.delegate_tool import delegate, _DELEGATE_DEPTH
    _patch_graph(monkeypatch)
    token = _DELEGATE_DEPTH.set(1)  # simulate being inside a delegated child
    try:
        out = await delegate.ainvoke({"tasks": ["a", "b"], "user_id": "u1"})
    finally:
        _DELEGATE_DEPTH.reset(token)
    assert "imbriquée non autorisée" in out


# ── resilience ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delegate_one_child_fails_batch_survives(monkeypatch):
    from app.agent.tools.delegate_tool import delegate
    _patch_graph(monkeypatch, reply="ok", boom_on="CASSE")
    out = await delegate.ainvoke({
        "tasks": ["tâche normale", "tâche qui CASSE", "autre tâche"],
        "user_id": "u1",
    })
    assert "✅" in out and "⚠️" in out        # mixed success/failure
    assert "3 sous-tâches" in out
    assert "tâche normale" in out and "autre tâche" in out
