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

import asyncio
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

    # ── Garde de graduation (Sprint 4d J4) ────────────────────────────
    # Un tool CORE homonyme d'un learned actif = la PR de graduation a été
    # mergée et l'image rebuildée : le core prend le relais. La row passe
    # status='graduated' (idempotent, loggé) et on ne binde JAMAIS deux
    # outils homonymes — le comportement LangChain serait indéfini.
    rows = await _reconcile_graduated(rows)

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
        out.append(_wrap_with_usage_bump(res.tool, skill.id))
    if out:
        logger.info(
            "learned_tools_runtime: loaded %d python_tool(s) for user %s", len(out), user_id[:8],
        )
    return out


_BUMP_TIMEOUT_S = 5.0  # borne dure : un DB qui hoquette ne gèle jamais l'appel


def _wrap_with_usage_bump(tool: Any, skill_id: str) -> Any:
    """Sprint 4d (gap J1 découvert en réel) — compte CHAQUE invocation d'un
    python_tool pur dans ``use_count``/``last_used_at``.

    ``bump_skill_usage`` n'était câblé que pour les playbooks (skill_view) ;
    les python_tools purs passaient par le binding LLM sans jamais bumper —
    la gate « invocations » de la graduation restait à zéro quel que soit
    l'usage réel (constaté sur fibonacci, 11 appels → use_count=0… parce
    qu'en plus le LLM répondait de tête, mais c'est une autre histoire).
    Les tools io ont déjà leur trace (io_tool_dispatches).

    Le bump est **attendu** (chemin async) / **bloqué jusqu'à commit**
    (chemin sync), pas fire-and-forget. L'ancienne version programmait le
    bump via ``create_task``/``run_coroutine_threadsafe`` SANS en garder la
    référence ni l'attendre : asyncio ne tient qu'une référence faible sur
    une task non stockée → elle pouvait être collectée AVANT de committer
    (d'où « ~6/8 bumps » en prod sur fibonacci), et deux invocations
    successives empilaient deux écritures concurrentes qui se marchaient
    dessus (flakiness CI : ``use_count=1`` au lieu de 2). En attendant le
    bump dans chaque invocation, les écritures se sérialisent et chaque
    incrément est garanti committé avant le retour de l'outil.

    ``bump_skill_usage`` fait déjà un ``UPDATE ... use_count = use_count + 1``
    atomique (cf. ``active_skills.py``) ; ici on garantit juste qu'il aboutit.
    Le compteur reste du confort : toute erreur (et le timeout) est avalée,
    l'appel de l'outil n'est jamais cassé — seul un délai borné est ajouté.
    La boucle asyncio est capturée au moment du compile (contexte async) ;
    un tool sync invoqué depuis l'executor LangChain re-schedule dessus.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    async def _bump_awaited() -> None:
        """Chemin async : on est sur la loop, on attend l'UPDATE atomique."""
        try:
            from app.services.learning.active_skills import bump_skill_usage
            await bump_skill_usage(skill_id)
        except Exception as exc:  # noqa: BLE001 — jamais au prix de l'appel
            logger.debug("usage bump failed for %s (swallowed): %s", skill_id, exc)

    def _bump_blocking() -> None:
        """Chemin sync (executor LangChain) : on programme le bump sur la loop
        qui porte le moteur DB et on BLOQUE le thread worker jusqu'au commit,
        borné par ``_BUMP_TIMEOUT_S``. Ça sérialise les invocations sync au
        lieu d'empiler des écritures concurrentes non attendues."""
        try:
            from app.services.learning.active_skills import bump_skill_usage
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not None:
                # Déjà sur un thread de loop (rare pour un tool sync) : bloquer
                # y gèlerait la loop — on programme et on garde la référence.
                task = running.create_task(bump_skill_usage(skill_id))
                task.add_done_callback(lambda t: t.exception())
            elif loop is not None and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(bump_skill_usage(skill_id), loop)
                fut.result(timeout=_BUMP_TIMEOUT_S)
            else:
                asyncio.run(bump_skill_usage(skill_id))
        except Exception as exc:  # noqa: BLE001 — jamais au prix de l'appel
            logger.debug("usage bump failed for %s (swallowed): %s", skill_id, exc)

    try:
        if getattr(tool, "coroutine", None) is not None:
            original_coro = tool.coroutine

            async def _traced_coro(*args: Any, **kwargs: Any) -> Any:
                await _bump_awaited()
                return await original_coro(*args, **kwargs)

            tool.coroutine = _traced_coro
        if getattr(tool, "func", None) is not None:
            original_func = tool.func

            def _traced_func(*args: Any, **kwargs: Any) -> Any:
                _bump_blocking()
                return original_func(*args, **kwargs)

            tool.func = _traced_func
    except Exception as exc:  # noqa: BLE001 — un tool non-wrappable reste utilisable
        logger.warning("usage bump wrap failed for %s: %s", skill_id, exc)
    return tool


def _core_tool_names() -> set[str]:
    """Noms du registre core — seam monkeypatchable pour les tests."""
    try:
        from app.skills.registry import get_skill_registry
        return get_skill_registry().all_tool_names()
    except Exception as exc:  # noqa: BLE001 — fail-open : pas de bascule
        logger.debug("learned_tools_runtime: registry lookup failed: %s", exc)
        return set()


async def _reconcile_graduated(rows: list[Any]) -> list[Any]:
    """Sprint 4d J4 — bascule en ``graduated`` les learned actifs dont le
    nom est désormais porté par un tool core, et les retire du binding.

    Best-effort : si l'UPDATE échoue, la row est quand même écartée du
    binding de CE chargement (l'unicité prime), et la bascule sera
    retentée au prochain chargement.
    """
    if not rows:
        return rows
    core = _core_tool_names()
    if not core:
        return rows
    survivors: list[Any] = []
    collided: list[Any] = []
    for skill in rows:
        (collided if skill.name in core else survivors).append(skill)
    if not collided:
        return rows
    try:
        from sqlalchemy import update

        from app.database import async_session
        from app.models.learned_skill import LearnedSkill, SkillStatus
        async with async_session() as db:
            await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id.in_([s.id for s in collided]))
                .values(status=SkillStatus.GRADUATED)
            )
            await db.commit()
        for s in collided:
            logger.info(
                "learned_tools_runtime: %s (%s) GRADUATED — un tool core "
                "porte désormais ce nom, le binding dynamique s'efface.",
                s.id, s.name,
            )
    except Exception as exc:  # noqa: BLE001 — l'unicité prime, on réessaiera
        logger.warning(
            "learned_tools_runtime: graduation flip failed (retry au "
            "prochain chargement): %s", exc,
        )
    return survivors


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
    ``tools`` unchanged when the feature flags are off (no learned tools).

    Sprint 4b V3 (v1.15.0) : les outils ``io`` (sandbox, egress réel)
    rejoignent la MÊME couture — chat (agent_node) et missions
    (_get_actor_llms) en héritent sans câblage supplémentaire.
    ``load_active_io_tools`` retourne ``[]`` quand
    ``LEARNED_PYTHON_TOOLS_IO_ENABLED`` est off : zéro changement de
    comportement tant que le flag n'est pas posé. Ordre : pure d'abord —
    en cas de collision de nom (déjà rejetée à la promotion), le pure
    in-process gagne sur l'io sandboxé.
    """
    from app.services.learning.learned_tools_runtime_io import load_active_io_tools

    learned = await load_active_python_tools(user_id)
    learned = learned + await load_active_io_tools(user_id)
    if not learned:
        return list(tools)
    have = {t.name for t in tools}
    out = list(tools)
    for t in learned:
        if t.name not in have:
            out.append(t)
            have.add(t.name)
    return out


async def merge_into_tool_map(tool_map: dict[str, Any], user_id: str) -> None:
    """Add the user's active python_tool skills to a dispatch ``tool_map``
    IN PLACE, without shadowing a builtin (``setdefault`` → registry wins).

    Used at DISPATCH time. python_tools aren't in the global skill registry
    (per-user, by design), so tool_node / dispatch_tool wouldn't find them at
    invoke without this. No-op when the feature flags are off.

    V3 (v1.15.0) : même couture pour les outils ``io`` — pure d'abord
    (cohérent avec ``append_learned_tools``), puis io, ``setdefault``
    partout.
    """
    from app.services.learning.learned_tools_runtime_io import load_active_io_tools

    for t in await load_active_python_tools(user_id):
        tool_map.setdefault(t.name, t)
    for t in await load_active_io_tools(user_id):
        tool_map.setdefault(t.name, t)
