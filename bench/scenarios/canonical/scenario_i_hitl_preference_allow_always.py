# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_i_hitl_preference_allow_always.py
# @brief      Sprint 3.7.3 J3 — canonical scenario I : per-user HITL preference
#             resolver. "Toujours autoriser" disables the prompt for a normal
#             tool ; depuis #150 (2026-06-19) un outil DANGEREUX est ON par
#             défaut mais la préférence est honorée → il PEUT être désactivé.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario I — HITL preference allow-always + dangerous-tool default.

Mis à jour le 2026-06-27 pour le comportement de #150 : ``LOCKED_HITL_TOOLS``
n'est plus un verrou dur. Un outil dangereux reste « confirmation ON » PAR
DÉFAUT (aucune préférence → True), mais ``user_requires_hitl`` honore désormais
une préférence ``requires_confirmation=False`` même pour lui (« Autoriser
définitivement » devient opérant). L'ancien check « ne peut jamais être
déverrouillé » assertait le comportement d'avant #150.
"""
from __future__ import annotations


NAME = "I — HITL preference allow-always + dangerous-tool default"
DESCRIPTION = (
    "set_user_preference(requires_confirmation=False) disables HITL for a "
    "normal tool. A LOCKED_HITL_TOOLS (dangerous) tool is HITL-ON by default "
    "but, depuis #150, the preference is honored → it CAN be disabled."
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
    locked_tool = "drive_delete_file"        # in LOCKED_HITL_TOOLS (dangerous)

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

        # 4. A DANGEROUS tool is HITL-ON by default, but since #150 the
        #    preference is honored even for it → it CAN be disabled (the user
        #    takes the risk via the red "DANGEREUX" toggle / "Autoriser
        #    définitivement"). This used to return True in hard.
        locked_default = await user_requires_hitl(uid, locked_tool)
        await set_user_preference(uid, locked_tool, requires_confirmation=False)
        locked_after_disable = await user_requires_hitl(uid, locked_tool)

        checks = {
            "default_requires_hitl": default_required is True,
            "set_preference_ok": set_ok is True,
            "allow_always_disables_hitl": after_allow is False,
            "reenable_restores_hitl": after_reenable is True,
            "locked_tool_in_set": locked_tool in LOCKED_HITL_TOOLS,
            "dangerous_tool_hitl_on_by_default": locked_default is True,
            "dangerous_tool_can_be_disabled": locked_after_disable is False,
        }
        return from_checks(checks, user_id=uid)
