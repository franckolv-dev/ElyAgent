# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_dedicated_tool_nudge.py
# @brief      C4-3 — nudge « outil dédié d'abord » : le modèle doit préférer
#             un outil dédié (y compris appris) à un script orchestrate.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""C4-3 — pins du nudge anti-« marteau familier ».

Épisode vécu (19/07/2026) : `levenshtein_distance` fraîchement promu et
bindé… mais le modèle a préféré écrire un script `orchestrate` — il a
fallu NOMMER l'outil pour qu'il l'utilise. Deux contre-mesures pinnées :

  1. Règle prompt « outil dédié d'abord » (prompts.py, à côté des règles
     find_tool) — couvre aussi les outils appris du bloc <learned_skills>.
  2. Contre-indication dans le docstring d'orchestrate (le modèle la lit
     au moment où il choisit l'outil).

Et le câblage C4-3 pertinence : memory_snapshot passe la requête du tour
à la sélection des skills injectés.

Run with:  cd backend && python -m pytest tests/test_dedicated_tool_nudge.py -v
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def test_prompt_has_dedicated_tool_first_rule():
    src = (_REPO / "app/agent/prompts.py").read_text(encoding="utf-8")
    assert "Outil dédié d'abord" in src, (
        "La règle « outil dédié d'abord » doit exister dans les règles de "
        "base — sans elle le modèle retombe sur orchestrate (son marteau "
        "familier) même quand un outil appris couvre exactement la demande."
    )
    assert "y compris tes outils appris" in src, (
        "La règle doit citer explicitement les outils APPRIS — c'est le "
        "cas vécu (levenshtein_distance ignoré au profit d'orchestrate)."
    )


def test_memory_snapshot_passes_query_to_skill_selection():
    src = (_REPO / "app/agent/builders/memory_snapshot.py").read_text(encoding="utf-8")
    assert "query=user_query" in src, (
        "build_memory_snapshot doit transmettre la requête du tour à "
        "get_active_skills_for_user — sans elle, pas de tri par pertinence "
        "(C4-3.2), retour au top-20 use_count aveugle."
    )
