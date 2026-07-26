"""Tests for the SkillRegistry domain helpers (Sprint 2 — eliminates the
triple-registration trap).

Run with:  cd backend && python -m pytest tests/test_skill_registry.py -v
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _register_builtins():
    """Make sure every builtin skill is registered for these tests.

    Other tests don't need this (they use mocks), but we explicitly want a
    fully-populated registry here.
    """
    from app.skills.builtin import register_all
    register_all()
    yield


def _registry():
    from app.skills import get_skill_registry
    return get_skill_registry()


# ── Domain helpers ────────────────────────────────────────────────────────────

def test_tools_by_domain_workspace_non_empty():
    from app.skills.base import Domain
    tools = _registry().tools_by_domain(Domain.WORKSPACE)
    assert len(tools) > 0, "workspace domain should expose at least some tools"
    names = {t.name for t in tools}
    # Sanity — Gmail and Calendar tools should be in workspace
    assert any(n.startswith("gmail_") for n in names), "expected at least one Gmail tool"
    assert any(n.startswith("calendar_") for n in names), "expected at least one Calendar tool"


def test_tools_by_domain_research_has_web_search():
    from app.skills.base import Domain
    names = _registry().tool_names_by_domain(Domain.RESEARCH)
    assert "web_search" in names
    assert "weather_get" in names


def test_universal_tools_appear_in_every_specialist_domain():
    """Skills marked Domain.UNIVERSAL must be injected into every domain."""
    from app.skills.base import Domain
    universal_names = _registry().tool_names_by_domain(Domain.UNIVERSAL)
    assert "save_user_preference" in universal_names
    assert "knowledge_search" in universal_names

    for d in (
        Domain.RESEARCH, Domain.WORKSPACE, Domain.INFRA, Domain.CREATIVE,
        Domain.DATA, Domain.MEMORY, Domain.DESKTOP, Domain.DIAG,
    ):
        names = _registry().tool_names_by_domain(d)
        for u in universal_names:
            assert u in names, f"universal tool {u!r} missing from domain {d!r}"


def test_all_tool_names_matches_all_tools():
    r = _registry()
    assert r.all_tool_names() == {t.name for t in r.all_tools}


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_tools_catalog_contains_gmail_and_calendar():
    catalog = _registry().tools_catalog(per_domain=True)
    # The catalog is what we inject into the planner prompt — the bug
    # report it fixes is "the planner hallucinates tool names". So the
    # catalog must clearly contain the canonical Gmail + Calendar names.
    assert "gmail_list_emails" in catalog
    assert "calendar_list_events" in catalog
    # Per-domain headers
    assert "## workspace" in catalog
    assert "## research" in catalog
    # Universal block must mention save_user_preference
    assert "save_user_preference" in catalog


def test_tools_catalog_flat_form_contains_every_tool_once():
    r = _registry()
    catalog = r.tools_catalog(per_domain=False)
    for name in r.all_tool_names():
        assert f"- {name} :" in catalog or f"- {name} " in catalog, (
            f"tool {name!r} missing from flat catalog"
        )


def test_every_builtin_skill_declares_at_least_one_domain():
    """No builtin skill should ship without explicit ``domains`` — that's
    the whole point of Sprint 2.

    A skill with empty ``domains`` would be invisible to every specialist
    agent and would only be reachable via the ``general`` fallback — which
    is exactly the trap the refactor closes.
    """
    orphans = [s.name for s in _registry().list_skills() if not s.domains]
    assert orphans == [], (
        f"these builtin skills have no declared domain (will be invisible "
        f"to every specialist agent): {orphans}"
    )


# ── Supervisor / sub_agents — runtime sets equal registry-derived sets ──────

