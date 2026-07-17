# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_hitl_decisions.py
# @brief      2026-06-04 — mission dispatch_tool must honour allow_always /
#             allow_for_task (and the persistent + task-scoped skips), not
#             treat them as refusals.
# @license    Elastic License 2.0
# =============================================================================
"""Regression: the HITL feature (#38) added allow_for_task/allow_always to the
CHAT path (tool_node) but NOT the MISSION path (missions/nodes.dispatch_tool),
which only accepted "allow" — so in a mission "Toujours autoriser" and "Pour
cette tâche" fell into `decision != "allow"` → "Action refusée" (Franck,
2026-06-04). These tests import & execute dispatch_tool to pin the fix.
"""
from __future__ import annotations

import pytest

from app.agent.missions import nodes as mnodes
from app.services import task_approvals


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name

    async def ainvoke(self, args):
        return "EXECUTED"


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = tools

    @property
    def all_tools(self):
        return self._tools


def _patch_common(monkeypatch, tool_name: str, *, decision: str | None, hitl_raises: bool = False):
    import app.skills as skills_mod
    import app.services.hitl_manager as hm
    import app.services.hitl_descriptions as hd

    monkeypatch.setattr(skills_mod, "get_skill_registry", lambda: _FakeRegistry([_FakeTool(tool_name)]))

    class _FakeHitl:
        async def request_validation(self, description, user_id):  # noqa: ARG002
            if hitl_raises:
                raise AssertionError("HITL prompt should have been skipped")
            return decision, None

    monkeypatch.setattr(hm, "get_hitl_manager", lambda: _FakeHitl())

    async def _fake_human(**kwargs):  # noqa: ARG001
        return "human-readable description"

    monkeypatch.setattr(hd, "build_human_hitl_description", _fake_human)

    # C3b-2 : le dispatch missions passe par le ToolGateway, qui applique
    # l'ACL outils d'instance (B-12, admin-only pour ssh) — hors sujet ici
    # (l'intention de ces tests = la sémantique des DÉCISIONS HITL). L'ACL
    # gagnée par les missions a son propre pin ci-dessous.
    import app.services.tool_acl as ta

    async def _no_acl(_uid, _tool):  # noqa: ARG001
        return None

    monkeypatch.setattr(ta, "check_tool_access", _no_acl)


# ssh_execute is in ALWAYS_CRITICAL_TOOLS (→ needs_hitl) and LOCKED_HITL_TOOLS
# (→ persistent pref can't skip it, but task-scoped approval still can).
_TOOL = "ssh_execute"


@pytest.mark.asyncio
async def test_allow_always_executes_and_persists(monkeypatch):
    _patch_common(monkeypatch, _TOOL, decision="allow_always")
    saved = {}

    async def _fake_set_pref(user_id, tool_name, *, requires_confirmation):
        saved["called"] = (user_id, tool_name, requires_confirmation)
        return True

    import app.services.hitl_preferences as hp
    monkeypatch.setattr(hp, "set_user_preference", _fake_set_pref)

    out, ok = await mnodes.dispatch_tool(_TOOL, {}, "tc1", "user-1", mission_id="m-always")
    assert ok is True
    assert out == "EXECUTED"  # NOT "Action refusée…"
    assert saved["called"] == ("user-1", _TOOL, False)


@pytest.mark.asyncio
async def test_allow_for_task_executes_and_registers(monkeypatch):
    task_approvals.clear_task_approvals("m-task")
    _patch_common(monkeypatch, _TOOL, decision="allow_for_task")
    try:
        out, ok = await mnodes.dispatch_tool(_TOOL, {}, "tc1", "user-1", mission_id="m-task")
        assert ok is True
        assert out == "EXECUTED"
        # the tool is now approved for the rest of THIS mission
        assert task_approvals.is_tool_approved_for_task("m-task", _TOOL) is True
    finally:
        task_approvals.clear_task_approvals("m-task")


@pytest.mark.asyncio
async def test_deny_is_still_refused(monkeypatch):
    _patch_common(monkeypatch, _TOOL, decision="deny")
    out, ok = await mnodes.dispatch_tool(_TOOL, {}, "tc1", "user-1", mission_id="m-deny")
    assert ok is False
    assert out.startswith("Action refusée")


@pytest.mark.asyncio
async def test_task_approval_skips_prompt_even_for_locked(monkeypatch):
    # pre-approve for this mission → HITL must be skipped (manager raises if called)
    task_approvals.clear_task_approvals("m-pre")
    task_approvals.approve_tool_for_task("m-pre", _TOOL)
    _patch_common(monkeypatch, _TOOL, decision=None, hitl_raises=True)
    try:
        out, ok = await mnodes.dispatch_tool(_TOOL, {}, "tc1", "user-1", mission_id="m-pre")
        assert ok is True
        assert out == "EXECUTED"
    finally:
        task_approvals.clear_task_approvals("m-pre")


@pytest.mark.asyncio
async def test_mission_gains_instance_tool_acl(monkeypatch):
    """C3b-2 — trou fermé : le chemin missions n'appliquait PAS l'ACL B-12
    (outils à ressources d'instance, admin-only). Via la passerelle, une
    mission d'un non-admin ne peut plus piloter ssh_execute."""
    _patch_common(monkeypatch, _TOOL, decision="allow")
    import app.services.tool_acl as ta

    async def _admin_only(_uid, _tool):  # noqa: ARG001
        return "⛔ Outil réservé à l'administrateur."

    monkeypatch.setattr(ta, "check_tool_access", _admin_only)
    out, ok = await mnodes.dispatch_tool(_TOOL, {}, "tc1", "user-1", mission_id="m-acl")
    assert ok is False
    assert "administrateur" in out
