# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_generation_falls_back_to_cloud.py
# @brief      Le modèle local tente d'abord ; s'il n'y arrive pas, le repli
#             cloud du niveau S prend le relais.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La seconde moitié de la règle de Franck (29/07/2026).

    « Idéalement, le modèle local crée l'outil, Ely le teste et s'il est
      fonctionnel on s'arrête ; s'il ne l'est pas, là on fait appel au fallback
      du tier S qui est kimi-k3. »

Ce qui existait déjà
---------------------
La boucle ``generate → validate → iterate`` de ``tool_creator`` : jusqu'à trois
tentatives, chacune renvoyant au générateur l'échec exact de validation. C'est
le « Ely le teste » de la règle, et il fonctionne.

Ce qui manquait
----------------
``generate_tool_source`` appelle ``get_tier_s_llm()`` **sans** ``force_fallback``.
Les trois itérations se font donc toutes sur le MÊME modèle local, et quand il
n'y arrive pas, on abandonne — alors que ``kimi-k3`` est configuré juste
derrière lui dans la chaîne du niveau S, et n'est jamais sollicité.

Le principe retenu
-------------------
Le local garde ses tentatives — il est gratuit, et c'est lui qui doit faire le
travail ordinaire. Le cloud n'est appelé **qu'après** son échec complet, une
seule fois : si trois passes locales n'ont pas produit un outil valide, une
quatrième ne le fera pas davantage.

Run with:  cd backend && python -m pytest tests/test_tool_generation_falls_back_to_cloud.py -v
"""
from __future__ import annotations

import inspect

import pytest


def test_the_generator_can_be_asked_for_the_fallback():
    """Sans ce paramètre, la chaîne du niveau S s'arrête à son premier maillon
    et ``kimi-k3`` reste décoratif."""
    from app.services.learning.tool_generator import generate_tool_source

    assert "force_fallback" in inspect.signature(generate_tool_source).parameters


@pytest.mark.asyncio
async def test_the_request_reaches_the_tier_s_chain(monkeypatch):
    """⚠️ Le paramètre doit descendre jusqu'à ``get_tier_s_llm`` : l'accepter
    sans le transmettre donnerait un test vert et un repli mort."""
    vus: list[bool] = []

    async def _spy(*, force_fallback: bool = False):
        vus.append(force_fallback)
        return None, "none"          # coupe court : on ne teste que le passage

    # ⚠️ Patcher `tier_s.get_tier_s_llm` ne suffit PAS : `tool_generator`
    # importe la fonction au niveau du module, donc il garde sa propre
    # référence. C'est là qu'il faut la remplacer — sinon le test vert ne
    # prouve rien du tout.
    monkeypatch.setattr(
        "app.services.learning.tool_generator.get_tier_s_llm", _spy,
    )
    from app.services.learning.tool_generator import generate_tool_source

    await generate_tool_source(task_description="x", user_id="u1", force_fallback=True)
    assert vus == [True]


@pytest.mark.asyncio
async def test_the_local_model_keeps_its_attempts_before_the_cloud(monkeypatch):
    """Le local est gratuit et doit faire le travail ordinaire : le cloud ne
    doit pas être sollicité tant qu'il n'a pas épuisé ses tentatives."""
    passes: list[bool] = []

    async def _gen(**kwargs):
        passes.append(bool(kwargs.get("force_fallback")))
        return None, {"status": "llm_error", "error": "boom"}

    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_tool_source", _gen,
    )
    from app.services.learning.tool_creator import generate_and_persist_tool

    await generate_and_persist_tool(
        task_description="envoyer un SMS", user_id="u1", max_iterations=3,
    )

    assert passes[:3] == [False, False, False], f"passes = {passes}"


@pytest.mark.asyncio
async def test_the_cloud_gets_exactly_one_attempt_after_the_local_fails(monkeypatch):
    """Une seule reprise cloud : si trois passes locales n'ont pas produit un
    outil valide, une quatrième locale ne le ferait pas davantage — mais payer
    plusieurs passes cloud non plus."""
    passes: list[bool] = []

    async def _gen(**kwargs):
        passes.append(bool(kwargs.get("force_fallback")))
        return None, {"status": "llm_error", "error": "boom"}

    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_tool_source", _gen,
    )
    from app.services.learning.tool_creator import generate_and_persist_tool

    await generate_and_persist_tool(
        task_description="envoyer un SMS", user_id="u1", max_iterations=3,
    )

    assert passes.count(True) == 1, f"passes = {passes}"


@pytest.mark.asyncio
async def test_a_local_success_never_pays_for_the_cloud(monkeypatch):
    """Le cas nominal doit rester gratuit. Un outil validé du premier coup ne
    doit déclencher aucun appel au repli."""
    passes: list[bool] = []

    async def _gen(**kwargs):
        passes.append(bool(kwargs.get("force_fallback")))
        # Un statut terminal qui arrête la boucle sans persister.
        return None, {"status": "no_provider", "error": "stop"}

    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_tool_source", _gen,
    )
    from app.services.learning.tool_creator import generate_and_persist_tool

    await generate_and_persist_tool(
        task_description="x", user_id="u1", max_iterations=3,
    )

    assert True not in passes, (
        f"le repli cloud a été appelé alors que la boucle s'arrêtait : {passes}"
    )
