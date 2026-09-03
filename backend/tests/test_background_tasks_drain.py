# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_background_tasks_drain.py
# @brief      Attendre que les tâches de fond en vol se terminent — arrêt
#             propre, et fin de course dans les tests.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de ``drain()``.

Origine concrète (V0-4) : le pré-check anti-doublon de la fabrique ajoute un
accès base dans la tâche de fond du gap. La tâche déborde donc d'un cran, et
une fixture qui supprimait son utilisateur juste après le test voyait la
tâche **ré-insérer une ligne enfant entre son DELETE des enfants et son
DELETE du user** → violation de clé étrangère. La course existait déjà ; le
`await` supplémentaire l'a rendue déterministe sous SQLite `:memory:`.

``pending_count()`` savait déjà compter les tâches en vol ; il manquait de
quoi les attendre.

Run with:  cd backend && python -m pytest tests/test_background_tasks_drain.py -v
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_drain_waits_for_in_flight_tasks():
    from app.services.background_tasks import drain, pending_count, spawn

    done: list[str] = []

    async def _slow() -> None:
        await asyncio.sleep(0.05)
        done.append("fini")

    spawn(_slow(), label="slow")
    assert pending_count() == 1

    drained = await drain()

    assert done == ["fini"], "drain() a rendu la main avant la fin de la tâche"
    assert drained == 1
    assert pending_count() == 0


@pytest.mark.asyncio
async def test_drain_is_a_noop_when_nothing_is_in_flight():
    from app.services.background_tasks import drain

    assert await drain() == 0


@pytest.mark.asyncio
async def test_drain_does_not_propagate_a_failing_task():
    """Une tâche de fond qui échoue est déjà journalisée par ``spawn`` ;
    ``drain`` ne doit pas transformer ça en exception chez l'appelant."""
    from app.services.background_tasks import drain, spawn

    async def _boom() -> None:
        raise RuntimeError("échec de fond")

    spawn(_boom(), label="boom")

    assert await drain() == 1


@pytest.mark.asyncio
async def test_drain_gives_up_after_its_timeout():
    """Un drain ne doit jamais bloquer un arrêt ou un teardown indéfiniment."""
    from app.services.background_tasks import drain, spawn

    async def _endless() -> None:
        await asyncio.sleep(30)

    task = spawn(_endless(), label="endless")
    try:
        assert await drain(timeout=0.05) == 0, "les tâches non terminées ne comptent pas"
    finally:
        task.cancel()
