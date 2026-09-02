# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_taches_de_fond_retenues.py
# @brief      Les tâches de fond « tire et oublie » sont retenues et leurs
#             échecs journalisés (audit 02/09).
# @license    Elastic License 2.0
# =============================================================================
"""Pins des tâches de fond critiques.

Le défaut corrigé (audit 02/09). La notification push d'une demande
d'approbation partait en ``asyncio.create_task`` nu. La boucle
événementielle ne garde qu'une référence FAIBLE sur une tâche : sous
pression du ramasse-miettes elle peut disparaître EN VOL. Concrètement,
l'utilisateur n'était jamais prévenu qu'Ely attendait son accord, et la
demande finissait en « timeout » — c'est-à-dire en refus automatique, sans
qu'aucune ligne de log n'explique pourquoi.

Le dépôt avait déjà l'outil : ``services/background_tasks.spawn`` garde la
référence forte dans un set et journalise l'exception au lieu de la perdre
avec la tâche. D'autres sites nus sont passés au même remplaçant : la
comptabilité de tokens des missions, l'indexation FTS des messages et la
sonde des têtes de chaîne au démarrage.

⚠️ Le webhook WhatsApp était le troisième site épinglé ici. Il est parti le
02/09/2026 sous ``archive/canaux`` — zéro message en cinq mois — et ses deux
tests de rétention avec lui.

⚠️ L'indexation FTS était citée comme motif d'existence par la docstring
de ``background_tasks`` — et elle était pourtant restée en
``loop.create_task`` nu. Un recensement qui cherche ``create_task`` rate
aussi ``ensure_future`` : c'est par là que la sonde du démarrage était
passée.

Run with:  cd backend && python -m pytest tests/test_taches_de_fond_retenues.py -v
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_la_notification_hitl_est_retenue_pendant_son_vol(monkeypatch):
    """La push FCM d'une demande HITL est enregistrée comme tâche retenue."""
    from app.services import background_tasks
    from app.services.hitl_manager import HITLManager

    demarree = asyncio.Event()
    liberee = asyncio.Event()

    async def _fcm_lent(*_args, **_kwargs) -> None:
        demarree.set()
        await liberee.wait()

    async def _muet(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(HITLManager, "_send_fcm", _fcm_lent)
    monkeypatch.setattr(HITLManager, "_notify_frontend", _muet)
    monkeypatch.setattr(HITLManager, "_send_telegram", _muet)
    monkeypatch.setattr(HITLManager, "_send_ntfy", _muet)

    manager = HITLManager()
    demande = asyncio.create_task(
        manager.request_validation("supprimer le dossier", user_id="u-test")
    )
    try:
        await asyncio.wait_for(demarree.wait(), timeout=2.0)

        retenues = {
            t.get_name()
            for t in background_tasks._BG_TASKS  # noqa: SLF001 — c'est le pin
            if not t.done()
        }
        assert "hitl.push_fcm" in retenues, (
            "la push HITL n'est pas retenue : un create_task nu la laisse "
            "collectable en vol, et l'utilisateur ne voit jamais la demande"
        )
    finally:
        liberee.set()
        demande.cancel()
        with pytest.raises(asyncio.CancelledError):
            await demande
        await background_tasks.drain()


@pytest.mark.asyncio
async def test_une_notification_hitl_qui_echoue_laisse_une_trace(monkeypatch, caplog):
    """L'exception d'une push perdue en route doit finir dans les logs."""
    from app.services import background_tasks
    from app.services.hitl_manager import HITLManager

    appelee = asyncio.Event()

    async def _fcm_casse(*_args, **_kwargs) -> None:
        appelee.set()
        raise RuntimeError("firebase injoignable")

    async def _muet(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(HITLManager, "_send_fcm", _fcm_casse)
    monkeypatch.setattr(HITLManager, "_notify_frontend", _muet)
    monkeypatch.setattr(HITLManager, "_send_telegram", _muet)
    monkeypatch.setattr(HITLManager, "_send_ntfy", _muet)

    manager = HITLManager()
    demande = asyncio.create_task(
        manager.request_validation("envoyer le briefing", user_id="u-test")
    )
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.background_tasks"):
            # La demande passe d'abord par la persistance et la préférence de
            # canal : attendre l'appel réel plutôt qu'un nombre d'itérations.
            await asyncio.wait_for(appelee.wait(), timeout=2.0)
            await background_tasks.drain()
            # Le rappel `done` de `spawn` est posté en `call_soon` : lui
            # laisser un tour de boucle pour journaliser.
            await asyncio.sleep(0)
    finally:
        demande.cancel()
        with pytest.raises(asyncio.CancelledError):
            await demande

    traces = [r.getMessage() for r in caplog.records]
    assert any("hitl.push_fcm" in m and "firebase injoignable" in m for m in traces), (
        f"l'échec de la push HITL n'a laissé aucune trace : {traces}"
    )


@pytest.mark.asyncio
async def test_l_indexation_fts_d_un_message_est_retenue(monkeypatch):
    """Le site que la docstring de ``background_tasks`` cite en exemple.

    L'indexation part d'un événement SQLAlchemy synchrone : personne ne
    garde la tâche. Perdue en vol, le message n'entre jamais dans l'index
    et « tu te souviens de… » ne le retrouvera plus — sans une ligne de log.
    """
    from app.services import background_tasks, messages_fts_indexer

    demarree = asyncio.Event()
    liberee = asyncio.Event()

    async def _indexation_lente(*_args) -> None:
        demarree.set()
        await liberee.wait()

    monkeypatch.setattr(messages_fts_indexer, "_do_index", _indexation_lente)

    messages_fts_indexer._schedule_index("m-1", "c-1", "user", "coucou", 0)
    try:
        await asyncio.wait_for(demarree.wait(), timeout=2.0)

        retenues = {
            t.get_name()
            for t in background_tasks._BG_TASKS  # noqa: SLF001 — c'est le pin
            if not t.done()
        }
        assert "messages_fts.index" in retenues, (
            "l'indexation FTS n'est pas retenue : le GC peut l'emporter et "
            "le message restera introuvable par la recherche"
        )
    finally:
        liberee.set()
        await background_tasks.drain()


@pytest.mark.parametrize(
    "module, attribut",
    [
        ("app.services.hitl_manager", "spawn"),
        ("app.services.messages_fts_indexer", "spawn"),
    ],
)
def test_le_nom_spawn_de_ces_modules_est_celui_du_depot(module, attribut):
    """Filet étroit : le `spawn` lié dans ces modules n'est pas un homonyme.

    ⚠️ Ce test ne dit RIEN de l'usage : il vérifie une liaison de nom, pas
    qu'elle est appelée. Ce sont les tests de comportement ci-dessus (HITL,
    indexation FTS) qui épinglent la rétention réelle des tâches.
    """
    import importlib

    from app.services.background_tasks import spawn

    assert getattr(importlib.import_module(module), attribut) is spawn
