# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_loader.py
# @brief      Sprint 4b V2 J7a — safe in-process compiler: validated
#             python_tool source → bindable StructuredTool.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Turn a promoted ``python_tool`` skill into a live, bindable tool
(design note J0 §3.4) — the load-bearing, riskiest step of V2: this is
where generated code is actually exec'd in the backend process.

Two safety properties, by construction:

1. **Never exec un-guarded source.** ``compile_tool_source`` re-runs
   ``code_guard`` first (defense in depth — the guard already ran at
   generation time, but a promoted candidate may have sat in the DB, and
   we never want a path that exec's something the guard hasn't just
   approved). exec only runs module-level imports + the ``def`` (the
   function BODY runs only when the LLM later invokes the tool — that's
   gated by HITL + the composed tools' own gates).

2. **No global registry mutation at compile time.** The source carries
   ``@register(...)`` above ``@tool``; calling ``register`` would mutate
   the global skill registry as a side effect. So we **strip the
   ``@register`` decorator** before exec (keeping ``@tool``, which just
   wraps the function into a ``StructuredTool`` with no side effect) and
   parse the ``@register`` metadata separately. The caller (boot loader /
   promote, J7b) decides if/when/how to register, scoped + behind the
   feature flag.

Finally a **live bind check**: ``convert_to_openai_tool`` must succeed —
this is the real ``bind_tools`` round-trip the J5 gate deferred.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from app.services.learning.code_guard import check_tool_source
from app.services.learning.registration_gate import extract_tool_signature

_REGISTER_DECORATOR_NAMES = frozenset({"register"})


@dataclass(frozen=True)
class LoadResult:
    """Outcome of compiling a python_tool source.

    ``error_stage`` ∈ {guard, parse, no_function, exec, not_a_tool, bind}.
    On success ``tool`` is the StructuredTool, ``name`` its bound name,
    ``metadata`` the parsed @register kwargs (skill_name, domain, …).
    """

    ok: bool
    name: str | None = None
    tool: Any | None = None
    metadata: dict = field(default_factory=dict)
    error_stage: str | None = None
    error: str = ""


# ── @register metadata extraction (from the ORIGINAL source) ─────────────────


def extract_register_metadata(source: str) -> dict:
    """Parse the ``@register(...)`` kwargs into a dict. ``domain`` is
    captured as its attribute name (Domain.WORKSPACE → "WORKSPACE").
    Returns {} if there's no @register call."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)):
                continue
            if dec.func.id not in _REGISTER_DECORATOR_NAMES:
                continue
            meta: dict = {}
            for kw in dec.keywords:
                if kw.arg is None:
                    continue
                v = kw.value
                if isinstance(v, ast.Constant):
                    meta[kw.arg] = v.value
                elif isinstance(v, ast.Attribute):  # Domain.WORKSPACE
                    meta[kw.arg] = v.attr
                elif isinstance(v, ast.Name):
                    meta[kw.arg] = v.id
            return meta
    return {}


# ── @register decorator stripping (so exec doesn't mutate the registry) ──────


class _RegisterStripper(ast.NodeTransformer):
    def _strip(self, node):
        node.decorator_list = [
            d
            for d in node.decorator_list
            if not (
                (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in _REGISTER_DECORATOR_NAMES)
                or (isinstance(d, ast.Name) and d.id in _REGISTER_DECORATOR_NAMES)
            )
        ]
        return node

    def visit_FunctionDef(self, node):  # noqa: N802
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return self._strip(node)


def _strip_register(source: str) -> str:
    tree = ast.parse(source)
    tree = _RegisterStripper().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


# ── The compiler ─────────────────────────────────────────────────────────────


def compile_tool_source(source: str) -> LoadResult:
    """Compile validated python_tool source into a bindable StructuredTool.

    Precondition (enforced here too): the source passes code_guard. Never
    mutates the global registry. Returns a :class:`LoadResult`.
    """
    # [1] Defense in depth — never exec un-guarded source.
    guard = check_tool_source(source)
    if not guard.ok:
        return LoadResult(ok=False, error_stage="guard", error=guard.summary())

    # locate the function name (the namespace key after exec)
    sig = extract_tool_signature(source)
    if sig is None:
        return LoadResult(ok=False, error_stage="no_function", error="no tool function found")

    # [2] Strip @register so exec doesn't touch the global registry.
    try:
        stripped = _strip_register(source)
    except SyntaxError as exc:
        return LoadResult(ok=False, error_stage="parse", error=f"unparse failed: {exc}")

    # [3] exec module-level (imports + def). Function body runs only on invoke.
    namespace: dict[str, Any] = {"__name__": "ely_generated_tool"}
    try:
        exec(compile(stripped, "<ely_generated_tool>", "exec"), namespace, namespace)
    except Exception as exc:  # noqa: BLE001 — any load error becomes a result
        return LoadResult(ok=False, error_stage="exec", error=f"{type(exc).__name__}: {exc}")

    tool_obj = namespace.get(sig.func_name)
    # A LangChain tool exposes .name and an invoke method.
    if tool_obj is None or not hasattr(tool_obj, "name") or not hasattr(tool_obj, "invoke"):
        return LoadResult(
            ok=False,
            error_stage="not_a_tool",
            error=f"'{sig.func_name}' did not produce a bindable @tool object",
        )

    # [4] Live bind check — the real bind_tools round-trip (deferred from J5).
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        convert_to_openai_tool(tool_obj)
    except Exception as exc:  # noqa: BLE001
        return LoadResult(
            ok=False,
            error_stage="bind",
            error=f"tool is not bindable: {type(exc).__name__}: {exc}",
        )

    return LoadResult(
        ok=True,
        name=getattr(tool_obj, "name", sig.func_name),
        tool=tool_obj,
        metadata=extract_register_metadata(source),
    )
