# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_v3_declarations.py
# @brief      Sprint 4b V3 J4 — tests for parsing + 3 gates of V3 declarations.
# @license    MIT
# =============================================================================
"""Three gates, three threat models:

  1. Well-formed gate — the declared lists are actually lists of valid
     strings (no sneaky AST-level injection of a Name, no malformed
     domains, no duplicate entries).
  2. Deps-subset gate — `requires` is a subset of the libs ACTUALLY in
     the sandbox image (so a tool can't declare a dep that won't import).
  3. Secrets-exist gate — every Vault label the tool wants is provisioned
     for that user.

All tests are unit-level: vault is mocked, requirements.txt is read from
disk (it's a small file checked into the repo).
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning.v3_declarations import (
    BAKED_LIBS,
    DeclarationsReport,
    V3Declarations,
    _read_requirements_distribution_names,
    check_declarations_wellformed,
    check_deps_subset_of_baked,
    check_secrets_exist,
    parse_v3_declarations,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _tool(decorator: str = "") -> str:
    """Wrap a `@register(...)` decorator around a trivial body."""
    return textwrap.dedent(f"""
        from langchain_core.tools import tool
        from app.skills.base import Domain
        from app.skills.decorator import register

        @register(domain=Domain.RESEARCH, skill_name="probe",
                  skill_display_name="Probe", skill_description="x",
                  skill_icon="🌐", enabled_by_default=False,
                  {decorator})
        @tool
        def probe() -> str:
            \"\"\"trivial\"\"\"
            return "ok"
    """).strip()


# ── BAKED_LIBS / requirements.txt lockstep ───────────────────────────────────


def test_baked_libs_matches_sandbox_requirements_txt():
    """Pin: BAKED_LIBS == every package in sandbox/requirements.txt. If you
    bump one in a PR, this test forces the other (or the PR has to argue
    why the static allow-list and the runtime-installed set should diverge,
    which is exactly the kind of slip we want a reviewer to see)."""
    on_disk = _read_requirements_distribution_names()
    # Sanity — if the file is empty or missing, the audit can't work.
    assert on_disk, "sandbox/requirements.txt not found or empty"
    assert BAKED_LIBS == frozenset(on_disk), (
        f"BAKED_LIBS={sorted(BAKED_LIBS)} vs requirements.txt={sorted(on_disk)}"
    )


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parse_no_declarations_returns_empty():
    decls = parse_v3_declarations(_tool())
    assert decls.network_allow == ()
    assert decls.requires == ()
    assert decls.requires_secrets == ()
    assert decls.is_pure is True


def test_parse_all_three_lists():
    decls = parse_v3_declarations(_tool(
        'network_allow=["api.x.com", ".github.com"], '
        'requires=["httpx", "lxml"], '
        'requires_secrets=["openweather_api_key"]'
    ))
    assert decls.network_allow == ("api.x.com", ".github.com")
    assert decls.requires == ("httpx", "lxml")
    assert decls.requires_secrets == ("openweather_api_key",)
    assert decls.is_pure is False


def test_parse_unparseable_source_is_empty():
    """Static parser must NEVER raise, even on broken input."""
    decls = parse_v3_declarations("def f(:\n")
    assert decls == V3Declarations()


def test_parse_no_register_decorator_is_empty():
    """Tool without @register (it shouldn't pass the registration gate
    anyway, but the V3 parser must still degrade gracefully)."""
    decls = parse_v3_declarations("def f():\n    return 1\n")
    assert decls == V3Declarations()


def test_parse_malformed_list_value_is_empty_list_not_crash():
    """A `network_allow={...}` (set) or `network_allow="x"` (str) keeps the
    parser honest — empty list, well-formed gate flags it later."""
    src = _tool('network_allow="should-be-a-list"')
    decls = parse_v3_declarations(src)
    assert decls.network_allow == ()  # empty, NOT crashed


def test_parse_list_with_non_string_entry_is_empty():
    """A list of mixed types is malformed — empty list, gate flags it."""
    src = _tool('requires=["httpx", 123]')
    decls = parse_v3_declarations(src)
    assert decls.requires == ()


# ── Gate 1: well-formed ──────────────────────────────────────────────────────


def test_wellformed_empty_is_ok():
    """A pure tool (no V3 declarations at all) passes vacuously."""
    src = _tool()
    report = check_declarations_wellformed(src)
    assert report.ok


def test_wellformed_valid_declarations_pass():
    src = _tool(
        'network_allow=["api.openweathermap.org", ".github.com"], '
        'requires=["httpx", "beautifulsoup4"], '
        'requires_secrets=["openweather_api_key", "github_pat"]'
    )
    report = check_declarations_wellformed(src)
    assert report.ok, report.summary()


@pytest.mark.parametrize("decl,fragment", [
    # invalid domain shapes
    ('network_allow=["not a domain"]',       "not a valid domain"),
    ('network_allow=["http://example.com"]', "not a valid domain"),  # scheme not allowed
    ('network_allow=["example.com:8080"]',   "not a valid domain"),  # port not allowed
    ('network_allow=["192.168.1.1"]',        "IP literals"),  # IPs aren't supported by dstdomain
    ('network_allow=[""]',                   "empty or non-string"),
    ('network_allow=["UPPERCASE.COM"]',      "not a valid domain"),
    # invalid secret labels
    ('requires_secrets=["UPPER"]',           "not a valid vault label"),
    ('requires_secrets=["spaces here"]',     "not a valid vault label"),
    ('requires_secrets=["1starts_with_digit"]', "not a valid vault label"),
    ('requires_secrets=[""]',                "empty or non-string"),
    # malformed at the AST level (not a list)
    ('network_allow="not-a-list"',           "must be a list of string literals"),
    ('requires={"httpx"}',                   "must be a list of string literals"),
    # mixed-type list (parser drops to [], gate's malformed audit flags it)
    ('requires=["httpx", 123]',              "must be a list of string literals"),
])
def test_wellformed_rejects_malformed(decl, fragment):
    src = _tool(decl)
    report = check_declarations_wellformed(src)
    assert not report.ok, f"{decl!r} unexpectedly passed"
    assert any(fragment in v for v in report.violations), (
        f"expected {fragment!r} in {list(report.violations)}"
    )


def test_wellformed_flags_duplicates():
    src = _tool('network_allow=["example.com", "example.com"]')
    report = check_declarations_wellformed(src)
    assert not report.ok
    assert any("duplicate" in v for v in report.violations)


def test_wellformed_accepts_leading_dot_squid_form():
    """Squid's `.example.com` form (suffix-match) is the canonical wire
    form we re-emit into squid.conf; it must validate."""
    src = _tool('network_allow=[".example.com"]')
    assert check_declarations_wellformed(src).ok


# ── Gate 2: requires ⊆ BAKED_LIBS ────────────────────────────────────────────


def test_deps_subset_empty_requires_passes():
    assert check_deps_subset_of_baked(V3Declarations()).ok


def test_deps_subset_baked_libs_pass():
    decls = V3Declarations(requires=("httpx", "beautifulsoup4", "lxml"))
    assert check_deps_subset_of_baked(decls).ok


def test_deps_subset_extra_lib_fails_with_clear_message():
    decls = V3Declarations(requires=("httpx", "requests"))
    report = check_deps_subset_of_baked(decls)
    assert not report.ok
    msg = report.summary()
    assert "requests" in msg
    assert "sandbox/requirements.txt" in msg  # tells the user how to fix


def test_deps_subset_custom_baked_set_for_future_io_profiles():
    """Allow callers to pass a custom baked set (V3.x might introduce
    `io_extended` with more libs)."""
    decls = V3Declarations(requires=("requests",))
    report = check_deps_subset_of_baked(
        decls, baked=frozenset({"requests"}),
    )
    assert report.ok


# ── Gate 3: secrets exist in Vault ───────────────────────────────────────────


class _FakeVault:
    """Stand-in for VaultService.list_secrets."""

    def __init__(self, labels: list[str]):
        self._labels = labels

    async def list_secrets(self, user_id: str):  # noqa: ARG002
        return [{"label": x} for x in self._labels]


class _CrashingVault:
    async def list_secrets(self, user_id: str):  # noqa: ARG002
        raise RuntimeError("vault down")


@pytest.mark.asyncio
async def test_secrets_no_declarations_passes():
    """A tool that doesn't ask for any secret skips the gate vacuously."""
    report = await check_secrets_exist(V3Declarations(), user_id="u1")
    assert report.ok


@pytest.mark.asyncio
async def test_secrets_all_present_passes():
    decls = V3Declarations(requires_secrets=("k1", "k2"))
    report = await check_secrets_exist(
        decls, user_id="u1",
        vault_service=_FakeVault(["k1", "k2", "k3"]),
    )
    assert report.ok


@pytest.mark.asyncio
async def test_secrets_missing_one_fails_with_clear_message():
    decls = V3Declarations(requires_secrets=("k1", "k2"))
    report = await check_secrets_exist(
        decls, user_id="u1", vault_service=_FakeVault(["k1"]),
    )
    assert not report.ok
    assert "k2" in report.summary()
    assert "must store" in report.summary()  # actionable, not just a flag


@pytest.mark.asyncio
async def test_secrets_no_user_id_is_a_violation():
    """Calling the gate without a user is a programmer mistake — surface it."""
    decls = V3Declarations(requires_secrets=("k1",))
    report = await check_secrets_exist(decls, user_id="")
    assert not report.ok


@pytest.mark.asyncio
async def test_secrets_vault_crash_degrades_open():
    """A Vault failure must NOT block the validation pipeline (the runtime
    will re-check when it actually tries to inject the secret)."""
    decls = V3Declarations(requires_secrets=("k1",))
    report = await check_secrets_exist(
        decls, user_id="u1", vault_service=_CrashingVault(),
    )
    assert report.ok


# ── DeclarationsReport helpers ───────────────────────────────────────────────


def test_summary_ok_when_no_violations():
    assert DeclarationsReport(ok=True).summary() == "ok"


def test_summary_joins_violations():
    report = DeclarationsReport(ok=False, violations=("a", "b", "c"))
    assert report.summary() == "a; b; c"
