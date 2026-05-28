# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_stubs.py
# @brief      Tests du stub generator ely_tools.py (Sprint 2.7 — Jalon 3).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Tests du générateur de stubs ``ely_tools.py``.

Couvre :
    1. Le fichier produit est un module Python valide (compile).
    2. Le fichier ne fait AUCUN import de ``app.*`` (self-contained).
    3. Les 15 stubs de l'allow-list sont présents.
    4. Aucun stub n'expose ``user_id`` (InjectedToolArg filtré).
    5. Le préambule contient ``_rpc``, ``_call_lock``, et les 3 helpers
       (``json_parse``, ``shell_quote``, ``retry``).
    6. Erreur claire si un tool de l'allow-list n'existe pas dans le
       registry.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1
from app.services.orchestrate_stubs import generate_stubs


# ──────────────────────────────────────────────────────────────────────
# Fixture — generate the stubs once per test (cheap)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def generated_stubs(tmp_path) -> tuple[Path, str]:
    """Generate ely_tools.py from the real V1 allow-list and return (path, text)."""
    target = tmp_path / "ely_tools.py"
    socket_path = tmp_path / "rpc.sock"
    generate_stubs(
        allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
        socket_path=socket_path,
        target_path=target,
    )
    return target, target.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# 1. The generated file is valid Python
# ──────────────────────────────────────────────────────────────────────


def test_generated_file_compiles(generated_stubs) -> None:
    path, text = generated_stubs
    # ast.parse raises SyntaxError if the file isn't valid Python.
    ast.parse(text, filename=str(path))


def test_generated_file_compile_with_builtin(generated_stubs) -> None:
    path, text = generated_stubs
    compile(text, str(path), "exec")  # raises SyntaxError on bad code


# ──────────────────────────────────────────────────────────────────────
# 2. Self-contained — no app.* imports
# ──────────────────────────────────────────────────────────────────────


def test_no_app_imports_in_generated_module(generated_stubs) -> None:
    _, text = generated_stubs
    tree = ast.parse(text)
    forbidden_prefixes = ("app", "app.")
    bad_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    bad_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "app" or mod.startswith("app."):
                bad_imports.append(mod)
    assert not bad_imports, (
        f"Generated ely_tools.py must be self-contained (stdlib only), "
        f"but imports from app.*: {bad_imports}"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. All 15 tools have stubs
# ──────────────────────────────────────────────────────────────────────


def test_all_allow_list_tools_have_a_stub(generated_stubs) -> None:
    _, text = generated_stubs
    tree = ast.parse(text)
    defined = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    missing = [name for name in SANDBOX_ALLOWED_TOOLS_V1 if name not in defined]
    assert not missing, (
        f"Tools in allow-list but missing from generated stubs: {missing}"
    )


def test_exactly_15_tool_stubs() -> None:
    # Belt-and-suspenders: the allow-list must be 15 (already covered in
    # test_orchestrate_skeleton.py) — but we re-assert it here so a
    # local change to this test catches drift early.
    assert len(SANDBOX_ALLOWED_TOOLS_V1) == 15


# ──────────────────────────────────────────────────────────────────────
# 4. user_id (InjectedToolArg) is filtered out
# ──────────────────────────────────────────────────────────────────────


def test_no_stub_exposes_user_id(generated_stubs) -> None:
    """The InjectedToolArg machinery must hide ``user_id`` from the LLM.

    Even one leak would let the script inside the sandbox spoof a
    different user — catastrophic in our multi-user model.
    """
    _, text = generated_stubs
    tree = ast.parse(text)

    leaked: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name in {"_rpc", "_recv_exact", "json_parse",
                             "shell_quote", "retry"}:
                continue  # framework helpers, not tool stubs
            arg_names = {a.arg for a in node.args.args}
            if "user_id" in arg_names:
                leaked.append(node.name)
    assert not leaked, (
        f"The following stubs expose user_id in their signature — "
        f"InjectedToolArg filtering failed: {leaked}"
    )


# ──────────────────────────────────────────────────────────────────────
# 5. Preamble has the RPC plumbing + the 3 QoL helpers
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected_symbol",
    [
        "_SOCKET_PATH",
        "_HEADER_FMT",
        "_HEADER_SIZE",
        "_call_lock",
        "_rpc",
        "_recv_exact",
        "OrchestrateError",
        "json_parse",
        "shell_quote",
        "retry",
    ],
)
def test_preamble_defines_symbol(generated_stubs, expected_symbol) -> None:
    _, text = generated_stubs
    tree = ast.parse(text)
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
    assert expected_symbol in defined, (
        f"Preamble must define {expected_symbol!r}, but only found {sorted(defined)}"
    )


# ──────────────────────────────────────────────────────────────────────
# 6. Robust error handling on bad inputs
# ──────────────────────────────────────────────────────────────────────


def test_unknown_tool_in_allow_list_raises(tmp_path) -> None:
    """If we ever drift between SANDBOX_ALLOWED_TOOLS_V1 and the real
    registry, ``generate_stubs`` must fail fast with a precise message."""
    bogus_allow_list = frozenset({"gmail_list_emails", "ce_tool_n_existe_pas"})
    with pytest.raises(ValueError, match="not found in registry"):
        generate_stubs(
            allowed_tools=bogus_allow_list,
            socket_path=tmp_path / "rpc.sock",
            target_path=tmp_path / "ely_tools.py",
        )


def test_missing_socket_parent_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        generate_stubs(
            allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
            socket_path=tmp_path / "does_not_exist" / "rpc.sock",
            target_path=tmp_path / "ely_tools.py",
        )


# ──────────────────────────────────────────────────────────────────────
# 7. Idempotence — re-running overwrites cleanly
# ──────────────────────────────────────────────────────────────────────


def test_regenerate_overwrites_existing_file(tmp_path) -> None:
    target = tmp_path / "ely_tools.py"
    target.write_text("# old garbage\n", encoding="utf-8")
    generate_stubs(
        allowed_tools=SANDBOX_ALLOWED_TOOLS_V1,
        socket_path=tmp_path / "rpc.sock",
        target_path=target,
    )
    text = target.read_text(encoding="utf-8")
    assert "old garbage" not in text
    assert "_rpc" in text
