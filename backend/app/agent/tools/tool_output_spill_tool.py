# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/tool_output_spill_tool.py
# @brief      Outil de pagination des sorties d'outil débordées vers fichier.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Relire par tranches une sortie d'outil trop grande pour le contexte.

⚠️ CE QUE ÇA CORRIGE (02/09/2026) : sans cet outil, une sortie volumineuse
était tronquée et sa suite définitivement hors d'atteinte — le modèle
relançait le même outil et repayait la même troncature. Depuis
``services/tool_output_spill``, la sortie entière est conservée dans un
fichier et remplacée par un bloc portant un ``spill_id`` ; c'est cet outil
qui rend la suite.

Le propriétaire du débordement n'est PAS un argument : il vient de la
ContextVar posée par la passerelle (``tool_output_spill.owner_scope``). Un
``spill_id`` volé chez un autre utilisateur ne résout donc aucun fichier.

⚠️ La tranche demandée est RAMENÉE sous le seuil de débordement
(``tool_output_spill.max_slice_chars``). Le 02/09/2026, le maximum annoncé
(20 000) dépassait ce seuil (12 000) : la réponse de cet outil redébordait et
rendait un nouvel identifiant — le modèle paginait sans jamais finir.

POURQUOI LA TRANCHE EST ÉCRÊTÉE (02/09/2026)
---------------------------------------------
La tranche servie doit rester assez petite pour que la réponse de cet outil ne
déborde pas À SON TOUR : sinon elle rendrait un nouveau bloc « sortie
volumineuse », avec un nouvel identifiant pointant sur une tranche de
l'ancienne, et un modèle qui suit le maximum documenté ne s'arrêterait jamais.
La borne est donc dérivée du seuil de débordement, évaluée à l'appel puisque
ce seuil est réglable. Ce raisonnement vit ici et non dans la description de
l'outil : celle-ci est payée à chaque tour, sur chaque surface.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.services.tool_output_spill import read_slice
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


@register(
    domain=Domain.UNIVERSAL,
    skill_name="tool_output_spill",
    skill_display_name="Sorties volumineuses",
    skill_description=(
        "Relit par tranches une sortie d'outil trop grande pour le contexte, "
        "conservée en entier dans un fichier de travail."
    ),
    skill_icon="📜",
)
@tool
def tool_output_read(spill_id: str, offset: int = 0, length: int = 4000) -> str:
    """Read the next slice of a large tool output kept in a work file.

    Use this ONLY when a previous tool result was replaced by a
    "sortie volumineuse" block: that block gives you the ``spill_id``.
    Walk the output by advancing ``offset`` until you have what you need.
    Never re-run the original tool to get the rest — the data is already
    stored here, and re-running would return the same truncated view.

    Args:
        spill_id: Identifier printed in the "sortie volumineuse" block.
        offset: First character to read (0 = start of the output).
        length: Characters to read (default 4000, larger values are clamped).
    """
    try:
        return read_slice(spill_id, offset, length)
    except PermissionError as exc:
        return str(exc)
    except FileNotFoundError as exc:
        return str(exc)
    except OSError as exc:
        logger.warning("tool_output_read a échoué (%s)", exc)
        return f"Lecture du débordement impossible : {exc}"
