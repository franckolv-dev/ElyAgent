# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/builders/memory_snapshot.py
# @brief      Sprint refactor nodes.py Phase 4.1 — pure builder for the
#             per-user memory snapshot spliced into the system prompt.
# @license    Elastic License 2.0
# @version    1.7.1
# =============================================================================
"""Memory snapshot builder — Hermes Chantier 2.

Pure async function that gathers the per-user memory pieces (preferences,
constraints, episodic memories, past interactions, user_profile, user_state
vector from Sprint 3) and emits the byte-stable string spliced into the
cacheable segment of the system prompt.

Why this lives outside agent_node
---------------------------------
The original ``_build_memory_snapshot`` was a closure inside
``create_agent_node().agent_node`` that captured ``messages``,
``user_id``, ``user_query``, ``memory``, ``_use_compact``, and mutated
``_compact_pieces`` via ``nonlocal``. The Phase 4.1 refactor pulls the
business logic out into this pure function (no closure, no side-effect),
returning a tuple ``(snapshot_text, compact_pieces_or_none)`` that the
caller propagates as it sees fit.

The thin closure that remains in agent_node only exists to satisfy the
``frozen_memory.get_or_build(builder: Callable[[], Awaitable[str]])``
signature — that's the only place the ``nonlocal`` survives.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.agent.helpers.memory_formatting import _format_memory_block


async def _no_interactions() -> list[dict]:
    """Cheap placeholder for ``get_relevant_interactions`` on the very
    first turn — there's nothing to find yet and Qdrant + FTS + embeddings
    cost ~100-200 ms. Skipping is worth the slight loss of context."""
    return []


async def build_memory_snapshot(
    *,
    messages: list,
    user_id: str,
    user_query: str,
    memory,
    use_compact: bool,
) -> tuple[str, dict[str, Any] | None]:
    """Build the frozen-snapshot section of the system prompt.

    Behaviour identical to the original closure :

    1. Skip ``get_relevant_interactions`` on the first turn (cheap stub).
    2. Gather the 5-tuple (constraints, memories, past_interactions,
       preferences, user_profile) in parallel via ``asyncio.gather``.
    3. If ``use_compact`` is True, return the compact pieces alongside
       the snapshot string so the compact builder downstream doesn't
       have to re-query Qdrant.
    4. Format the user-memory block via ``_format_memory_block``.
    5. Prepend the Sprint 3 ``<user_state>`` block when the user has a
       non-empty UserState (best-effort — failures swallowed).

    Returns
    -------
    snapshot_text : str
        The full snapshot string (user_state block + memory block).
    compact_pieces : dict | None
        Structured pieces (user_profile / memories / constraints) when
        ``use_compact`` is True, otherwise None.
    """
    # Skip past-interactions retrieval on the very first turn — saves
    # 100-200 ms on cold starts.
    _history_msgs_count = sum(
        1 for m in messages if getattr(m, "type", None) in ("human", "ai")
    )
    _needs_interactions = _history_msgs_count > 1

    # Lazy import to avoid heavy module-load at agent_node creation.
    from app.services.memory_service import get_user_context

    _past_interactions_task = (
        memory.get_relevant_interactions(user_query, user_id, limit=3)
        if _needs_interactions
        else _no_interactions()
    )
    constraints, memories_, past_interactions, preferences, user_profile = (
        await asyncio.gather(
            memory.get_relevant_constraints(user_query, user_id),
            memory.get_relevant_memories(user_query, user_id),
            _past_interactions_task,
            memory.get_user_preferences(user_id),
            get_user_context(user_id),
        )
    )

    compact_pieces: dict[str, Any] | None = None
    if use_compact:
        # Compact path needs structured pieces, not a single block.
        compact_pieces = {
            "user_profile": user_profile or "",
            "memories": memories_,
            "constraints": constraints,
        }

    _mem_block = _format_memory_block(
        user_profile or "",
        preferences or [],
        constraints or [],
        memories_ or [],
        past_interactions or [],
    )

    # Sprint 3 Jalon 2 — prepend the User State Vector block.
    # Lives inside the frozen_memory snapshot so it gets the same cache
    # treatment as the rest of the per-user memory. Empty state collapses
    # to empty string (handled in formatter), so we don't pollute the
    # prompt for first-time users.
    try:
        from app.services.learning.user_state import (
            format_user_state_block,
            get_user_state,
        )
        _us = await get_user_state(user_id)
        _us_block = format_user_state_block(_us)
    except Exception:
        _us_block = ""

    # Sprint 4b Phase 4.b — inject the active LearnedSkills block (tier 1
    # of the progressive disclosure : name + description only, the
    # agent calls skill_view(name) to load the full body on demand).
    # Same frozen_memory cache treatment as the rest, empty when the
    # user has no active playbook → no prompt pollution for first-time
    # or unpromoted users. Best-effort — DB outage returns "".
    try:
        from app.services.learning.active_skills import (
            format_active_skills_block,
            get_active_skills_for_user,
        )
        _active_skills = await get_active_skills_for_user(user_id)
        _skills_block = format_active_skills_block(_active_skills)
    except Exception:
        _skills_block = ""

    snapshot_text = _us_block + _skills_block + _mem_block
    return snapshot_text, compact_pieces


async def refetch_compact_pieces(
    *,
    user_id: str,
    user_query: str,
    memory,
) -> dict[str, Any]:
    """Fallback re-fetch for the compact path when ``frozen_memory`` returns
    a cached snapshot (so ``build_memory_snapshot`` was NOT called this
    turn and compact_pieces is empty).

    Synchronously re-runs the minimal trio (user_profile / memories /
    constraints) — Past interactions and preferences aren't needed for
    the compact prompt.

    Rare path: only triggered on (frozen_memory cache hit) + (compact
    mode active) simultaneously.
    """
    from app.services.memory_service import get_user_context

    constraints_c, memories_c, _, _, user_profile_c = await asyncio.gather(
        memory.get_relevant_constraints(user_query, user_id),
        memory.get_relevant_memories(user_query, user_id),
        _no_interactions(),
        memory.get_user_preferences(user_id),
        get_user_context(user_id),
    )
    return {
        "user_profile": user_profile_c or "",
        "memories": memories_c or [],
        "constraints": constraints_c or [],
    }
