# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/canonical/scenario_l_completion_guard_detection.py
# @brief      Sprint 3.7.3 J3 — canonical scenario L : completion_guard's pure
#             detection logic. Flags an unbacked completion claim, clears a
#             tool-backed one, and (regression) does NOT flag a NEGATED claim
#             nor a memory-recall recitation.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Canonical scenario L — detect_unbacked_completion_claim pure-function."""
from __future__ import annotations


NAME = "L — completion_guard detection (pure)"
DESCRIPTION = (
    "detect_unbacked_completion_claim: unbacked claim → hallucination ; "
    "destructive-tool-backed claim → clean ; negated claim (v1.11.1 fix) → "
    "clean ; memory-recall recitation (2026-05-23 bypass) → clean."
)
TAGS = ["shallow"]


async def run() -> dict:
    from app.services.completion_guard import detect_unbacked_completion_claim
    from bench.scenarios._base import from_checks

    claim = "C'est fait, j'ai supprimé les 12 mails de la corbeille."

    # 1. Claim with NO tool invoked → hallucination.
    v_unbacked = detect_unbacked_completion_claim(claim, [])

    # 2. Same claim but a destructive tool actually ran → backed → clean.
    v_backed = detect_unbacked_completion_claim(claim, ["gmail_trash_emails"])

    # 3. Negated claim (v1.11.1 negation fix) → not a completion → clean.
    v_negated = detect_unbacked_completion_claim(
        "Non, aucun mail n'a été supprimé : l'opération a été annulée.", []
    )

    # 4. Memory-recall recitation (the user asked what ELY remembers) →
    #    past-tense verbs are honest recall, not a tool claim → bypass.
    v_recall = detect_unbacked_completion_claim(
        "Voici ce que j'ai noté sur ton compte : tu préfères le train.",
        [],
        user_message="qu'as-tu enregistré sur mon compte ?",
    )

    checks = {
        "unbacked_claim_flagged": v_unbacked.is_hallucination is True,
        "unbacked_has_patterns": len(v_unbacked.matched_patterns) >= 1,
        "tool_backed_claim_clean": v_backed.is_hallucination is False,
        "negated_claim_not_flagged": v_negated.is_hallucination is False,
        "memory_recall_bypassed": v_recall.is_hallucination is False,
    }
    return from_checks(
        checks,
        unbacked_reason=v_unbacked.reason,
        negated_reason=v_negated.reason,
        recall_reason=v_recall.reason,
    )
