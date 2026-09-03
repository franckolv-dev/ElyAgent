# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_hitl_instruction_args.py
# @brief      2026-06-04 — the HITL keyword scan must ignore deferred-instruction
#             args (prompt/code): scheduling a task « Supprimer … » is a harmless
#             creation, not a destructive action. (scheduler_create_task anomaly.)
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins the fix for the scheduler_create_task HITL anomaly (Franck, 2026-06-04).

is_critical was keyword-scanning the *full* action_desc, including the
free-text `prompt` of scheduler_create_task — so a scheduled task whose
description contained an exact keyword form (« Supprimer », « Payer », …)
falsely triggered HITL on its CREATION. The deferred action is HITL-gated
when the task actually runs; creating it isn't critical. dispatch_tool is
imported & executed; mission_id="" so the autonomous branch is skipped.
"""
from __future__ import annotations

import pytest

from app.agent.missions import nodes as mnodes


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


def _patch(monkeypatch, tool_name, *, hitl_decision="deny", hitl_raises=False):
    import app.skills as skills_mod
    import app.services.hitl_manager as hm
    import app.services.hitl_descriptions as hd

    monkeypatch.setattr(skills_mod, "get_skill_registry",
                        lambda: _FakeRegistry([_FakeTool(tool_name)]))

    class _FakeHitl:
        async def request_validation(self, description, user_id):  # noqa: ARG002
            if hitl_raises:
                raise AssertionError("HITL prompt should NOT fire for this call")
            return hitl_decision, None

    monkeypatch.setattr(hm, "get_hitl_manager", lambda: _FakeHitl())

    async def _human(**kwargs):  # noqa: ARG001
        return "desc"

    monkeypatch.setattr(hd, "build_human_hitl_description", _human)


@pytest.mark.asyncio
async def test_scheduler_prompt_with_keyword_not_gated(monkeypatch):
    # The prompt holds a deferred instruction with a destructive keyword.
    # Creating the task is harmless → no HITL → executes.
    _patch(monkeypatch, "scheduler_create_task", hitl_raises=True)
    out, ok = await mnodes.dispatch_tool(
        "scheduler_create_task",
        {"name": "Mén.", "prompt": "Supprimer mes vieux mails chaque lundi",
         "cron_expression": "0 8 * * 1"},
        "tc1", "user-1", mission_id="",
    )
    assert ok is True
    assert out == "EXECUTED"


@pytest.mark.asyncio
async def test_keyword_in_structured_arg_still_gates(monkeypatch):
    # A keyword in a NON-instruction (structured) arg must still trigger HITL —
    # the fix only excludes prompt/code/instruction, not real args.
    _patch(monkeypatch, "some_search_tool", hitl_decision="deny")
    out, ok = await mnodes.dispatch_tool(
        "some_search_tool", {"query": "supprimer tout"}, "tc1", "user-1", mission_id="",
    )
    assert ok is False
    assert out.startswith("Action refusée")


@pytest.mark.asyncio
async def test_always_critical_tool_still_gates_despite_prompt_arg(monkeypatch):
    # Tool criticality by NAME is unaffected by the prompt exclusion.
    _patch(monkeypatch, "ssh_execute", hitl_decision="deny")
    out, ok = await mnodes.dispatch_tool(
        "ssh_execute", {"prompt": "hello", "command": "ls"}, "tc1", "user-1", mission_id="",
    )
    assert ok is False
    assert out.startswith("Action refusée")
