# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_k_hitl_timeout_capture.py
# @brief      Sprint 3.7.3 J3 — canonical scenario K : « timeout ≠ refus ».
#             Depuis #150 (2026-06-19) un timeout (l'utilisateur n'a ni validé
#             ni refusé) n'est PAS un refus délibéré → record_hitl_refusal
#             l'ignore (aucun signal, aucune capture), tandis qu'un VRAI refus
#             reste persisté ET capturé comme failure_case.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario K — HITL timeout ignored, genuine refusal captured.

Mis à jour le 2026-06-27 pour le comportement de #150. Avant, un timeout était
compté comme un refus et capturé ; il polluait le signal d'apprentissage (un
« non » de l'utilisateur attribué à tort). Désormais ``record_hitl_refusal``
retourne ``None`` pour ``reason="timeout"`` ; seul un refus délibéré
(``reason="user-provided"``) produit une ligne ``hitl_refusals`` + un
``failure_cases``.
"""
from __future__ import annotations


NAME = "K — HITL timeout ignored, genuine refusal captured"
DESCRIPTION = (
    "record_hitl_refusal(reason='timeout') returns None and persists nothing "
    "(timeout ≠ refus, #150) ; a genuine refusal (reason='user-provided') is "
    "persisted AND produces a failure_cases row."
)
TAGS = ["shallow"]


async def run() -> dict:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.failure_case import FailureCase
    from app.models.hitl_refusal import HitlRefusal
    from app.services.learning.failure_capture import SIGNAL_HITL_REFUSAL
    from app.services.learning.signals import record_hitl_refusal
    from bench.scenarios._base import from_checks, throwaway_user

    async with throwaway_user("bench_hitl_timeout") as uid:
        # 1. A timeout is NOT a deliberate refusal → ignored (no signal row).
        timeout_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id="bench-conv-k-timeout",
            tool_name="calendar_delete_event",
            args={"event_id": "evt_timeout"},
            action_description="Supprimer l'événement « Réunion budget »",
            decision="deny",
            reason="timeout",
            tier_llm="C",
        )

        # 2. A genuine user refusal IS persisted AND captured as a failure_case.
        denied_id = await record_hitl_refusal(
            user_id=uid,
            conversation_id="bench-conv-k-denied",
            tool_name="calendar_delete_event",
            args={"event_id": "evt_denied"},
            action_description="Supprimer l'événement « Réunion budget »",
            decision="deny",
            reason="user-provided",
            tier_llm="C",
        )

        async with async_session() as db:
            timeout_rows = (await db.execute(
                select(HitlRefusal).where(
                    HitlRefusal.user_id == uid,
                    HitlRefusal.reason == "timeout",
                )
            )).scalars().all()
            denied = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.id == denied_id)
            )).scalar_one_or_none() if denied_id is not None else None
            fcs = (await db.execute(
                select(FailureCase).where(
                    FailureCase.user_id == uid,
                    FailureCase.signal_table == SIGNAL_HITL_REFUSAL,
                )
            )).scalars().all()

        checks = {
            "timeout_not_recorded": timeout_id is None,
            "timeout_no_refusal_row": len(timeout_rows) == 0,
            "genuine_refusal_persisted": denied is not None,
            "genuine_refusal_reason": denied is not None and denied.reason == "user-provided",
            "genuine_refusal_captured": any(f.signal_id == denied_id for f in fcs),
        }
        return from_checks(checks, signal_id=denied_id)
