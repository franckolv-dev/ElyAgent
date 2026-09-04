# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_relancer_une_mission_repart_a_zero.py
# @brief      Relancer une mission efface aussi sa MÉMOIRE de travail : le
#             carnet de bord, la sélection d'outils et le plan de session.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Prospection CLM-LKDN » (722d111f), 04/09/2026 à 22h50.

Franck modifie l'objectif d'une mission réussie — cinq sociétés au lieu de
trois, compléter le tableur au lieu d'en créer un — puis la relance. En
51 secondes et 7 actions, elle se déclare terminée sans avoir rien produit.

L'objectif MODIFIÉ était bien en base. Ce qui a décidé, c'est la mémoire de
la mission précédente, que ``/restart`` ne touchait pas :

- ``CARNET.md`` ouvrait la consigne sur « **Passage 1** — mission conclue » ;
- ``session_todo``, au tout premier appel du nouveau passage, rendait
  « Plan — 7 étape(s), 4 faite(s) » ;
- ``OUTILS.json`` figeait la sélection d'outils faite pour l'ANCIEN objectif.

Le modèle a lu qu'il avait déjà fait le travail, a relu le tableur qui le
confirmait, et a conclu. Il avait raison sur les faits qu'on lui donnait.

👉 ``/restart`` promet « wipe plan history + steps so the next start produces
a fresh plan ». Depuis #370 le plan d'une mission n'est plus dans
``MissionPlan`` : il est dans le CARNET. Effacer les tables sans effacer le
carnet, c'est effacer la copie et garder l'original.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionPlan, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service

    await init_db()
    uid = f"test_relance_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="Trouve trois sociétés.",
    )
    yield uid, m.id
    async with async_session() as db:
        for modele in (MissionStepRun, MissionStep, MissionPlan):
            await db.execute(delete(modele).where(modele.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


def _memoire_de_travail(mission_id: str) -> None:
    """L'état qu'un passage laisse derrière lui."""
    from app.services.mission_workspace import carnet_append_section, ensure_workspace

    ws = ensure_workspace(mission_id)
    carnet_append_section(mission_id, "Passages", "**Passage 1** — mission conclue")
    (ws / "OUTILS.json").write_text(
        json.dumps({"familles": ["drive"], "outils": ["drive_list_files"], "choisis": []}),
        encoding="utf-8",
    )
    (ws / "artefacts" / "livrable.csv").write_text("societe,nom\n", encoding="utf-8")


async def _relancer(uid: str, mid: str, monkeypatch, **kwargs):
    from app.database import async_session
    from app.models.mission import Mission
    from app.models.user import User
    from app.routers import missions as routeur

    async def _fake_own(mission_id, _user):
        async with async_session() as db:
            return await db.get(Mission, mission_id)

    monkeypatch.setattr(routeur, "_own_or_404", _fake_own)
    body = routeur._RestartBody(**kwargs) if kwargs else None
    return await routeur.restart(
        mid, body=body,
        current_user=User(id=uid, username="u", email="u@x", hashed_password="x"),
    )


# ── La remise à zéro du plan de travail ──────────────────────────────────────

def test_la_remise_a_zero_efface_le_carnet_et_la_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.services.mission_workspace import (
        read_carnet, reinitialiser, workspace_dir,
    )

    mid = str(uuid.uuid4())
    _memoire_de_travail(mid)

    reinitialiser(mid)

    assert read_carnet(mid) is None
    assert not (workspace_dir(mid) / "OUTILS.json").exists()
    assert (workspace_dir(mid) / "artefacts" / "livrable.csv").exists(), (
        "les artefacts sont le TRAVAIL produit, pas la mémoire du passage"
    )


def test_la_remise_a_zero_d_un_workspace_absent_ne_leve_pas(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.services.mission_workspace import reinitialiser

    reinitialiser(str(uuid.uuid4()))


def test_le_plan_de_session_s_oublie():
    from app.agent.tools.todo_tool import _registre, etapes_restantes, oublier

    conv = f"mission-{uuid.uuid4().hex[:8]}"
    from app.agent.tools.todo_tool import _Plan

    _registre[conv] = _Plan(taches=("relire l'historique", "écrire le tableur"),
                            en_cours=1, faites=frozenset({1}))
    assert etapes_restantes(conv)

    oublier(conv)

    assert etapes_restantes(conv) == ""
    oublier(conv)  # idempotent


# ── Le branchement dans /restart ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relancer_efface_la_memoire_du_passage_precedent(mission, monkeypatch):
    """LE défaut du 04/09 : la mission relue se croyait déjà terminée."""
    from app.agent.tools.todo_tool import _Plan, _registre, etapes_restantes
    from app.services.mission_workspace import read_carnet, workspace_dir

    uid, mid = mission
    _memoire_de_travail(mid)
    _registre[mid] = _Plan(taches=("relire l'historique",), faites=frozenset({1}))

    await _relancer(uid, mid, monkeypatch)

    assert read_carnet(mid) is None, (
        "la consigne du prochain passage rouvrirait sur « mission conclue »"
    )
    assert not (workspace_dir(mid) / "OUTILS.json").exists(), (
        "l'objectif a pu changer : la sélection d'outils se refait"
    )
    assert etapes_restantes(mid) == ""
    assert (workspace_dir(mid) / "artefacts" / "livrable.csv").exists()


@pytest.mark.asyncio
async def test_keep_history_garde_aussi_le_carnet(mission, monkeypatch):
    """`keep_history=true` demande explicitement de tout garder."""
    from app.services.mission_workspace import read_carnet, workspace_dir

    uid, mid = mission
    _memoire_de_travail(mid)

    await _relancer(uid, mid, monkeypatch, keep_history=True)

    assert "Passage 1" in (read_carnet(mid) or "")
    assert (workspace_dir(mid) / "OUTILS.json").exists()
