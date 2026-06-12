# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/learned_tools_runtime_io.py
# @brief      Sprint 4b V3 J6.b.2 — runtime loader for `tool_profile=io`
#             LearnedSkills. Wraps each as an async StructuredTool whose
#             body dispatches into the sandbox runner (J2.c) over its
#             isolated network + Squid egress proxy ACL.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""V3 counterpart of :mod:`learned_tools_runtime`. The V2 module compiles
``python_tool`` skills in-process (composition + stdlib only, zero I/O);
this V3 module is for skills whose `tool_profile == "io"`: they declare
``network_allow`` / ``requires`` / ``requires_secrets`` and must execute
inside the sandbox runner — they **never run in this process**.

Why a separate module rather than a branch in ``learned_tools_runtime``:
  - The bind path is materially different (sync compile vs async dispatch).
  - V3 has runtime-only concerns (Vault, sandbox availability, secrets bag)
    that don't exist for V2. Keeping them out of the V2 path keeps V2's
    failure modes simple.
  - The flag (``LEARNED_PYTHON_TOOLS_IO_ENABLED``) gates the WHOLE V3 path.
    With OFF (the default), this module is a no-op; the V2 path is
    untouched.

The AST is the source of truth — we never ``exec`` the tool source in the
backend process. An io tool source can contain ``httpx.get(...)`` at top
level; running it here would EXIT the sandbox (the worst possible
failure mode). So we parse the AST for func_name / params / docstring,
build a pydantic args_schema with parameters typed ``Any`` (V3.0 — V3.x
can lift to real types), and construct the StructuredTool around a
coroutine that calls ``run_in_sandbox`` — the source itself only ever
exec's inside the runner subprocess.

Safety gates (defence in depth):
  - ``LEARNED_PYTHON_TOOLS_IO_ENABLED`` (env) must be truthy. Default OFF.
  - ``LEARNED_PYTHON_TOOLS_DISABLED`` (env) is a master kill-switch — wins
    over IO_ENABLED (kept in lockstep with the V2 module's contract).
  - A skill that fails to parse / build is SKIPPED with a warning, never
    crashes the bind.
  - The sandbox itself enforces the per-call quotas (RLIMIT, timeout,
    network ACL, etc.) — this module's contract is "the request gets
    there", not "the request is safe": that's J2's job.

Scope: J6.b.2 builds the StructuredTool + dispatches. Async secrets gate
(``check_secrets_exist``) + per-call audit log + canary HITL land in J6.c.
"""
from __future__ import annotations

import ast
import logging
import os
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import create_model

from app.services.learning.io_tool_audit import record_dispatch
from app.services.learning.registration_gate import extract_tool_signature
from app.services.learning.v3_declarations import (
    check_secrets_exist,
    parse_v3_declarations,
)
from app.services.sandbox_client import SandboxResult, run_in_sandbox

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


# ── Flags ────────────────────────────────────────────────────────────────────


def io_tools_enabled() -> bool:
    """True iff the V3 io-tools path is active.

    Off by default — deploying this module changes nothing. The master
    kill-switch ``LEARNED_PYTHON_TOOLS_DISABLED`` wins over the
    ``LEARNED_PYTHON_TOOLS_IO_ENABLED`` flag, mirroring V2's contract: one
    env var disables ALL learned tools (V2 + V3) without redeploy.
    """
    if _truthy(os.environ.get("LEARNED_PYTHON_TOOLS_DISABLED")):
        return False
    return _truthy(os.environ.get("LEARNED_PYTHON_TOOLS_IO_ENABLED"))


# ── Result formatting (SandboxResult → str for ToolMessage.content) ─────────


def format_sandbox_result(result: SandboxResult) -> str:
    """Turn a :class:`SandboxResult` into the string the LLM will see.

    Contract: the LLM only ever sees text. We don't return JSON dicts (the
    agent's tool-call loop converts the return value into a ToolMessage
    string anyway). For the happy path, that's the tool's own JSON-
    serialised result — preserves the type (a tool returning ``42``
    yields ``"42"``, returning ``"hi"`` yields ``"\\"hi\\""``).

    Failure modes get a human-readable prefix so the LLM can see WHAT
    failed (and decide whether to retry, ask the user, or fall back) —
    the prefix is also a stable shape that downstream signals (failure
    cases, Reasonix) can match on.
    """
    if result.is_ok:
        return result.result_json or ""
    if result.outcome == "raised":
        stage = result.stage or "call"
        err = result.error or "<unknown>"
        # Keep traces out — the LLM doesn't need full traces; the audit
        # log (J6.c) keeps them. A truncated error is enough to drive
        # the next decision.
        return f"[io tool {stage} error] {err[:300]}"
    if result.outcome == "timeout":
        return f"[io tool timeout] {result.detail or 'wall-clock exceeded'}"
    if result.outcome == "nonserializable":
        return (
            f"[io tool result not JSON-serialisable] "
            f"{(result.result_repr or '')[:300]}"
        )
    if result.outcome == "crashed":
        return f"[io tool crashed] {result.detail or 'wrapper failed'}"
    if result.is_unavailable:
        return "[io sandbox unreachable] please try again in a moment"
    # Catch-all (outcome="error", new outcomes a future runner introduces).
    return f"[io tool {result.outcome}] {result.detail or 'unknown'}"


# ── Schema construction (AST-only) ──────────────────────────────────────────


def _docstring_first_line(source: str) -> str | None:
    """Extract the docstring's first line from a tool source — used as the
    StructuredTool ``description`` (which feeds the LLM's understanding of
    when to call the tool). Returns ``None`` if no docstring or no parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                # The LLM reads the first line as a synopsis; the rest is
                # documentation for the generator/HITL reviewer.
                return doc.strip().splitlines()[0][:1024]
    return None


def _build_args_schema(sig_params: tuple) -> type:
    """Build a pydantic model class for the tool's args. All params typed
    ``Any`` in V3.0 — robust to whatever annotation shapes the generator
    writes, and the LLM gets type guidance from the docstring. V3.x can
    lift this to real types via a whitelisted AST type parser."""
    fields: dict[str, tuple] = {}
    for p in sig_params:
        if p.injected:
            # Annotated[..., InjectedToolArg] — populated by the agent
            # at dispatch, not LLM-facing. Skip from the schema.
            continue
        # Required if no default, optional with None if has default.
        if p.has_default:
            fields[p.name] = (Any, None)
        else:
            fields[p.name] = (Any, ...)
    # `create_model` requires at least the class name; an empty body is OK
    # (a no-arg tool exists — eg. "get_current_weather()").
    return create_model("IoToolArgs", **fields)


# ── The actual build ────────────────────────────────────────────────────────


async def dispatch_io_source(
    *,
    source: str,
    func_name: str,
    tool_name: str,
    kwargs: dict[str, Any],
    secret_labels: tuple[str, ...],
    network_allow: tuple[str, ...],
    user_id: str,
    skill_id: str,
    vault_service: Any,
    timeout_s: int,
) -> str:
    """L'opération io complète : secrets résolus à l'APPEL, dispatch
    sandbox, audit, formatage LLM-lisible. Extraite de la closure
    ``_make_dispatcher`` (V4.1, 2026-06-12) pour être réutilisée TELLE
    QUELLE par les outils io GRADUÉS (``graduated/*_io_tool.py``) — un
    outil gradué garde exactement ce chemin d'exécution sandboxé, seule
    sa source vient d'un fichier core au lieu d'une row learned_skill.

    Ne lève jamais : tout échec retourne une chaîne claire pour le LLM
    (il peut demander à l'utilisateur ou se rabattre).
    """
    # Resolve secrets at CALL time (vault may unlock/lock between
    # bind and call, labels may rotate). If resolution fails, return
    # a clear LLM-visible string — don't raise — so the loop can
    # continue (the LLM may ask the user, or fall back).
    secrets: dict[str, str] = {}
    if secret_labels and vault_service is not None:
        for label in secret_labels:
            try:
                secrets[label] = await vault_service.get_secret(user_id, label)
            except KeyError:
                logger.info(
                    "io dispatch %s: secret %r not in vault for %s",
                    func_name, label, user_id[:8],
                )
                await record_dispatch(
                    user_id=user_id, skill_id=skill_id,
                    tool_name=tool_name, outcome="config_error",
                    secrets_used=secret_labels,
                    network_allow=network_allow,
                    error=f"secret '{label}' not provisioned",
                )
                return f"[io tool config error] secret '{label}' not provisioned"
            except PermissionError:
                logger.info(
                    "io dispatch %s: vault locked for %s",
                    func_name, user_id[:8],
                )
                await record_dispatch(
                    user_id=user_id, skill_id=skill_id,
                    tool_name=tool_name, outcome="config_error",
                    secrets_used=secret_labels,
                    network_allow=network_allow,
                    error="vault locked",
                )
                return f"[io tool config error] vault is locked; please unlock to use this tool"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "io dispatch %s: vault crash on %r: %s",
                    func_name, label, exc,
                )
                await record_dispatch(
                    user_id=user_id, skill_id=skill_id,
                    tool_name=tool_name, outcome="config_error",
                    secrets_used=secret_labels,
                    network_allow=network_allow,
                    error=f"vault error: {exc}"[:500],
                )
                return f"[io tool config error] vault error: {exc}"
    elif secret_labels and vault_service is None:
        # Misconfiguration — the tool declares secrets but no vault
        # service was injected. Don't pretend it worked.
        await record_dispatch(
            user_id=user_id, skill_id=skill_id,
            tool_name=tool_name, outcome="config_error",
            secrets_used=secret_labels,
            network_allow=network_allow,
            error="no vault service in session",
        )
        return (
            "[io tool config error] tool requires secrets but vault "
            "is not available in this session"
        )

    result = await run_in_sandbox(
        source,
        func_name,
        kwargs=kwargs,
        secrets=secrets,
        timeout_s=timeout_s,
    )

    # Audit the call. The labels of secrets we resolved (not the
    # values); the declared network domains (not the actual URLs);
    # a 500-char error truncation. Best-effort — record_dispatch
    # logs + swallows on any DB failure.
    await record_dispatch(
        user_id=user_id,
        skill_id=skill_id,
        tool_name=tool_name,
        outcome=result.outcome,
        duration_s=result.duration_s,
        secrets_used=tuple(secrets.keys()),  # actually resolved
        network_allow=network_allow,
        error=(result.error or result.detail) if not result.is_ok else None,
    )
    return format_sandbox_result(result)


def _make_dispatcher(
    *,
    source: str,
    func_name: str,
    tool_name: str,
    secret_labels: tuple[str, ...],
    network_allow: tuple[str, ...],
    user_id: str,
    skill_id: str | None,
    vault_service: Any,
    timeout_s: int,
):
    """Build the async coroutine that StructuredTool will call. Kept as a
    factory so each tool gets its own closure (no shared mutable state).
    Le corps réel vit dans :func:`dispatch_io_source` (partagé avec les
    outils io gradués)."""

    # The audit takes a non-empty skill_id (the FK column is non-nullable).
    # For unit-test builds without a persisted skill we fall back to a
    # synthetic id; the test asserts don't read it. Production callers
    # always supply the real DB id.
    _skill_id = skill_id or f"<unsaved:{func_name}>"

    async def _dispatch(**kwargs: Any) -> str:
        return await dispatch_io_source(
            source=source,
            func_name=func_name,
            tool_name=tool_name,
            kwargs=kwargs,
            secret_labels=secret_labels,
            network_allow=network_allow,
            user_id=user_id,
            skill_id=_skill_id,
            vault_service=vault_service,
            timeout_s=timeout_s,
        )

    return _dispatch


def build_io_structured_tool(
    *,
    source: str,
    user_id: str,
    skill_id: str | None = None,
    vault_service: Any = None,
    timeout_s: int = 8,
) -> StructuredTool | None:
    """Build an async :class:`StructuredTool` for one io tool source.

    Returns ``None`` (logged at warning level) if the source doesn't parse
    or doesn't declare a registrable ``@tool`` / ``@register`` function —
    never raises on bad input.

    Args:
        source: The python_tool source. We never ``exec`` it here — AST only.
        user_id: Owner of the skill, passed to Vault for secret resolution.
        skill_id: Optional, used purely for log breadcrumbs.
        vault_service: Async vault that exposes ``get_secret(user_id, label)``.
            ``None`` is OK for a tool with no ``requires_secrets``; the
            dispatcher returns a config-error string if a tool that declares
            secrets is invoked without a vault.
        timeout_s: Wall-clock per call. Passed through to the sandbox runner.
    """
    if not source or not source.strip():
        return None

    sig = extract_tool_signature(source)
    if sig is None or not (sig.has_tool_decorator or sig.has_docstring):
        # No @tool decorator AND no docstring — not a real generated tool.
        # (We accept docstring-only because some generators emit @register
        # without @tool — registration_gate already validates the @tool
        # presence at build time; this is just runtime defence.)
        logger.warning(
            "io build skipped: skill %s has no usable tool signature",
            skill_id or "?",
        )
        return None

    decls = parse_v3_declarations(source)
    description = (
        _docstring_first_line(source)
        or f"V3 io tool {sig.tool_name}"
    )
    args_schema = _build_args_schema(sig.params)

    dispatcher = _make_dispatcher(
        source=source,
        func_name=sig.func_name,
        tool_name=sig.tool_name,
        secret_labels=decls.requires_secrets,
        network_allow=decls.network_allow,
        user_id=user_id,
        skill_id=skill_id,
        vault_service=vault_service,
        timeout_s=timeout_s,
    )

    return StructuredTool.from_function(
        coroutine=dispatcher,
        name=sig.tool_name,
        description=description,
        args_schema=args_schema,
    )


# ── List loader (DB-touching) ───────────────────────────────────────────────


async def load_active_io_tools(
    user_id: str,
    *,
    vault_service: Any = None,
    timeout_s: int = 8,
) -> list[StructuredTool]:
    """Return the user's active io python_tool skills as bindable
    StructuredTools.

    Returns ``[]`` when:
      - The IO flag is off (default).
      - The user has no active io skills.
      - The DB read fails (logged; we never break the bind on a DB hiccup —
        same defensive contract as ``learned_tools_runtime.load_active_python_tools``).

    Args:
        user_id: User whose skills to load.
        vault_service: Optional. Required for tools that declare
            ``requires_secrets``. A bare ``None`` is fine for the no-secret
            subset; tools needing secrets degrade to a config-error
            response per call.
        timeout_s: Per-call sandbox wall-clock for every tool built here.
            V3.x might lift this to per-skill.
    """
    if not io_tools_enabled():
        return []

    # Imports here (not at module top) to avoid a circular import in test
    # collection — mirrors the V2 module's pattern.
    from sqlalchemy import select

    from app.database import async_session
    from app.models.learned_skill import (
        LearnedSkill,
        SkillContentFormat,
        SkillStatus,
        SkillToolProfile,
    )

    try:
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(LearnedSkill).where(
                        LearnedSkill.user_id == user_id,
                        LearnedSkill.status == SkillStatus.ACTIVE,
                        LearnedSkill.content_format == SkillContentFormat.PYTHON_TOOL,
                        LearnedSkill.tool_profile == SkillToolProfile.IO,
                    )
                )
            ).scalars().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "load_active_io_tools: query failed for %s: %s",
            user_id[:8], exc,
        )
        return []

    out: list[StructuredTool] = []
    seen: set[str] = set()
    _bound: set[str] = set()
    for skill in rows:
        # ── Secrets gate AT BIND TIME (Sprint 4b V3 J6.c.1) ──────────
        # Different from the per-call gate inside the dispatcher: this
        # gate keeps a tool OUT of the LLM's view entirely when its
        # declared secrets aren't provisioned right now. The LLM never
        # sees a tool it can't call, so it can't "burn a turn" trying.
        # The per-call gate (in _make_dispatcher) is the fallback for
        # the race where the user removes a secret between bind and
        # call — that returns a config-error string mid-conversation.
        decls = parse_v3_declarations(skill.content or "")
        if decls.requires_secrets:
            gate = await check_secrets_exist(
                decls, user_id=user_id, vault_service=vault_service,
            )
            if not gate.ok:
                # check_secrets_exist degrades-open on vault crashes
                # (returns ok=True), so a non-ok here is a genuine
                # missing-secret. Skip + log; no audit row (the call
                # never happened — bind exclusion is a separate signal
                # that V3.x can surface via the admin UI).
                logger.info(
                    "load_active_io_tools: excluding skill %s (%s) — %s",
                    skill.id, skill.name, gate.summary(),
                )
                continue

        try:
            tool = build_io_structured_tool(
                source=skill.content or "",
                user_id=user_id,
                skill_id=skill.id,
                vault_service=vault_service,
                timeout_s=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "load_active_io_tools: build failed for skill %s: %s",
                skill.id, exc,
            )
            continue
        if tool is None:
            continue
        if tool.name in seen:
            logger.warning(
                "load_active_io_tools: duplicate name %s — skipping", tool.name,
            )
            continue
        seen.add(tool.name)
        out.append(tool)
        _bound.add(tool.name)
    # Registre des noms io bindés (v1.15.0) — consommé par le canary HITL
    # de tool_node pour distinguer un outil io d'un builtin homonyme.
    # Rafraîchi à CHAQUE bind (y compris vers set() vide : une démotion ou
    # le flag repassé off purgent l'entrée au tour suivant).
    _BOUND_IO_NAMES[user_id] = _bound
    if out:
        logger.info(
            "load_active_io_tools: loaded %d io tool(s) for user %s",
            len(out), user_id[:8],
        )
    return out


# ── Canary HITL (Sprint 4b V3, design §5.6 — v1.15.0) ───────────────────────
# Les outils io sont intrinsèquement plus risqués (egress réel, code
# auto-généré) : leurs N premières invocations passent par HITL avant que
# l'outil ne soit « de confiance ». Le compteur s'appuie sur la table
# d'audit io_tool_dispatches (J6.c.1) — une ligne par appel, déjà écrite
# par le dispatcher : aucun nouvel état à maintenir.

# user_id → noms des outils io actuellement bindés (rafraîchi à chaque bind)
_BOUND_IO_NAMES: dict[str, set[str]] = {}

_CANARY_DEFAULT_CALLS = 10


def canary_calls_threshold() -> int:
    """Nombre d'appels sous HITL avant confiance. 0 (ou invalide) = désactivé.
    Env : LEARNED_IO_TOOLS_CANARY_CALLS (défaut 10)."""
    try:
        return int(os.environ.get(
            "LEARNED_IO_TOOLS_CANARY_CALLS", str(_CANARY_DEFAULT_CALLS),
        ))
    except ValueError:
        return _CANARY_DEFAULT_CALLS


def is_bound_io_tool(user_id: str, tool_name: str) -> bool:
    return tool_name in _BOUND_IO_NAMES.get(user_id, ())


async def _dispatch_count(user_id: str, tool_name: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.io_tool_dispatch import IoToolDispatch

    async with async_session() as db:
        return int((await db.execute(
            select(func.count()).select_from(IoToolDispatch).where(
                IoToolDispatch.user_id == user_id,
                IoToolDispatch.tool_name == tool_name,
            )
        )).scalar_one() or 0)


async def io_canary_requires_hitl(user_id: str, tool_name: str) -> bool:
    """True si ``tool_name`` est un outil io de ce user encore en période
    canary. Fail-closed : un outil io dont l'historique est illisible
    (erreur DB) reste sous HITL — un outil auto-généré avec egress réel ne
    s'exécute jamais sans validation par défaut de panne."""
    if not io_tools_enabled():
        return False
    if not user_id or not is_bound_io_tool(user_id, tool_name):
        return False
    threshold = canary_calls_threshold()
    if threshold <= 0:
        return False
    try:
        count = await _dispatch_count(user_id, tool_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "io_canary: comptage des dispatches illisible pour %s/%s (%s) — "
            "HITL conservé (fail-closed)", user_id[:8], tool_name, exc,
        )
        return True
    if count < threshold:
        logger.info(
            "io_canary: %s en période canary pour %s (%d/%d appels) — HITL",
            tool_name, user_id[:8], count, threshold,
        )
        return True
    return False
