# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_session_todo_tolere_les_dicts.py
# @brief      Le carnet d'étapes accepte une étape écrite comme un objet.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Production, mission du 03/09 à 05:49 :

    Tool session_todo failed: 1 validation error for session_todo
    taches.0  Input should be a valid string [input_value={'en_cours': 1, ...}]

Le modèle a écrit chaque étape comme un objet (``{"id": 5, "texte": …}``)
plutôt qu'une chaîne. Le schéma refusait, l'outil rendait une erreur de
validation au lieu du plan, et le carnet de la mission restait vide.

Refuser un plan lisible parce qu'il est structuré coûte un tour de modèle
pour rien : on lit le texte de l'objet (``texte``, ``text``, ``title``,
``tache``, ``task``, ``label``, ``name``), et à défaut sa forme JSON.
"""
from __future__ import annotations

import pytest

from app.agent.tool_context import CURRENT_CONVERSATION_ID


@pytest.fixture
def _conv():
    token = CURRENT_CONVERSATION_ID.set("conv-todo-dicts")
    try:
        yield "conv-todo-dicts"
    finally:
        CURRENT_CONVERSATION_ID.reset(token)


def test_le_normaliseur_lit_le_texte_d_un_objet():
    from app.agent.tools.todo_tool import _normaliser

    assert _normaliser([
        {"id": 1, "texte": "Lister les mails"},
        {"title": "Trier"},
        "Archiver",
        {"id": 4},
        {"texte": ""},          # un texte vide est une étape vide, pas un JSON
    ]) == ("Lister les mails", "Trier", "Archiver", '{"id": 4}')


@pytest.mark.asyncio
async def test_l_outil_accepte_des_etapes_structurees(_conv):
    from app.agent.tools.todo_tool import MARQUEUR_A_FAIRE, session_todo

    rendu = await session_todo.ainvoke({
        "taches": [{"id": 1, "texte": "Lister les mails"}, "Trier"],
    })

    assert "erreur" not in rendu.lower()
    assert f"1. {MARQUEUR_A_FAIRE} Lister les mails" in rendu
    assert f"2. {MARQUEUR_A_FAIRE} Trier" in rendu
