# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/registration_gate.py
# @brief      Sprint 4b V2 J5 — registration-safety gate for generated @tool
#             code (stage 5 of the validation pipeline).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Stage 5 of the V2 validation pipeline — will registering this tool be
safe? (design note J0 §3.3, reframed.)

J0 first framed stage 5 as "register the tool, replay the 50 canonical
scenarios, assert no regression". But those 50 scenarios test the
signal/memory subsystems (shallow + idempotent) — they do NOT exercise
tool-calling/routing, so replaying them wouldn't catch a tool that
breaks the bound toolset. They stay ELY's CI regression net (run every
jalon), not a per-candidate gate.

The real per-candidate regression risk when you add a dynamically
generated tool to the LLM's bound set is narrower and sharper:

  - **name collision** — the tool's name shadows an existing registered
    tool, silently breaking it for every request;
  - **bind failure** — an untyped / undocumented signature makes
    ``bind_tools`` produce a broken (or no) args schema, which can throw
    for the whole conversation, not just this tool;
  - **unusable tool** — no docstring → the LLM has nothing to decide
    *when* to call it (see docs/ADDING_A_TOOL.md).

This module checks those statically via AST — **in-process, with zero
mutation of the global registry** (no import side effects, no
``@register`` firing). The live ``bind_tools`` round-trip happens at J7,
where binding is the actual job and the context is right; this gate is
the cheap structural pre-filter before then.

Pure module: caller passes the set of existing tool names (the
orchestrator will pass ``{t.name for t in get_skill_registry().all_tools}``).
"""
from __future__ import annotations

import ast
import keyword
from dataclasses import dataclass, field


# ── Signature model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolParam:
    name: str
    annotated: bool
    has_default: bool
    injected: bool  # Annotated[..., InjectedToolArg] — not an LLM-facing arg


@dataclass(frozen=True)
class ToolSignature:
    func_name: str
    tool_name: str  # explicit @tool("name") / name= override, else func_name
    is_async: bool
    has_docstring: bool
    has_tool_decorator: bool
    params: tuple[ToolParam, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GateIssue:
    code: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.code}] {self.detail}"


@dataclass(frozen=True)
class GateReport:
    ok: bool
    issues: tuple[GateIssue, ...] = field(default_factory=tuple)
    signature: ToolSignature | None = None

    def summary(self) -> str:
        if self.ok:
            return "ok"
        return "; ".join(str(i) for i in self.issues)


# ── AST helpers ────────────────────────────────────────────────────────────────


def _decorator_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for dec in fn.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _tool_name_override(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Return an explicit tool name from ``@tool("x")`` / ``@tool(name="x")``
    if present, else None (LangChain then uses the function name)."""
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        callee = dec.func
        if not (isinstance(callee, ast.Name) and callee.id == "tool"):
            continue
        # positional string: @tool("name")
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            return dec.args[0].value
        # keyword: @tool(name="...")
        for kw in dec.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
    return None


def _annotation_is_injected(annotation: ast.expr | None) -> bool:
    """True for ``Annotated[<type>, InjectedToolArg]`` (any metadata element
    named InjectedToolArg)."""
    if not isinstance(annotation, ast.Subscript):
        return False
    base = annotation.value
    if not (isinstance(base, ast.Name) and base.id == "Annotated"):
        return False
    sl = annotation.slice
    elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
    for el in elts:
        if isinstance(el, ast.Name) and el.id == "InjectedToolArg":
            return True
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name) and el.func.id == "InjectedToolArg":
            return True
    return False


def extract_tool_signature(source: str) -> ToolSignature | None:
    """Extract the registrable tool function's signature from ``source``.

    Picks the (async) function decorated with ``@tool``/``@register``;
    falls back to the only top-level function. Returns None if neither
    exists or the source doesn't parse.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not funcs:
        return None

    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for fn in funcs:
        if {"tool", "register"} & _decorator_names(fn):
            target = fn
            break
    if target is None:
        if len(funcs) != 1:
            return None
        target = funcs[0]

    decos = _decorator_names(target)
    a = target.args
    # Positional params (posonly + normal). Defaults align to the tail.
    positional = list(a.posonlyargs) + list(a.args)
    n_defaults = len(a.defaults)
    n_with_default = n_defaults  # last n_defaults positional args have defaults

    params: list[ToolParam] = []
    for idx, arg in enumerate(positional):
        if arg.arg == "self":
            continue
        has_default = idx >= len(positional) - n_with_default if n_with_default else False
        params.append(
            ToolParam(
                name=arg.arg,
                annotated=arg.annotation is not None,
                has_default=has_default,
                injected=_annotation_is_injected(arg.annotation),
            )
        )
    # keyword-only args (each may have its own default in a.kw_defaults)
    for kwarg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(
            ToolParam(
                name=kwarg.arg,
                annotated=kwarg.annotation is not None,
                has_default=default is not None,
                injected=_annotation_is_injected(kwarg.annotation),
            )
        )

    return ToolSignature(
        func_name=target.name,
        tool_name=_tool_name_override(target) or target.name,
        is_async=isinstance(target, ast.AsyncFunctionDef),
        has_docstring=bool(ast.get_docstring(target)),
        has_tool_decorator="tool" in decos,
        params=tuple(params),
    )


# ── The gate ─────────────────────────────────────────────────────────────────


def check_registration_safety(
    source: str,
    *,
    existing_names: set[str] | frozenset[str],
) -> GateReport:
    """Statically check that registering this tool won't break the bound
    toolset. Returns a :class:`GateReport` collecting all issues."""
    sig = extract_tool_signature(source)
    if sig is None:
        return GateReport(
            ok=False,
            issues=(GateIssue("no_tool_function", "no registrable tool function found"),),
        )

    issues: list[GateIssue] = []

    if not sig.has_tool_decorator:
        issues.append(
            GateIssue(
                "missing_tool_decorator",
                f"function '{sig.func_name}' is not decorated with @tool — not bindable",
            )
        )

    # name validity
    if not sig.tool_name.isidentifier() or keyword.iskeyword(sig.tool_name):
        issues.append(
            GateIssue("invalid_tool_name", f"tool name '{sig.tool_name}' is not a valid identifier")
        )

    # collision with an existing bound tool — the dangerous one
    if sig.tool_name in existing_names:
        issues.append(
            GateIssue(
                "name_collision",
                f"tool name '{sig.tool_name}' already exists — would shadow the registered tool",
            )
        )

    # the LLM needs a docstring to decide WHEN to call the tool
    if not sig.has_docstring:
        issues.append(
            GateIssue("missing_docstring", f"tool '{sig.tool_name}' has no docstring (LLM description)")
        )

    # every param needs an annotation so bind_tools can build the args schema
    for p in sig.params:
        if not p.annotated:
            issues.append(
                GateIssue(
                    "unannotated_param",
                    f"param '{p.name}' has no type annotation — breaks the args schema",
                )
            )

    return GateReport(ok=not issues, issues=tuple(issues), signature=sig)
