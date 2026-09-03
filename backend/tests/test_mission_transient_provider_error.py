# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_transient_provider_error.py
# @brief      Un 429 du fournisseur reporte le tick ; il ne tue pas la mission.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Une limite de débit n'est pas un bug (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print », 01h46. Le `foreach` avait enfin produit ses
5 sociétés, l'historique était créé, le tableur aussi, et l'item 1 tournait :

    status = failed
    failure_reason = graph crashed: {'message': 'Provider returned error',
                                     'code': 429}

Vingt-cinq minutes de travail perdues sur une limite de débit du fournisseur
— un état passager qui se résout tout seul en attendant.

LA CAUSE
--------
``_process_one_mission`` traite TOUTE exception de la même façon : `fail_mission`.
Aucune distinction entre « le graphe est cassé » et « le fournisseur nous
demande de ralentir ».

Le bon comportement est déjà écrit vingt lignes plus haut, pour le budget
quotidien du user :

    « On ne tue PAS la mission : un user temporairement à sec ne doit pas
      perdre son travail — le tick est reporté d'une heure. »

Un 429 relève exactement du même raisonnement.

LA BORNE
--------
Le report n'est pas illimité : un fournisseur durablement en panne laisserait
sinon une mission « en cours » pour toujours, ce qui est pire qu'un échec
franc parce que muet. `provider_retries` compte les reports, se remet à zéro
au premier tick réussi, et au-delà de MAX_PROVIDER_RETRIES la mission échoue
en NOMMANT la cause.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

_ERREUR_429 = {"message": "Provider returned error", "code": 429}


@pytest_asyncio.fixture
async def mission():
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations
    from tests._user_cleanup import purge_user

    await init_db()
    await ensure_migrations()
    uid = f"test_429_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Débit", goal="prospecter",
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    # Nettoyage dérivé du schéma : trois fixtures de suite ont oublié une
    # table fille et fait rougir la CI. Voir tests/_user_cleanup.py.
    await purge_user(uid)



async def _tick_qui_leve(monkeypatch, mid: str, uid: str, exc: Exception):
    """Fait tourner un tick dont le graphe lève `exc`."""
    from app.database import async_session
    from app.models.mission import Mission
    from app.services import mission_heartbeat as hb

    async def _boom(*_a, **_kw):
        raise exc

    monkeypatch.setattr(hb, "_tick_one_mission", _boom)
    async with async_session() as db:
        m = await db.get(Mission, mid)
        await hb._process_one_mission(m)
    async with async_session() as db:
        return await db.get(Mission, mid)


# ── Le report ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_429_reporte_le_tick_et_ne_tue_pas_la_mission(
    mission, monkeypatch,
) -> None:
    uid, mid = mission
    m = await _tick_qui_leve(monkeypatch, mid, uid, RuntimeError(str(_ERREUR_429)))

    assert m.status != "failed", (
        "vingt-cinq minutes de travail perdues parce que le fournisseur "
        "nous demandait de ralentir"
    )
    assert m.next_tick_at is not None, "le tick doit être reprogrammé"
    assert m.provider_retries == 1


@pytest.mark.asyncio
async def test_les_autres_pannes_passageres_aussi(mission, monkeypatch) -> None:
    """502/503/504 et délais dépassés relèvent du même traitement."""
    uid, mid = mission
    m = await _tick_qui_leve(
        monkeypatch, mid, uid,
        RuntimeError("upstream error 503 Service Unavailable"),
    )
    assert m.status != "failed"


# ── Mais un vrai bug reste un vrai bug ──────────────────────────────────


@pytest.mark.asyncio
async def test_un_bug_du_graphe_echoue_toujours(mission, monkeypatch) -> None:
    """Sinon on masquerait les défauts qu'on passe nos journées à trouver."""
    uid, mid = mission
    m = await _tick_qui_leve(
        monkeypatch, mid, uid,
        UnboundLocalError("cannot access local variable 'new_plan'"),
    )
    assert m.status == "failed"
    assert "graph crashed" in (m.failure_reason or "")


# ── Et le report est borné ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_au_dela_de_la_borne_la_mission_echoue_en_le_disant(
    mission, monkeypatch,
) -> None:
    """Une mission « en cours » pour toujours est pire qu'un échec franc."""
    from app.services import mission_heartbeat as hb

    uid, mid = mission
    for _ in range(hb.MAX_PROVIDER_RETRIES + 1):
        m = await _tick_qui_leve(
            monkeypatch, mid, uid, RuntimeError(str(_ERREUR_429)),
        )

    assert m.status == "failed"
    assert "429" in (m.failure_reason or ""), (
        "l'échec doit nommer la cause : c'est le fournisseur, pas la mission"
    )


@pytest.mark.asyncio
async def test_un_tick_reussi_remet_le_compteur_a_zero(
    mission, monkeypatch,
) -> None:
    """Sinon un 429 par jour finirait par tuer une mission qui va bien."""
    from app.database import async_session
    from app.models.mission import Mission
    from app.services import mission_heartbeat as hb

    uid, mid = mission
    await _tick_qui_leve(monkeypatch, mid, uid, RuntimeError(str(_ERREUR_429)))

    async def _ok(*_a, **_kw):
        return {"iteration": 2, "done": False}

    monkeypatch.setattr(hb, "_tick_one_mission", _ok)
    async with async_session() as db:
        m = await db.get(Mission, mid)
        await hb._process_one_mission(m)

    async with async_session() as db:
        assert (await db.get(Mission, mid)).provider_retries == 0
