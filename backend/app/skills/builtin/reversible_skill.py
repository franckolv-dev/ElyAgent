# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/reversible_skill.py
# @brief      Skill d'annulation — expose les outils du Reversible Journal.
# @license    MIT
# =============================================================================
"""Skill « annulation » — surfaces model-facing du Reversible Action Journal."""
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.reversible_tool import (
    list_revertible_actions,
    revert_action,
    undo_last_action,
)

get_skill_registry().register(Skill(
    name="reversible_actions",
    display_name="Annulation d'actions",
    description=(
        "Annule une action mutante précédente (« annule ce que tu viens de "
        "faire »), ex. ressortir de la corbeille un fichier Drive supprimé. "
        "Liste les actions annulables et exécute la compensation enregistrée."
    ),
    icon="↩️",
    scopes=[],
    domains=[Domain.SYSTEM],
    tools=[
        list_revertible_actions,
        revert_action,
        undo_last_action,
    ],
))
