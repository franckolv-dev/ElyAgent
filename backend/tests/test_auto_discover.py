# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_auto_discover.py
# @brief      Tests for the @register decorator + auto-discovery scanner.
#             Sprint 2 — Tool registry auto-discovery.
#
# @license    MIT
# =============================================================================
"""Tests for the @register decorator and auto-discovery scanner.

These tests are isolated from the real backend modules: each test builds
a temporary fake package on disk and feeds its dotted path to the
scanner. That way we exercise the full ``importlib.walk_packages`` →
``_drain_pending`` → ``Skill`` → ``registry.register`` path without
mutating the global registry that other tests rely on.

Run with:  cd backend && python -m pytest tests/test_auto_discover.py -v
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from app.skills.base import Domain, Skill
from app.skills.decorator import (
    META_ATTR,
    _peek_pending,
    _reset_pending_for_tests,
    register,
)
from app.skills.registry import get_skill_registry


# ──────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_pending():
    """Empty the pending buffer before AND after each test.

    Prevents cross-test bleed if a test forgets to drain or if a
    previous test fails mid-way.
    """
    _reset_pending_for_tests()
    yield
    _reset_pending_for_tests()


@pytest.fixture
def fake_tools_package(tmp_path, monkeypatch) -> str:
    """Create an empty package on disk and add it to sys.path.

    Returns the dotted package name (unique per test thanks to tmp_path).
    Tests then write tool modules into the directory and call
    ``auto_discover_tools(packages=[pkg_name])``.
    """
    pkg_dir = tmp_path / "fakepkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")

    monkeypatch.syspath_prepend(str(tmp_path))
    yield "fakepkg"

    # Cleanup: drop every fakepkg.* module so the next test re-imports fresh
    to_drop = [m for m in sys.modules if m == "fakepkg" or m.startswith("fakepkg.")]
    for m in to_drop:
        del sys.modules[m]


def _write_tool_module(pkg_path: Path, mod_name: str, body: str) -> None:
    """Write a tool module under the fake package."""
    (pkg_path / f"{mod_name}.py").write_text(textwrap.dedent(body))


# ──────────────────────────────────────────────────────────────────────
# Decorator behaviour
# ──────────────────────────────────────────────────────────────────────


def test_register_attaches_metadata():
    """@register attaches the __ely_skill_metadata__ sentinel."""

    @register(
        domain=Domain.MEMORY,
        skill_name="test_skill",
        skill_display_name="Test Skill",
        skill_description="Just a test.",
        skill_icon="🧪",
    )
    def fake_tool():
        return "ok"

    meta = getattr(fake_tool, META_ATTR, None)
    assert meta is not None
    assert meta.skill_name == "test_skill"
    assert meta.skill_display_name == "Test Skill"
    assert meta.domains == (Domain.MEMORY,)


def test_register_records_in_pending():
    """@register adds the callable to the module-level _PENDING dict."""

    @register(
        domain=Domain.WORKSPACE,
        skill_name="pending_skill",
        skill_display_name="Pending",
        skill_description="Should land in _PENDING.",
    )
    def another_tool():
        pass

    pending = _peek_pending()
    keys = [k for k in pending if k.endswith(".another_tool")]
    assert len(keys) == 1
    _, meta = pending[keys[0]]
    assert meta.skill_name == "pending_skill"


def test_register_accepts_domain_list():
    """domain= can be a single string or a list."""

    @register(
        domain=[Domain.MEMORY, Domain.WORKSPACE],
        skill_name="multi_domain",
        skill_display_name="Multi",
        skill_description="In two domains.",
    )
    def multi_tool():
        pass

    meta = getattr(multi_tool, META_ATTR)
    assert set(meta.domains) == {Domain.MEMORY, Domain.WORKSPACE}


def test_register_rejects_empty_skill_name():
    with pytest.raises(ValueError, match="skill_name"):
        @register(
            domain=Domain.MEMORY,
            skill_name="",
            skill_display_name="X",
            skill_description="Y",
        )
        def bad_tool():
            pass


def test_register_rejects_unknown_domain():
    with pytest.raises(ValueError, match="unknown domain"):
        @register(
            domain="not_a_real_domain",
            skill_name="x",
            skill_display_name="X",
            skill_description="Y",
        )
        def bad_tool():
            pass


def test_register_rejects_empty_domain_list():
    with pytest.raises(ValueError, match="domain"):
        @register(
            domain=[],
            skill_name="x",
            skill_display_name="X",
            skill_description="Y",
        )
        def bad_tool():
            pass


# ──────────────────────────────────────────────────────────────────────
# Auto-discovery scanner
# ──────────────────────────────────────────────────────────────────────


def test_auto_discover_imports_and_registers_skill(fake_tools_package, tmp_path):
    """End-to-end: a tool decorated in a fake package shows up in the registry."""
    from app.skills.auto_discover import auto_discover_tools

    pkg_path = tmp_path / "fakepkg"
    _write_tool_module(pkg_path, "demo_tool", """
        from app.skills.decorator import register
        from app.skills.base import Domain

        @register(
            domain=Domain.MEMORY,
            skill_name="auto_demo_skill",
            skill_display_name="Auto Demo",
            skill_description="Created via @register decorator.",
            skill_icon="✨",
        )
        def demo_tool():
            '''Demo tool docstring.'''
            return 42

        demo_tool.name = "demo_tool"  # mimic LangChain @tool attribute
    """)

    registry = get_skill_registry()
    # Pre-condition: skill not yet in registry
    assert registry.get_skill("auto_demo_skill") is None

    try:
        n = auto_discover_tools(packages=(fake_tools_package,))
        assert n == 1
        skill = registry.get_skill("auto_demo_skill")
        assert skill is not None
        assert skill.display_name == "Auto Demo"
        assert skill.icon == "✨"
        assert Domain.MEMORY in skill.domains
        assert len(skill.tools) == 1
    finally:
        # Clean up the registry mutation
        registry.unregister("auto_demo_skill")


def test_auto_discover_groups_tools_by_skill_name(fake_tools_package, tmp_path):
    """Two tools with the same skill_name collapse into a single Skill."""
    from app.skills.auto_discover import auto_discover_tools

    pkg_path = tmp_path / "fakepkg"
    _write_tool_module(pkg_path, "tool_a", """
        from app.skills.decorator import register
        from app.skills.base import Domain

        @register(
            domain=Domain.WORKSPACE,
            skill_name="grouped_skill",
            skill_display_name="Grouped",
            skill_description="Two tools, one skill.",
        )
        def tool_a():
            pass

        tool_a.name = "tool_a"
    """)
    _write_tool_module(pkg_path, "tool_b", """
        from app.skills.decorator import register
        from app.skills.base import Domain

        @register(
            domain=Domain.WORKSPACE,
            skill_name="grouped_skill",
            skill_display_name="Grouped",
            skill_description="Two tools, one skill.",
        )
        def tool_b():
            pass

        tool_b.name = "tool_b"
    """)

    registry = get_skill_registry()
    assert registry.get_skill("grouped_skill") is None

    try:
        n = auto_discover_tools(packages=(fake_tools_package,))
        assert n == 1  # one skill registered
        skill = registry.get_skill("grouped_skill")
        assert skill is not None
        names = {t.__name__ if hasattr(t, "__name__") else t.name for t in skill.tools}
        assert names == {"tool_a", "tool_b"}
    finally:
        registry.unregister("grouped_skill")


def test_auto_discover_respects_existing_legacy_skill(fake_tools_package, tmp_path):
    """If a skill_name is already registered manually, auto-discovery skips it."""
    from app.skills.auto_discover import auto_discover_tools

    pkg_path = tmp_path / "fakepkg"
    _write_tool_module(pkg_path, "shadow", """
        from app.skills.decorator import register
        from app.skills.base import Domain

        @register(
            domain=Domain.MEMORY,
            skill_name="legacy_shadow_skill",
            skill_display_name="Should be ignored",
            skill_description="Auto pattern should be skipped here.",
        )
        def shadow_tool():
            pass

        shadow_tool.name = "shadow_tool"
    """)

    registry = get_skill_registry()
    # Pre-register manually — like the existing memory_skill.py does
    legacy = Skill(
        name="legacy_shadow_skill",
        display_name="Legacy Wins",
        description="Registered the old way first.",
        icon="🛡️",
        tools=[],
        domains=[Domain.MEMORY],
    )
    registry.register(legacy)

    try:
        n = auto_discover_tools(packages=(fake_tools_package,))
        assert n == 0  # auto-discovery should have skipped it
        skill = registry.get_skill("legacy_shadow_skill")
        assert skill is not None
        assert skill.display_name == "Legacy Wins"  # legacy version, not auto
    finally:
        registry.unregister("legacy_shadow_skill")


def test_auto_discover_survives_broken_module(fake_tools_package, tmp_path, caplog):
    """A module that raises at import time is logged and skipped — boot keeps going."""
    import logging
    from app.skills.auto_discover import auto_discover_tools

    pkg_path = tmp_path / "fakepkg"
    _write_tool_module(pkg_path, "broken", """
        raise RuntimeError("intentional boom during import")
    """)
    _write_tool_module(pkg_path, "healthy", """
        from app.skills.decorator import register
        from app.skills.base import Domain

        @register(
            domain=Domain.MEMORY,
            skill_name="healthy_skill",
            skill_display_name="Healthy",
            skill_description="Should still register despite the sibling crashing.",
        )
        def healthy_tool():
            pass

        healthy_tool.name = "healthy_tool"
    """)

    registry = get_skill_registry()
    try:
        with caplog.at_level(logging.WARNING):
            n = auto_discover_tools(packages=(fake_tools_package,))
        assert n == 1
        assert registry.get_skill("healthy_skill") is not None
        # Should have logged the broken module
        assert any("broken" in r.message for r in caplog.records)
    finally:
        registry.unregister("healthy_skill")


def test_auto_discover_returns_zero_when_no_decorated_tools(fake_tools_package, tmp_path):
    """A package with only plain functions returns zero — no false-positive Skill."""
    from app.skills.auto_discover import auto_discover_tools

    pkg_path = tmp_path / "fakepkg"
    _write_tool_module(pkg_path, "plain", """
        def not_a_registered_tool():
            return None
    """)

    n = auto_discover_tools(packages=(fake_tools_package,))
    assert n == 0


def test_auto_discover_handles_unknown_package_gracefully(caplog):
    """Pointing at a non-existent package logs a warning and returns 0."""
    import logging
    from app.skills.auto_discover import auto_discover_tools

    with caplog.at_level(logging.WARNING):
        n = auto_discover_tools(packages=("does.not.exist.anywhere",))
    assert n == 0
    assert any("cannot import" in r.message.lower() for r in caplog.records)


def test_drain_pending_is_idempotent():
    """Calling _drain_pending twice in a row doesn't replay items."""
    from app.skills.decorator import _drain_pending

    @register(
        domain=Domain.MEMORY,
        skill_name="drain_test",
        skill_display_name="Drain",
        skill_description="Drain me once.",
    )
    def t():
        pass

    first = _drain_pending()
    second = _drain_pending()
    assert len(first) == 1
    assert second == {}
