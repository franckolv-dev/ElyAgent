# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_annulation_affirmee_sans_outil_est_bloquee.py
# @brief      Le garde-fou anti-affirmation connaît « annulé », « restauré »,
#             « de nouveau nommé », « renommé » — et `undo_last_action` prouve.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le 05/09/2026, à « annule ce que tu viens de faire », Ely a répondu « Le
fichier est de nouveau nommé « brouillon test » » sans appeler aucun outil.
Le garde-fou n'a rien vu : ses motifs connaissaient « supprimé », « envoyé »,
« créé »… pas l'annulation ni le renommage. Et `undo_last_action`, qui rend
l'action réelle, ne figurait pas parmi les outils qui prouvent un effet.

Run with:  cd backend && python -m pytest tests/test_une_annulation_affirmee_sans_outil_est_bloquee.py -v
"""
from __future__ import annotations

import pytest

from app.services.completion_guard import DESTRUCTIVE_TOOLS, detect_unbacked_completion_claim


@pytest.mark.parametrize("texte", [
    "Le fichier est de nouveau nommé « brouillon test ».",
    "C'est annulé : le fichier a retrouvé son nom d'origine.",
    "J'ai annulé le renommage.",
    "L'action a été annulée.",
    "Le nom a été restauré.",
    "J'ai renommé le fichier en « brouillon test 2 ».",
    "Le fichier a été renommé.",
    "Le nom d'origine est rétabli.",
])
def test_une_annulation_ou_un_renommage_sans_outil_est_une_affirmation_creuse(texte):
    verdict = detect_unbacked_completion_claim(texte, [])
    assert verdict.is_hallucination is True, texte


def test_undo_last_action_prouve_l_annulation():
    assert "undo_last_action" in DESTRUCTIVE_TOOLS
    verdict = detect_unbacked_completion_claim(
        "Le fichier est de nouveau nommé « brouillon test ».", ["undo_last_action"],
    )
    assert verdict.is_hallucination is False


def test_drive_rename_file_prouve_le_renommage():
    verdict = detect_unbacked_completion_claim(
        "J'ai renommé le fichier en « brouillon test 2 ».", ["drive_rename_file"],
    )
    assert verdict.is_hallucination is False


@pytest.mark.parametrize("texte", [
    "Veux-tu que j'annule le renommage ?",
    "Je peux renommer le fichier si tu veux.",
    "Tu as annulé la réunion de jeudi, c'est noté.",
])
def test_une_question_ou_un_futur_ne_sont_pas_des_affirmations(texte):
    verdict = detect_unbacked_completion_claim(texte, [])
    assert verdict.is_hallucination is False, texte
