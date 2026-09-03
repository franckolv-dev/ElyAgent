# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_code_guard.py
# @brief      Sprint 4b V2 J2 — exhaustive bypass tests for the AST guard.
# @license    MIT
# =============================================================================
"""Tests for ``app/services/learning/code_guard.py``.

This is the security gate of V2, so the suite is adversarial: it
enumerates the sandbox-escape vectors (dunder walk, getattr, __import__,
__builtins__, star/relative imports, eval/exec/open) and asserts each is
caught — while a realistic composed tool + pure-compute stdlib passes.

A regression here = arbitrary code running in the backend process. Treat
a newly-discovered bypass as a P0 with a new test row.
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.learning.code_guard import (
    ALLOWED_IMPORT_EXACT,
    ALLOWED_IMPORT_ROOTS,
    FORBIDDEN_CALLS,
    check_tool_source,
    is_safe,
)


def _codes(source: str) -> set[str]:
    return {v.code for v in check_tool_source(source).violations}


# ── 1. Realistic valid tool passes ───────────────────────────────────────────


VALID_COMPOSED_TOOL = textwrap.dedent(
    '''
    from __future__ import annotations

    import re
    from datetime import datetime
    from typing import Annotated

    from langchain_core.tools import InjectedToolArg, tool

    from app.skills.base import Domain
    from app.skills.decorator import register


    @register(
        domain=Domain.WORKSPACE,
        skill_name="invoice_digest",
        skill_display_name="Invoice digest",
        skill_description="Summarise an invoice number + date from text.",
        skill_icon="🧾",
        enabled_by_default=False,
    )
    @tool
    async def invoice_digest(
        text: str,
        user_id: Annotated[str, InjectedToolArg] = "",
    ) -> str:
        """Extract the invoice number and format today\'s date."""
        match = re.search(r"INV-(\\d+)", text)
        number = match.group(1) if match else "unknown"
        stamp = datetime.now().strftime("%Y-%m-%d")
        rows = [number, stamp]
        return " | ".join(rows)
    '''
)


def test_valid_composed_tool_passes() -> None:
    report = check_tool_source(VALID_COMPOSED_TOOL)
    assert report.ok, report.summary()
    assert is_safe(VALID_COMPOSED_TOOL)


@pytest.mark.parametrize(
    "snippet",
    [
        "import math\nx = math.sqrt(4)\n",
        "from collections.abc import Iterable\n",            # submodule of allowed root
        "from collections import OrderedDict\n",
        "import json\ny = json.dumps({'a': 1})\n",
        "import statistics\nm = statistics.mean([1, 2, 3])\n",
        "from itertools import chain\n",
        "import re\nr = re.compile(r'\\\\d+')\n",            # re.compile = attribute call, OK
        "from datetime import datetime\nn = datetime.now()\n",
        "d = {'k': 1}\nv = d.get('k')\n",                    # plain attribute, not dunder
        "vals = [i * 2 for i in range(3)]\n",                # comprehension + range OK
    ],
)
def test_pure_stdlib_snippets_pass(snippet: str) -> None:
    report = check_tool_source(snippet)
    assert report.ok, report.summary()


# ── 2. Forbidden imports ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\n",
        "import sys\n",
        "import subprocess\n",
        "import socket\n",
        "import shutil\n",
        "import pathlib\n",
        "from os import path\n",
        "from subprocess import run\n",
        "import urllib.request\n",
        "import requests\n",
        "import app.config\n",                 # app.* not blanket-allowed
        "from app.database import engine\n",   # only app.skills.* scaffolding allowed
        "import importlib\n",
    ],
)
def test_forbidden_imports(snippet: str) -> None:
    assert "forbidden_import" in _codes(snippet), snippet


def test_star_import_forbidden() -> None:
    assert "forbidden_import" in _codes("from re import *\n")


def test_relative_import_forbidden() -> None:
    assert "forbidden_import" in _codes("from . import sibling\n")


def test_allowed_scaffolding_imports_pass() -> None:
    src = (
        "from langchain_core.tools import tool\n"
        "from app.skills.decorator import register\n"
        "from app.skills.base import Domain\n"
        "from __future__ import annotations\n"
    )
    assert check_tool_source(src).ok


# ── 3. Forbidden builtin calls ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "eval('1+1')\n",
        "exec('x=1')\n",
        "compile('1', '<s>', 'eval')\n",
        "__import__('os')\n",
        "open('/etc/passwd')\n",
        "globals()\n",
        "locals()\n",
        "vars()\n",
        "getattr(object(), 'x')\n",
        "setattr(object(), 'x', 1)\n",
        "delattr(object(), 'x')\n",
        "input('?')\n",
        "breakpoint()\n",
    ],
)
def test_forbidden_calls(snippet: str) -> None:
    assert "forbidden_call" in _codes(snippet), snippet


def test_every_forbidden_call_name_is_caught() -> None:
    """Belt-and-suspenders: each name in FORBIDDEN_CALLS, used as a bare
    call, must produce a forbidden_call (or, for dunder names, at least a
    violation)."""
    for name in FORBIDDEN_CALLS:
        codes = _codes(f"{name}()\n")
        assert codes, f"{name}() produced no violation"
        # __import__ also trips dunder_access; both are fine, just not empty
        assert "forbidden_call" in codes or "dunder_access" in codes, name


def test_re_compile_attribute_call_not_flagged_but_builtin_compile_is() -> None:
    # builtin compile() — forbidden
    assert "forbidden_call" in _codes("compile('x','<s>','eval')\n")
    # re.compile() — an Attribute call, must NOT be flagged
    assert check_tool_source("import re\nre.compile('x')\n").ok


# ── 4. Dunder escape vectors ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "().__class__\n",
        "().__class__.__bases__[0].__subclasses__()\n",   # the classic full chain
        "x = object()\ny = x.__dict__\n",
        "f = (lambda: 0)\nc = f.__globals__\n",
        "t = type.__subclasses__\n",
    ],
)
def test_dunder_attribute_access_forbidden(snippet: str) -> None:
    assert "dunder_access" in _codes(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "b = __builtins__\n",
        "__import__\n",
        "n = __name__\n",
    ],
)
def test_dunder_name_reference_forbidden(snippet: str) -> None:
    assert "dunder_access" in _codes(snippet), snippet


def test_getattr_dunder_combo_is_caught() -> None:
    # getattr(x, '__class__') — getattr itself is forbidden, string arg is a
    # Constant so the dunder hides in a literal; the getattr ban catches it.
    assert "forbidden_call" in _codes("getattr(object(), '__class__')\n")


# ── 5. global / nonlocal ──────────────────────────────────────────────────────


def test_global_forbidden() -> None:
    src = "g = 0\ndef f():\n    global g\n    g = 1\n"
    assert "forbidden_statement" in _codes(src)


def test_nonlocal_forbidden() -> None:
    src = "def outer():\n    x = 0\n    def inner():\n        nonlocal x\n        x = 1\n    return inner\n"
    assert "forbidden_statement" in _codes(src)


# ── 6. Syntax errors ──────────────────────────────────────────────────────────


def test_syntax_error_reported() -> None:
    report = check_tool_source("def broken(:\n    pass\n")
    assert not report.ok
    assert report.violations[0].code == "syntax_error"


# ── 7. All violations are collected, not just the first ───────────────────────


def test_multiple_violations_collected() -> None:
    src = textwrap.dedent(
        """
        import os
        import socket
        x = eval('1')
        y = ().__class__
        """
    )
    report = check_tool_source(src)
    assert not report.ok
    # 2 forbidden_import + 1 forbidden_call + 1 dunder_access (at least)
    assert len(report.violations) >= 4, report.summary()
    codes = {v.code for v in report.violations}
    assert {"forbidden_import", "forbidden_call", "dunder_access"} <= codes


# ── 8. Violations carry a location ────────────────────────────────────────────


def test_violation_has_lineno() -> None:
    src = "x = 1\nimport os\n"
    v = check_tool_source(src).violations[0]
    assert v.code == "forbidden_import"
    assert v.lineno == 2


# ── 9. Allow-list is configurable ─────────────────────────────────────────────


def test_custom_allow_list_can_permit_a_module() -> None:
    # default: random is forbidden
    assert "forbidden_import" in _codes("import random\n")
    # but a caller can widen the root set
    report = check_tool_source(
        "import random\n",
        allowed_import_roots=ALLOWED_IMPORT_ROOTS | {"random"},
    )
    assert report.ok


def test_custom_exact_allow_list_pins_a_module() -> None:
    report = check_tool_source(
        "from app.agent.tools.drive_tool import drive_search\n",
        allowed_import_exact=ALLOWED_IMPORT_EXACT | {"app.agent.tools.drive_tool"},
    )
    assert report.ok
    # without the override it is forbidden
    assert "forbidden_import" in _codes(
        "from app.agent.tools.drive_tool import drive_search\n"
    )


# ── 10. async constructs are fine ─────────────────────────────────────────────


def test_async_def_and_await_pass() -> None:
    src = textwrap.dedent(
        """
        async def f(x):
            r = await g(x)
            return r
        """
    )
    assert check_tool_source(src).ok
