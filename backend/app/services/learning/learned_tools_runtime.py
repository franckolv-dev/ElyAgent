# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/learned_tools_runtime.py
# @brief      Sprint 4b V2 J7b — runtime loader for promoted python_tool skills.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Load a user's promoted python_tool skills as live, bindable tools.

This is the runtime half of V2 (the generation/validation half is J1-J6,
the safe compiler is J7a/tool_loader). It reads the user's ``active``
``python_tool`` LearnedSkills from the DB, compiles each via
``tool_loader.compile_tool_source`` (which re-runs code_guard, strips
@register, and verifies bindability), and returns the StructuredTools so
the agent node can bind them alongside the built-in toolset.

Safety gates (defence in depth — the flag is the master switch):
  - ``LEARNED_PYTHON_TOOLS_ENABLED`` (env) must be truthy. Default OFF —
    so this is a no-op until explicitly turned on, and deploying the code
    changes nothing.
  - ``LEARNED_PYTHON_TOOLS_DISABLED`` (env) is a kill-switch that wins
    over ENABLED (instant off without redeploy).
  - A skill that fails to compile (guard / exec / bind) is SKIPPED + logged,
    never crashes the bind.

Scope: the current generator produces PURE (computation) tools, which run
end-to-end here. COMPOSITION tools (calling other ELY tools) need an
injected ``call_tool`` dispatcher + a generator-prompt update — a separate
coordinated jalon. Until then, a composition tool would compile + bind but
fail at invoke (undefined name), so it simply won't be produced/promoted.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.services.learning.tool_loader import compile_tool_source

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def python_tools_enabled() -> bool:
    """Master switch. False unless ENABLED is truthy AND DISABLED isn't."""
    if _truthy(os.getenv("LEARNED_PYTHON_TOOLS_DISABLED")):
        return False
    return _truthy(os.getenv("LEARNED_PYTHON_TOOLS_ENABLED"))


# Per-user cache of compiled tools — compile once, reuse across requests.
# Invalidated on promote/demote (J7c) and on demand.
_cache: dict[str, list[Any]] = {}
_lock = threading.Lock()


async def load_active_python_tools(user_id: str, *, use_cache: bool = True) -> list[Any]:
    """Return the user's active python_tool skills as bindable StructuredTools.

    Empty list when the feature flag is off, the user_id is empty, or the
    user has no (valid) python_tool skills. Never raises.
    """
    if not user_id or not python_tools_enabled():
        return []
    if use_cache:
        with _lock:
            cached = _cache.get(user_id)
        if cached is not None:
            return cached
    tools = await _compile_active(user_id)
    with _lock:
        _cache[user_id] = tools
    return tools


async def _compile_active(user_id: str) -> list[Any]:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.learned_skill import (
        LearnedSkill,
        SkillContentFormat,
        SkillStatus,
    )

    try:
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(LearnedSkill).where(
                        LearnedSkill.user_id == user_id,
                        LearnedSkill.status == SkillStatus.ACTIVE,
                        LearnedSkill.content_format == SkillContentFormat.PYTHON_TOOL,
                    )
                )
            ).scalars().all()
    except Exception as exc:  # noqa: BLE001 — never break the bind on a DB hiccup
        logger.warning("learned_tools_runtime: query failed for %s: %s", user_id[:8], exc)
        return []

    out: list[Any] = []
    seen: set[str] = set()
    for skill in rows:
        res = compile_tool_source(skill.content or "")
        if not res.ok:
            logger.warning(
                "learned_tools_runtime: skill %s (%s) skipped — %s: %s",
                skill.id, skill.name, res.error_stage, res.error,
            )
            continue
        name = res.name or skill.name
        if name in seen:
            logger.warning("learned_tools_runtime: duplicate tool name %s — skipping", name)
            continue
        seen.add(name)
        out.append(res.tool)
    if out:
        logger.info(
            "learned_tools_runtime: loaded %d python_tool(s) for user %s", len(out), user_id[:8],
        )
    return out


def invalidate(user_id: str | None = None) -> None:
    """Drop the cache for one user (None = all). Call after promote/demote."""
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


# ── J7b.2 wiring helpers ─────────────────────────────────────────────────────
# Two seams, shared by BOTH execution paths (chat: agent_node + tool_node ;
# mission: _get_actor_llms + dispatch_tool) so the wiring stays in sync.


async def append_learned_tools(tools: list[Any], user_id: str) -> list[Any]:
    """Return ``tools`` with the user's active python_tool skills appended.

    Used at BIND time. A learned tool NEVER shadows a builtin: a tool already
    present with the same name wins (defence in depth — registration_gate
    already rejects name collisions at promotion). Returns a list copy of
    ``tools`` unchanged when the feature flag is off (no learned tools).
    """
    learned = await load_active_python_tools(user_id)
    if not learned:
        return list(tools)
    have = {t.name for t in tools}
    return list(tools) + [t for t in learned if t.name not in have]


async def merge_into_tool_map(tool_map: dict[str, Any], user_id: str) -> None:
    """Add the user's active python_tool skills to a dispatch ``tool_map``
    IN PLACE, without shadowing a builtin (``setdefault`` → registry wins).

    Used at DISPATCH time. python_tools aren't in the global skill registry
    (per-user, by design), so tool_node / dispatch_tool wouldn't find them at
    invoke without this. No-op when the feature flag is off.
    """
    for t in await load_active_python_tools(user_id):
        tool_map.setdefault(t.name, t)
