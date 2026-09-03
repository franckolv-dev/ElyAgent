# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_selecteur_trie_a_froid.py
# @brief      Le sélecteur d'outils appelle son modèle à température zéro et
#             avec une sortie bornée : un tri de noms ne se tire pas au sort.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Banc du 03/09/2026 sur Ministral 3B, quatre demandes, deux passes :

    température 0,7 (défaut de `_make_llm_for_instance`) : 3/4 puis 3/4,
                                                           mais PAS les mêmes
    température 0                                        : 3/4 puis 3/4,
                                                           identiques

À 0,7 le sélecteur rendait `pdf_to_docx` une fois sur deux pour « convertir
un PDF en Word ». Choisir des noms dans une liste n'est pas une tâche
créative : la température est à zéro, et la sortie (douze noms au plus) est
bornée pour qu'un modèle qui déraille s'arrête en moins d'une seconde.
"""
from __future__ import annotations


def test_le_selecteur_demande_son_modele_a_temperature_zero(monkeypatch):
    from app.agent import tool_selector as ts
    from app.services import llm_provider as lp

    monkeypatch.setenv("TOOL_SELECTOR_MODEL", "ministral")
    monkeypatch.setattr(lp, "_instance_cache", {
        "inst-1": {"provider": "lm_studio", "model": "mistralai/ministral-3-3b", "api_key": None},
    })
    recus: list[dict] = []

    def _fabrique(instance_id, max_tokens=4096, temperature=0.7):
        recus.append({"id": instance_id, "max_tokens": max_tokens, "temperature": temperature})
        return object()

    monkeypatch.setattr(lp, "_make_llm_for_instance", _fabrique)

    assert ts._selector_llm() is not None
    assert recus == [{"id": "inst-1", "max_tokens": 256, "temperature": 0.0}]
