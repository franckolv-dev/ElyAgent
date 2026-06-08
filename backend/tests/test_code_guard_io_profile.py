# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_code_guard_io_profile.py
# @brief      Sprint 4b V3 J3 — adversarial tests for the "io" guard profile.
# @license    Elastic License 2.0
# =============================================================================
"""The `io` profile relaxes the IMPORT allow-list to include the curated
network/parse libs (httpx, bs4, lxml). It does NOT relax anything else.

These tests:
  - pin that the new libs pass under "io" but still FAIL under "pure"
    (so the default-pure call-sites can't accidentally let io-only tools
    through without explicitly opting in);
  - pin that EVERY adversarial pattern the `pure` profile blocks is also
    blocked under `io` (same FORBIDDEN_CALLS, same dunder ban, same
    relative/star-import ban, same global/nonlocal ban);
  - pin the V2-N1 composition path (`call_tool` import) still works under
    "io" (V3 tools may still want to compose existing ELY tools).
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning.code_guard import (
    ALLOWED_IMPORT_EXACT,
    ALLOWED_IMPORT_ROOTS,
    ALLOWED_IMPORT_ROOTS_IO,
    FORBIDDEN_CALLS,
    check_tool_source,
    is_safe,
)


# ── frozenset relationships (the design contract) ────────────────────────────


def test_io_strictly_extends_pure_for_roots():
    """`io` must be a superset of `pure` for ROOTS — any code accepted under
    pure must still be accepted under io. (Adding `io` can never break a
    V2-shipped tool.)"""
    assert ALLOWED_IMPORT_ROOTS.issubset(ALLOWED_IMPORT_ROOTS_IO)


def test_io_adds_exactly_the_curated_network_libs():
    """Spell the V3.0 surface out so a future PR can't silently bloat it
    without updating this pin (and being noticed in review)."""
    added = ALLOWED_IMPORT_ROOTS_IO - ALLOWED_IMPORT_ROOTS
    assert added == {"httpx", "bs4", "lxml"}


def test_io_does_not_relax_FORBIDDEN_CALLS():
    """The escape-pattern ban is the real defence. The `io` profile only
    moves the IMPORT line. This guard pins that no PR sneaks a forbidden
    builtin out of the deny-list while shipping io support."""
    expected_core = {"eval", "exec", "compile", "__import__", "open",
                     "getattr", "setattr", "globals", "locals"}
    assert expected_core.issubset(FORBIDDEN_CALLS)


# ── new libs: pass under "io", fail under "pure" ─────────────────────────────


_CURATED_SAMPLES = [
    ("httpx import",   "import httpx\nx = 1\n"),
    ("httpx from",     "from httpx import AsyncClient\nx = 1\n"),
    ("bs4 from",       "from bs4 import BeautifulSoup\nx = 1\n"),
    ("lxml import",    "import lxml.etree\nx = 1\n"),
    ("lxml from",      "from lxml import html\nx = 1\n"),
]


@pytest.mark.parametrize("name,src", _CURATED_SAMPLES)
def test_curated_libs_allowed_under_io(name, src):
    report = check_tool_source(src, profile="io")
    assert report.ok, f"{name} rejected under io: {report.summary()}"


@pytest.mark.parametrize("name,src", _CURATED_SAMPLES)
def test_curated_libs_rejected_under_pure(name, src):
    report = check_tool_source(src, profile="pure")
    assert not report.ok, f"{name} unexpectedly accepted under pure: should be io-only"
    codes = {v.code for v in report.violations}
    assert "forbidden_import" in codes


# ── V2 scaffolding still works under "io" ────────────────────────────────────


_REGISTRATION_SHELL = textwrap.dedent("""
    from langchain_core.tools import tool
    from app.skills.base import Domain
    from app.skills.decorator import register

    @register(domain=Domain.RESEARCH, skill_name="probe",
              skill_display_name="Probe", skill_description="ping",
              skill_icon="🌐", enabled_by_default=False)
    @tool
    def probe() -> str:
        \"\"\"trivial\"\"\"
        return "ok"
""").strip()


def test_v2_scaffolding_unchanged_under_io():
    """A vanilla V2 tool must still pass under the new profile."""
    assert is_safe(_REGISTRATION_SHELL, profile="io")
    assert is_safe(_REGISTRATION_SHELL, profile="pure")


def test_call_tool_composition_works_under_io():
    src = _REGISTRATION_SHELL.replace(
        "from app.skills.decorator import register",
        "from app.skills.decorator import register\n"
        "from app.services.learning.learned_tool_dispatch import call_tool",
    )
    assert is_safe(src, profile="io"), "V2 composition import broken under io"


# ── adversarial: every forbidden pattern still fails under "io" ──────────────
# These mirror a subset of test_code_guard.py — re-asserting them here is on
# purpose, because the io profile is what V3 generators will run against and
# we want a single file you can audit for the io threat model.


_ADVERSARIAL = [
    ("eval call",        "x = eval('1+1')\n",                     "forbidden_call"),
    ("exec call",        "exec('print(1)')\n",                    "forbidden_call"),
    ("compile call",     "c = compile('1', '<s>', 'eval')\n",     "forbidden_call"),
    ("__import__ call",  "m = __import__('os')\n",                "forbidden_call"),
    ("open call",        "f = open('/etc/passwd')\n",             "forbidden_call"),
    ("getattr escape",   "g = getattr({}, '__class__')\n",        "forbidden_call"),
    ("globals call",     "g = globals()\n",                       "forbidden_call"),
    ("dunder attr",      "x = (1).__class__\n",                   "dunder_access"),
    ("dunder subclasses","s = ().__class__.__bases__[0].__subclasses__()\n", "dunder_access"),
    ("forbidden module", "import os\n",                           "forbidden_import"),
    ("forbidden socket", "import socket\n",                       "forbidden_import"),
    ("forbidden subproc","import subprocess\n",                   "forbidden_import"),
    ("forbidden ctypes", "import ctypes\n",                       "forbidden_import"),
    ("forbidden pickle", "import pickle\n",                       "forbidden_import"),
    ("forbidden marshal","import marshal\n",                      "forbidden_import"),
    ("forbidden pathlib","import pathlib\n",                      "forbidden_import"),
    ("star import",      "from httpx import *\n",                 "forbidden_import"),
    ("relative import",  "from . import sibling\n",               "forbidden_import"),
    ("global stmt",      "def f():\n    global x\n    x = 1\n",   "forbidden_statement"),
    ("nonlocal stmt",    "def f():\n    def g():\n        nonlocal y\n        y = 1\n    y = 0\n    g()\n",
                                                                  "forbidden_statement"),
]


@pytest.mark.parametrize("name,src,expected_code", _ADVERSARIAL)
def test_adversarial_still_blocked_under_io(name, src, expected_code):
    report = check_tool_source(src, profile="io")
    assert not report.ok, f"{name} unexpectedly accepted under io"
    codes = {v.code for v in report.violations}
    assert expected_code in codes, (
        f"{name}: expected {expected_code} in {codes}"
    )


# ── extra paranoia: httpx import doesn't accidentally bless `httpx.foo` ──────


def test_httpx_submodules_pass():
    """`dstdomain`-style suffix matching at the AST level: roots include
    the package, anything below it is fine."""
    assert is_safe("import httpx._config\nx = 1\n", profile="io")
    assert is_safe("from httpx._models import Response\nx = 1\n", profile="io")


def test_httpx_lookalike_modules_dont_sneak_in():
    """`httpx` is allowed; `httpx_evil` is NOT (root match is on the FIRST
    segment, not a substring/prefix)."""
    assert not is_safe("import httpx_evil\n", profile="io")


# ── invalid profile name ─────────────────────────────────────────────────────


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="unknown guard profile"):
        check_tool_source("x = 1\n", profile="not_a_profile")  # type: ignore[arg-type]


# ── default profile is "pure" (V2 backward compat) ───────────────────────────


def test_default_profile_is_pure():
    """A V2 caller that doesn't pass `profile` must get the pre-V3 behaviour."""
    # httpx must STILL be rejected at the default call-site.
    assert not is_safe("import httpx\n")
