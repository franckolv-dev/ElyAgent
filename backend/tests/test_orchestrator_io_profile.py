# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrator_io_profile.py
# @brief      Sprint 4b V3 J5 — `validate_tool_source(profile="io")` integration.
# @license    Elastic License 2.0
# =============================================================================
"""Pins the V3 chain order + the new gates' fail-fast behaviour + the
backward compatibility of the default profile="pure".

The smoke stage in the io chain still uses the in-process subprocess
(smoke_sandbox) — the runner-based smoke lands in J6 along with the agent
integration. The pin here is on the SHAPE of the chain (right stages,
right order, right fail-fast), not on the smoke being remote.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning.tool_orchestrator import (
    STAGE_ORDER,
    STAGE_ORDER_IO,
    validate_tool_source,
)


# ── reusable sources ─────────────────────────────────────────────────────────


_PURE_SOURCE = textwrap.dedent("""
    from langchain_core.tools import tool

    from app.skills.base import Domain
    from app.skills.decorator import register


    @register(domain=Domain.WORKSPACE, skill_name="double_it",
              skill_display_name="Double", skill_description="x2",
              skill_icon="x", enabled_by_default=False)
    @tool
    def double_it(x: int) -> int:
        \"\"\"Double the integer x.\"\"\"
        return x * 2
""").strip()


def _io_tool(extra_register_lines: str = "") -> str:
    """Build a V3 `@tool` that uses httpx (real use → no F401) and stays
    under ruff's 88-char line limit.

    `extra_register_lines` is inserted INSIDE the `@register(...)` call. The
    caller is responsible for the indentation (4 spaces) and trailing comma
    of each line — keeps the generated source ruff-clean.
    """
    return (
        "from __future__ import annotations\n"
        "\n"
        "import httpx\n"
        "\n"
        "from langchain_core.tools import tool\n"
        "from app.skills.base import Domain\n"
        "from app.skills.decorator import register\n"
        "\n"
        "\n"
        "@register(\n"
        "    domain=Domain.RESEARCH,\n"
        '    skill_name="weather_check",\n'
        '    skill_display_name="Weather",\n'
        '    skill_description="ping",\n'
        '    skill_icon="i",\n'
        "    enabled_by_default=False,\n"
        + extra_register_lines
        + ")\n"
        "@tool\n"
        "def weather_check() -> int:\n"
        '    """trivial"""\n'
        '    r = httpx.get("https://example.com", timeout=1)\n'
        "    return r.status_code\n"
    )


_IO_HAPPY = _io_tool(
    '    network_allow=["api.openweathermap.org"],\n'
    '    requires=["httpx"],\n'
    '    requires_secrets=["openweather_api_key"],\n'
)


# ── stage-order constants ────────────────────────────────────────────────────


def test_stage_order_pure_unchanged():
    """V2 contract — the pure chain must stay (ast, ruff, mypy, smoke, registration).
    Any caller still reading STAGE_ORDER (logs, dashboards) gets the old shape."""
    assert STAGE_ORDER == ("ast", "ruff", "mypy", "smoke", "registration")


def test_stage_order_io_inserts_v3_gates_between_ast_and_ruff():
    """V3 contract — declarations + deps land BETWEEN ast and ruff so we fail
    fast on bad declarations without paying for the heavier static checks."""
    assert STAGE_ORDER_IO == (
        "ast", "declarations", "deps", "ruff", "mypy", "smoke", "registration",
    )


# ── backward compatibility (profile defaults to "pure") ──────────────────────


def test_default_profile_unchanged_pure_tool_still_passes():
    """Existing V2 call-sites: same source, no profile arg, must still pass."""
    report = validate_tool_source(
        _PURE_SOURCE, existing_names=set(), smoke_kwargs={"x": 21},
    )
    assert report.ok, report.to_json()
    # And the stages list reflects the PURE chain (no `declarations`, no `deps`).
    stage_names = [s.stage for s in report.stages]
    assert "declarations" not in stage_names
    assert "deps" not in stage_names


def test_io_profile_rejects_httpx_import_under_pure():
    """Defence in depth: an io-source MUST NOT pass the default pure pipeline
    even if its declarations are well-formed — pure profile blocks httpx at
    the AST stage."""
    report = validate_tool_source(
        _IO_HAPPY, existing_names=set(), run_smoke=False, profile="pure",
    )
    assert not report.ok
    assert report.failed_stage == "ast"


# ── io profile happy path ────────────────────────────────────────────────────


def test_io_profile_happy_path_runs_v3_gates_in_order():
    """An io-tool with proper declarations + curated deps + httpx must pass
    every io stage that doesn't require live tooling."""
    report = validate_tool_source(
        _IO_HAPPY,
        existing_names=set(),
        run_smoke=False,  # smoke-in-sandbox lands in J6; smoke_sandbox.py local
                          # still works but the wrapper would need real httpx;
                          # skipping here keeps J5 focused on the new chain.
        profile="io",
    )
    assert report.ok, report.to_json()
    stage_names = [s.stage for s in report.stages]
    # declarations + deps appear AFTER ast and BEFORE ruff. The exact slice
    # matters — we don't want a future refactor accidentally moving them.
    assert stage_names[:4] == ["ast", "declarations", "deps", "ruff"]


# ── io profile: each new gate can fail-fast ──────────────────────────────────


def test_io_fails_fast_on_malformed_declarations():
    """A wrong-typed declaration must stop the chain at the `declarations`
    stage — no point paying for ruff/mypy when the kwargs are broken."""
    src = _io_tool('    network_allow="should-be-a-list",\n')
    report = validate_tool_source(
        src, existing_names=set(), run_smoke=False, profile="io",
    )
    assert not report.ok
    assert report.failed_stage == "declarations"
    # And NO further stages ran.
    stage_names = [s.stage for s in report.stages]
    assert "ruff" not in stage_names
    assert "deps" not in stage_names


def test_io_fails_fast_on_invalid_domain():
    src = _io_tool(
        '    network_allow=["http://example.com"],\n'
        '    requires=["httpx"],\n'
    )
    report = validate_tool_source(
        src, existing_names=set(), run_smoke=False, profile="io",
    )
    assert not report.ok
    assert report.failed_stage == "declarations"


def test_io_fails_fast_on_dep_not_in_baked():
    """A `requires=["requests"]` stops the chain at `deps` — requests isn't
    in the sandbox image so the runtime would `ModuleNotFoundError` anyway."""
    src = _io_tool(
        '    network_allow=["api.example.com"],\n'
        '    requires=["requests"],\n'
        '    requires_secrets=["valid_key"],\n'
    )
    report = validate_tool_source(
        src, existing_names=set(), run_smoke=False, profile="io",
    )
    assert not report.ok
    assert report.failed_stage == "deps"


def test_io_fails_fast_on_invalid_secret_label():
    """An invalid secret label is caught by the well-formed gate, NOT by
    secrets-exist (which is async + lands in J6)."""
    src = _io_tool(
        '    requires_secrets=["BAD UPPERCASE"],\n'
        '    requires=["httpx"],\n'
    )
    report = validate_tool_source(
        src, existing_names=set(), run_smoke=False, profile="io",
    )
    assert not report.ok
    assert report.failed_stage == "declarations"


# ── io profile + tool with NO V3 declarations is legitimate ──────────────────


def test_io_profile_tool_without_v3_declarations_passes():
    """A pure-compute tool routed through profile="io" by mistake (or because
    the caller doesn't yet know) must NOT spuriously fail — the io chain
    runs the V3 gates vacuously (empty declarations → ok)."""
    report = validate_tool_source(
        _PURE_SOURCE, existing_names=set(), smoke_kwargs={"x": 21}, profile="io",
    )
    assert report.ok, report.to_json()


# ── unknown profile is a programmer error ────────────────────────────────────


def test_unknown_profile_raises_at_ast_stage():
    """code_guard surfaces it as a ValueError; we don't catch it because
    a typo'd profile name is a programmer mistake, not a tool fault."""
    with pytest.raises(ValueError, match="unknown guard profile"):
        validate_tool_source(
            _PURE_SOURCE, existing_names=set(), profile="bogus",  # type: ignore[arg-type]
        )
