# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_tick_manuel_prend_le_bon_moteur.py
# @brief      Le bouton « Tick » du routeur lancait l'AUTRE moteur, sans garde
#             de concurrence — deux moteurs distincts sur les memes tables.
# @license    MIT
# =============================================================================
"""Le Tick manuel doit passer par le meme aiguillage que le heartbeat.

LE CONSTAT (relecture adverse du 02/09/2026)
--------------------------------------------
Depuis que la mission libre tourne sur la boucle du chat, le dépôt a DEUX
moteurs. `POST /api/missions/{id}/tick` compilait encore `build_mission_graph()`
en dur : un Tick presse sur une mission qui tourne sur la boucle du chat
lancait plan/act/eval a cote du passage en cours.

Et il ne prenait pas `_in_flight`, le garde-fou dont le heartbeat se sert pour
interdire deux ticks simultanes de la meme mission. Avant ce lot les deux
chemins etaient le MEME graphe sur le MEME checkpointer, qui serialise ; ce
sont maintenant deux moteurs distincts qui ecrivent dans les memes
`mission_steps` et appellent le meme `complete_mission`.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

_BUT = "Trouve trois imprimeries et note-les dans un tableur."


class _FauxUser:
    def __init__(self, uid: str) -> None:
        self.id = uid


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_tick_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield _FauxUser(uid), m.id
    await purge_user(uid)


def _deux_moteurs(monkeypatch) -> dict:
    """Compte qui a tourne : la machine a etats, ou la boucle du chat."""
    appels = {"graphe": 0, "chat": 0}

    async def _faux_graphe(*_a, **_k):
        appels["graphe"] += 1
        return {"iteration": 1}

    async def _fausse_boucle(*_a, **_k):
        appels["chat"] += 1
        return {"done": False, "failed": False, "actions": 0}

    import app.agent.missions.chat_loop as cl
    import app.services.mission_heartbeat as hb

    monkeypatch.setattr(hb, "_tick_mission_graph", _faux_graphe)
    monkeypatch.setattr(cl, "run_mission_chat_passage", _fausse_boucle)
    return appels


@pytest.mark.asyncio
async def test_le_tick_manuel_lance_le_moteur_de_la_mission(mission, monkeypatch):
    """Une mission libre tourne sur la boucle du chat, Tick compris."""
    user, mid = mission
    appels = _deux_moteurs(monkeypatch)

    from app.routers.missions import tick

    await tick(mid, current_user=user)

    assert appels == {"graphe": 0, "chat": 1}, (
        "le bouton Tick a lance l'AUTRE moteur sur une mission qui tourne sur "
        "la boucle du chat"
    )


@pytest.mark.asyncio
async def test_un_tick_manuel_pendant_un_passage_est_refuse(mission, monkeypatch):
    """Deux moteurs sur les memes `mission_steps` et le meme
    `complete_mission` : le Tick doit prendre le garde-fou du heartbeat."""
    user, mid = mission
    appels = _deux_moteurs(monkeypatch)

    import app.services.mission_heartbeat as hb

    from app.routers.missions import tick

    hb._in_flight.add(mid)
    try:
        with pytest.raises(HTTPException) as capture:
            await tick(mid, current_user=user)
    finally:
        hb._in_flight.discard(mid)

    assert capture.value.status_code == 409
    assert appels == {"graphe": 0, "chat": 0}, (
        "un passage etait deja en vol : aucun moteur ne devait demarrer"
    )


@pytest.mark.asyncio
async def test_le_tick_manuel_rend_le_garde_fou_a_la_fin(mission, monkeypatch):
    """Un Tick qui garderait `_in_flight` bloquerait le heartbeat pour
    toujours — la mission ne se reveillerait plus jamais."""
    user, mid = mission
    _deux_moteurs(monkeypatch)

    import app.services.mission_heartbeat as hb

    from app.routers.missions import tick

    await tick(mid, current_user=user)
    assert mid not in hb._in_flight

    async def _qui_plante(*_a, **_k):
        raise RuntimeError("Provider returned error, code 429")

    import app.agent.missions.chat_loop as cl

    monkeypatch.setattr(cl, "run_mission_chat_passage", _qui_plante)
    with pytest.raises(HTTPException) as capture:
        await tick(mid, current_user=user)
    assert mid not in hb._in_flight, (
        "un tick qui plante doit rendre le garde-fou, sinon la mission est "
        "muree hors du heartbeat"
    )

    # 02/09/2026 — la panne jouee ci-dessus est un 429, PASSAGERE. Le
    # heartbeat reporte le tick au lieu de tuer la mission (c41d758) ; le Tick
    # manuel s'aligne. Sans ces deux assertions, un retour a
    # `fail_mission` + 500 resterait vert : `pytest.raises(HTTPException)`
    # ne distingue pas « reviens plus tard » de « ta mission est morte ».
    assert capture.value.status_code == 503, (
        "une limite de debit du fournisseur doit rendre 503, pas tuer la "
        "mission"
    )
    from app.services import mission_service

    survivante = await mission_service.get_mission(mid)
    assert survivante.status not in {"failed", "aborted"}, (
        f"une panne passagere a tue la mission (status={survivante.status}) : "
        f"vingt-cinq minutes de travail perdues sur un 429"
    )
