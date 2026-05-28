# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/helpers/memory_formatting.py
# @brief      Sprint refactor nodes.py Phase 1.5 — memory block formatter
#             (Hermes Chantier 2, frozen snapshot section).
# @license    Elastic License 2.0
# @version    1.7.1
# =============================================================================
"""Memory block formatter — Hermes Chantier 2.

Single function ``_format_memory_block`` that turns the per-user memory
gather (user_profile, preferences, constraints, memories, past_interactions)
into the byte-stable string spliced into the cacheable segment of the
system prompt.
"""
from __future__ import annotations


def _format_memory_block(
    user_profile: str,
    preferences: list,
    constraints: list,
    memories: list,
    past_interactions: list,
) -> str:
    """Build the user-memory section of the system prompt as a single string.

    This is the **cacheable, frozen-for-the-session** part of the prompt.
    The output is byte-stable for given inputs, so wrapping the inputs
    themselves with frozen_memory + this formatter gives an immutable
    block that the prompt cache prefix can latch on.

    Order is intentional: user_profile FIRST (most important to anchor
    the model on the user's identity), preferences as RULES, constraints
    as REFUSAL HISTORY, memories as CONTEXT, past_interactions LAST
    (least important, longest tail).
    """
    parts: list[str] = []
    if user_profile:
        parts.append(f"\n\n🧠 {user_profile}\n")
    if preferences:
        parts.append(
            "\n\n👤 RÈGLES DE COMMUNICATION PERSONNALISÉES — OBLIGATOIRES :\n"
            "⚠️ Ces règles ont la même priorité que les règles absolues ci-dessus.\n"
            "Elles s'appliquent à CHAQUE réponse, sans exception, même si tu penses\n"
            "qu'une réponse plus longue serait plus utile. Respecte-les strictement.\n"
        )
        parts.append("\n".join(f"- {p}" for p in preferences))
    if constraints:
        parts.append("\n\n🛡️ CONTRAINTES DE SÉCURITÉ PERMANENTES (apprises de tes refus) :\n")
        parts.append("\n".join(f"- {c}" for c in constraints))
    if memories:
        parts.append("\n\n💾 CONTEXTE MÉMORISÉ :\n")
        parts.append("\n".join(f"- {m}" for m in memories))
    if past_interactions:
        parts.append("\n\n🔁 INTERACTIONS PASSÉES PERTINENTES :\n")
        for p in past_interactions:
            parts.append(
                f"- Q: {p.get('user_message', '')[:120]} "
                f"→ R: {p.get('assistant_message', '')[:120]}\n"
            )
    return "".join(parts)
