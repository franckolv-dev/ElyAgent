# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_rag_lit_l_infra_memoire.py
# @brief      La base de connaissances lit le client Qdrant et l'encodeur
#             là où ils vivent : dans l'infra mémoire, pas sur le manager.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Au démarrage, la production journalise depuis le Sprint 2.5 de la mémoire :

    Failed to init knowledge collection: 'MemoryManager' object has no attribute 'client'

``RAGService`` délègue ``client``, ``encoder`` et ``_embed`` à
``get_memory_manager()``. Or le Sprint 2.5 a déplacé ces trois choses dans
``MemoryInfra`` (``memory/_infra.py``), que le manager porte sous ``_infra``.
Résultat : ``knowledge_search``, ``knowledge_list`` et ``smart_knowledge_query``
lèvent ``AttributeError`` à la première requête, et la collection n'est jamais
créée. Personne ne l'a vu : l'audit du 02/09 compte UN appel à la base de
connaissances sur cinq mois.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FauxInfra:
    def __init__(self) -> None:
        self.client = object()
        self.encoder = object()
        self.textes: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.textes.append(text)
        return [0.1, 0.2]


def _service_sur(infra: _FauxInfra, monkeypatch):
    from app.services import rag_service as mod

    manager = SimpleNamespace(_infra=infra)
    monkeypatch.setattr(mod, "get_memory_manager", lambda: manager)
    return mod.RAGService()


def test_le_client_et_l_encodeur_viennent_de_l_infra(monkeypatch):
    infra = _FauxInfra()
    svc = _service_sur(infra, monkeypatch)

    assert svc.client is infra.client
    assert svc.encoder is infra.encoder


@pytest.mark.asyncio
async def test_l_embedding_passe_par_le_cache_de_l_infra(monkeypatch):
    infra = _FauxInfra()
    svc = _service_sur(infra, monkeypatch)

    assert await svc._embed("bonjour") == [0.1, 0.2]
    assert infra.textes == ["bonjour"]


def test_le_vrai_manager_expose_bien_ce_que_le_rag_lui_demande():
    """Le double ci-dessus reproduit la surface réelle : si le manager
    déménage encore ses attributs, ce test-ci rougit, pas seulement le faux."""
    from app.services.memory_manager import MemoryManager
    from app.services.memory._infra import MemoryInfra

    manager = MemoryManager()
    assert isinstance(manager._infra, MemoryInfra)
    for attr in ("client", "encoder", "embed"):
        assert hasattr(MemoryInfra, attr), attr
