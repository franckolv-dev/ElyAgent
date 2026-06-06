# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/learned_tool_dispatch.py
# @brief      Sprint 4b V2 (composition N1) — runtime support for generated
#             python_tools that compose OTHER ELY tools via call_tool().
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""``call_tool`` — the bridge a generated COMPOSITION tool uses to invoke
already-registered ELY tools.

A generated python_tool may package a multi-tool workflow into one call::

    from app.services.learning.learned_tool_dispatch import call_tool

    @tool
    async def unread_summary(query: str) -> str:
        \"\"\"Summarise unread emails matching a query.\"\"\"
        emails = await call_tool("gmail_list_emails", {"query": query})
        ...

Why an explicit import (not a magic injected global): so ruff (F821) and
mypy see a defined name. The import is allow-listed in ``code_guard`` and
resolves to the real dispatcher at runtime; the smoke sandbox stubs it.

Safety (V1 composition is the SAFE subset):
  - ``call_tool`` REFUSES any critical / HITL-locked / never-autonomous tool
    (delete, send, share, ssh, vault, raw API…). Re-applying HITL from inside
    a tool invocation isn't wired, so composing a destructive tool is
    forbidden — it raises ValueError. Composing destructive tools is a
    future, separate jalon.
  - The generator is only ever shown the composable (safe) subset, and this
    refusal is the runtime backstop (defence in depth).

Runtime context: builtin tools get hidden args injected by the dispatcher
(tool_node / dispatch_tool) — Google credentials and user_id. call_tool runs
*inside* a tool invocation, past that injection point, so it re-injects the
same args keyed by ``LEARNED_TOOL_USER_ID`` (a ContextVar the dispatcher sets
before invoking any tool — same pattern as ORCHESTRATE_CONVERSATION_ID).
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# Set by tool_node (chat) and dispatch_tool (mission) before invoking a tool.
# ContextVars propagate per asyncio task, so concurrent turns don't leak each
# other's user. Empty string = unknown (creds/user_id injection then no-ops).
LEARNED_TOOL_USER_ID: ContextVar[str] = ContextVar("learned_tool_user_id", default="")


def _critical_names() -> frozenset[str]:
    """The union of tool sets a composition tool may NOT call."""
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS
    from app.services.security_filter import (
        ALWAYS_CRITICAL_TOOLS,
        NEVER_AUTONOMOUS_TOOLS,
    )

    return ALWAYS_CRITICAL_TOOLS | NEVER_AUTONOMOUS_TOOLS | LOCKED_HITL_TOOLS


def composable_tool_names() -> set[str]:
    """Registered tool names a generated python_tool MAY compose — the safe
    subset (excludes critical / HITL-locked / never-autonomous tools).

    Best-effort: returns an empty set on any registry hiccup.
    """
    try:
        from app.skills.registry import get_skill_registry

        allnames = get_skill_registry().all_tool_names()
    except Exception as exc:  # noqa: BLE001 — never break generation/validation
        logger.debug("composable_tool_names: registry lookup failed: %s", exc)
        return set()
    critical = _critical_names()
    return {n for n in allnames if n not in critical}


def is_composable(name: str) -> bool:
    """True iff ``name`` is registered AND safe to compose (not critical)."""
    return name in composable_tool_names()


async def call_tool(name: str, args: dict | None = None) -> Any:
    """Invoke a registered, NON-CRITICAL ELY tool from inside a composition
    tool, injecting the same hidden args the dispatcher injects for builtins.

    Raises ``ValueError`` for an unknown name or a critical/HITL tool — those
    cannot be composed in V1 (no HITL from inside an invocation).
    """
    if not isinstance(name, str) or not name:
        raise ValueError("call_tool: tool name must be a non-empty string")
    if name in _critical_names():
        raise ValueError(
            f"call_tool: {name!r} is a critical / HITL-gated tool and cannot be "
            "composed (V1 composition allows safe, non-destructive tools only)"
        )

    from app.skills.registry import get_skill_registry

    tool = {t.name: t for t in get_skill_registry().all_tools}.get(name)
    if tool is None:
        raise ValueError(f"call_tool: unknown tool {name!r}")

    # Re-inject the hidden args the dispatcher gives builtins, keyed by the
    # current user (set in a ContextVar before the composition tool ran).
    from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS

    call_args = dict(args or {})
    user_id = LEARNED_TOOL_USER_ID.get()
    if name in GOOGLE_TOOLS:
        from app.services.credential_store import get_credential_store

        call_args["user_google_credentials_json"] = get_credential_store().get(user_id) or ""
    if name in USER_ID_TOOLS:
        call_args["user_id"] = user_id

    logger.info("call_tool: composing %s (user=%s)", name, (user_id[:8] or "?"))
    return await tool.ainvoke(call_args)
