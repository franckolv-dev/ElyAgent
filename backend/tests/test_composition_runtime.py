# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_composition_runtime.py
# @brief      Sprint 4b V2 (composition N1) — the runtime engine for generated
#             python_tools that compose other ELY tools via call_tool().
# @license    Elastic License 2.0
# =============================================================================
"""Composition engine tests (no LLM — a hand-written composition source).

Covers: call_tool refuses critical tools + unknown names, dispatches a safe
tool and re-injects creds/user_id, the composable allow-list excludes
critical tools, code_guard allows the call_tool import, the validation
orchestrator skips smoke for composition tools, and a compiled composition
StructuredTool actually dispatches end-to-end.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning import learned_tool_dispatch as ltd


# A hand-written COMPOSITION tool — what the generator will produce once its
# prompt teaches the convention (PR-B). Async + imports + awaits call_tool.
COMPO = textwrap.dedent(
    '''
    from __future__ import annotations

    from langchain_core.tools import tool

    from app.skills.base import Domain
    from app.skills.decorator import register
    from app.services.learning.learned_tool_dispatch import call_tool


    @register(domain=Domain.WORKSPACE, skill_name="unread_count",
              skill_display_name="Unread count", skill_description="count matching emails",
              skill_icon="📧", enabled_by_default=False)
    @tool
    async def unread_count(query: str) -> int:
        """Count emails matching a query by composing gmail_list_emails."""
        emails = await call_tool("gmail_list_emails", {"query": query})
        return len(emails) if isinstance(emails, list) else 0
    '''
).strip()


class _FakeTool:
    def __init__(self, name: str, result):
        self.name = name
        self._result = result
        self.received: dict | None = None

    async def ainvoke(self, args):
        self.received = args
        return self._result


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = tools

    @property
    def all_tools(self):
        return self._tools

    def all_tool_names(self):
        return {t.name for t in self._tools}


def _patch_registry(monkeypatch, tools):
    monkeypatch.setattr("app.skills.registry.get_skill_registry", lambda: _FakeRegistry(tools))


def _patch_creds(monkeypatch, value="creds-json"):
    class _Store:
        def get(self, user_id):  # noqa: ARG002
            return value

    monkeypatch.setattr("app.services.credential_store.get_credential_store", lambda: _Store())


# ── call_tool guardrails ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_tool_refuses_critical_tool():
    # ssh_execute is in ALWAYS_CRITICAL_TOOLS — refused before any lookup.
    with pytest.raises(ValueError, match="critical"):
        await ltd.call_tool("ssh_execute", {})


@pytest.mark.asyncio
async def test_call_tool_refuses_unknown_tool(monkeypatch):
    _patch_registry(monkeypatch, [_FakeTool("gmail_list_emails", [])])
    with pytest.raises(ValueError, match="unknown tool"):
        await ltd.call_tool("does_not_exist", {})


@pytest.mark.asyncio
async def test_call_tool_dispatches_and_injects_credentials(monkeypatch):
    fake = _FakeTool("gmail_list_emails", ["a", "b", "c"])
    _patch_registry(monkeypatch, [fake])
    _patch_creds(monkeypatch, "tok-123")
    ltd.LEARNED_TOOL_USER_ID.set("user-xyz")

    result = await ltd.call_tool("gmail_list_emails", {"query": "is:unread"})
    assert result == ["a", "b", "c"]
    # gmail_list_emails ∈ GOOGLE_TOOLS → creds re-injected like the dispatcher does
    assert fake.received["query"] == "is:unread"
    assert fake.received["user_google_credentials_json"] == "tok-123"


# ── composable allow-list ────────────────────────────────────────────────────


def test_composable_excludes_critical(monkeypatch):
    _patch_registry(monkeypatch, [
        _FakeTool("gmail_list_emails", []),   # safe (read)
        _FakeTool("gmail_send_email", []),    # ALWAYS_CRITICAL
        _FakeTool("ssh_execute", []),         # ALWAYS_CRITICAL
    ])
    names = ltd.composable_tool_names()
    assert "gmail_list_emails" in names
    assert "gmail_send_email" not in names
    assert "ssh_execute" not in names
    assert ltd.is_composable("gmail_list_emails") is True
    assert ltd.is_composable("gmail_send_email") is False


# ── code_guard allows the call_tool import ───────────────────────────────────


def test_code_guard_allows_call_tool_import():
    from app.services.learning.code_guard import check_tool_source

    report = check_tool_source(COMPO)
    assert report.ok, report.summary()


# ── orchestrator runs a NARROW smoke for composition tools ───────────────────


def test_validation_runs_contract_smoke_for_composition():
    """Le smoke n'est plus sauté : il valide le contrat de type de call_tool.

    Changement du 22/07 — le saut pur et simple avait laissé passer en prod
    un tool qui faisait ``.get()`` sur une chaîne (cf.
    test_composition_smoke_contract.py). La sémantique, elle, reste hors de
    portée du bac à sable : seul le contrat est jugé ici.
    """
    from app.services.learning.tool_orchestrator import validate_tool_source

    report = validate_tool_source(COMPO, existing_names=set(), run_smoke=True)
    assert report.ok, report.to_json()
    smoke = next((s for s in report.stages if s.stage == "smoke"), None)
    assert smoke is not None and smoke.ok
    assert "contract ok" in smoke.detail


# ── end-to-end: compile a composition tool and dispatch through it ───────────


@pytest.mark.asyncio
async def test_compiled_composition_tool_dispatches(monkeypatch):
    from app.services.learning.tool_loader import compile_tool_source

    res = compile_tool_source(COMPO)
    assert res.ok, res.error
    assert res.name == "unread_count"

    fake = _FakeTool("gmail_list_emails", ["m1", "m2"])
    _patch_registry(monkeypatch, [fake])
    _patch_creds(monkeypatch, "tok-abc")
    ltd.LEARNED_TOOL_USER_ID.set("user-1")

    out = await res.tool.ainvoke({"query": "is:unread"})
    assert out == 2  # len(["m1", "m2"]) — dispatched through call_tool live
    assert fake.received["user_google_credentials_json"] == "tok-abc"
