# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_u_user_state_idempotence.py
# @brief      Sprint 3.7.3 J4 — structural regression : Sprint 3 User State
#             Vector. set_user_state is idempotent (same input → same merged
#             output), get round-trips it, and every DEFAULT_STATE key is
#             always present (the maintenance LLM updates one field at a time).
# @license    MIT
# =============================================================================
"""Canonical scenario U — user_state set/get idempotence + default merge."""
from __future__ import annotations


NAME = "U — user_state idempotence + default merge"
DESCRIPTION = (
    "set_user_state(partial) twice yields the same merged state ; get_user_"
    "state round-trips it ; the merged state always carries every "
    "DEFAULT_STATE key ; _merge_with_defaults is a fixed point."
)
TAGS = ["shallow"]


async def run() -> dict:
    from app.services.learning.user_state import (
        DEFAULT_STATE,
        _merge_with_defaults,
        get_user_state,
        set_user_state,
    )
    from bench.scenarios._base import from_checks, throwaway_user

    # Valid keys/values: mood is free-text, energy_budget is validated
    # against {high, normal, low}, current_focus is free-text.
    partial = {
        "mood": "concentré",
        "energy_budget": "high",
        "current_focus": "bench J4",
    }

    async with throwaway_user("bench_ustate") as uid:
        s1 = await set_user_state(uid, partial)
        s2 = await set_user_state(uid, partial)   # idempotent re-apply
        got = await get_user_state(uid)

        checks = {
            "set_is_idempotent": s1 == s2,
            "get_round_trips": got == s1,
            "partial_applied": (
                got.get("mood") == "concentré"
                and got.get("energy_budget") == "high"
                and got.get("current_focus") == "bench J4"
            ),
            "all_default_keys_present": set(DEFAULT_STATE).issubset(set(got)),
            "merge_is_fixed_point": _merge_with_defaults(s1) == s1,
            # The bounding contract: an out-of-vocabulary energy coerces to
            # the default rather than poisoning the state.
            "invalid_energy_coerced": (
                _merge_with_defaults({"energy_budget": "haute"})["energy_budget"]
                == "normal"
            ),
        }
        return from_checks(checks, state_keys=sorted(got.keys()))
