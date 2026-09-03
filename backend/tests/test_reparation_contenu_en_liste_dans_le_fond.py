# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_contenu_en_liste_dans_le_fond.py
# @brief      Les chemins de fond lisent un `content` rendu en LISTE de blocs
#             sans planter.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Production, nuit du 02 au 03/09 :

    diagnostician: LLM failed for outcome=383 : 'list' object has no attribute 'replace'

Le tier COMPLEX résout un modèle sur l'API Responses (gpt-5.6), dont le
``content`` arrive en LISTE de blocs. ``background_llm`` le sait et aplatit ;
six chemins de fond (diagnostiqueur, création et itération de compétence,
évaluation, générateur d'outil, état utilisateur) appellent le modèle en
direct et passent la liste au dé-anonymiseur, qui fait ``.replace``.

Le diagnostiqueur est testé de bout en bout ; les cinq autres reçoivent le
même correctif au même endroit.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _LLMEnBlocs:
    model = "gpt-5.6-test"

    async def ainvoke(self, _msgs, config=None):
        return SimpleNamespace(
            content=[
                {"type": "reasoning", "summary": []},
                {"type": "text", "text": "CATEGORIE: tool_error\nCONFIANCE: 0.9\n"},
                {"type": "text", "text": "HYPOTHESE: le jeton a expiré"},
            ],
            usage_metadata={"input_tokens": 1, "output_tokens": 1},
        )


@pytest.mark.asyncio
async def test_le_diagnostiqueur_rend_du_texte_quand_le_modele_rend_des_blocs(monkeypatch):
    import app.services.llm_provider as llm_mod
    from app.services.learning.diagnostician import _call_diagnostician_llm

    monkeypatch.setattr(llm_mod, "get_llm_for_tier", lambda tier: _LLMEnBlocs())

    raw, model = await _call_diagnostician_llm("diagnostique ceci")

    assert isinstance(raw, str)
    assert "HYPOTHESE: le jeton a expiré" in raw
    assert "reasoning" not in raw
    assert model == "gpt-5.6-test"


def test_les_six_chemins_de_fond_aplatissent_le_contenu():
    """Les cinq autres sites ont des signatures trop lourdes pour un test de
    bout en bout ; on vérifie qu'ils n'appliquent plus le motif fautif.
    Ce test rougit si l'un d'eux revient à ``getattr(response, "content")``
    passé tel quel au parseur."""
    import inspect

    from app.services.learning import (
        diagnostician, skill_creator, skill_eval, skill_iteration,
        tool_generator, user_state,
    )

    for mod in (diagnostician, skill_creator, skill_eval, skill_iteration,
                tool_generator, user_state):
        source = inspect.getsource(mod)
        assert 'raw = getattr(response, "content", "") or ""' not in source, mod.__name__
        assert "content_to_text(" in source, mod.__name__
