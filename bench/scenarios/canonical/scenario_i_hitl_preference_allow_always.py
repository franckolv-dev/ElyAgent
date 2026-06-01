# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_i_hitl_preference_allow_always.py
# @brief      Sprint 3.7.3 J3 — canonical scenario I : per-user HITL
#             preference resolver. "Toujours autoriser" disables the prompt
#             for a normal tool, but LOCKED_HITL_TOOLS can never be unlocked.
# @license    Elastic License 2.0
# =============================================================================
"""Canonical scenario I — HITL preference allow-always + locked-tool safety."""
from __future__ import annotations


NAME = "I — HITL preference allow-always + locked safety"
DESCRIPTION = (
    "set_user_preference(requires_confirmation=False) disables HITL for a "
    "normal tool, but a LOCKED_HITL_TOOLS entry stays forced-on even after "
    "an allow-always write (server-side belt-and-suspenders)."
)
TAGS = ["shallow"]


async def run() -> dict:
    from app.services.hitl_preferences import (
        LOCKED_HITL_TOOLS,
        set_user_preference,
        user_requires_hitl,
    )
    from bench.scenarios._base import from_checks, throwaway_user

    normal_tool = "gmail_list_emails"        # toggleable
    locked_tool = "drive_delete_file"        # in LOCKED_HITL_TOOLS

    async with throwaway_user("bench_hitl_pref") as uid:
        # 1. Secure default: no preference row → HITL required.
        default_required = await user_requires_hitl(uid, normal_tool)

        # 2. "Toujours autoriser" on a normal tool → HITL disabled.
        set_ok = await set_user_preference(
            uid, normal_tool, requires_confirmation=False
        )
        after_allow = await user_requires_hitl(uid, normal_tool)

        # 3. Re-enabling restores HITL (the slider works both ways).
        await set_user_preference(uid, normal_tool, requires_confirmation=True)
        after_reenable = await user_requires_hitl(uid, normal_tool)

        # 4. A LOCKED tool accepts the write but stays forced-on.
        await set_user_preference(uid, locked_tool, requires_confirmation=False)
        locked_still_required = await user_requires_hitl(uid, locked_tool)

        checks = {
            "default_requires_hitl": default_required is True,
            "set_preference_ok": set_ok is True,
            "allow_always_disables_hitl": after_allow is False,
            "reenable_restores_hitl": after_reenable is True,
            "locked_tool_in_set": locked_tool in LOCKED_HITL_TOOLS,
            "locked_tool_cannot_be_unlocked": locked_still_required is True,
        }
        return from_checks(checks, user_id=uid)
