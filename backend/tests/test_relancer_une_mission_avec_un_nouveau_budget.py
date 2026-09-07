# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_relancer_une_mission_avec_un_nouveau_budget.py
# @brief      Une mission à bout de budget se relance en gardant son carnet,
#             avec un budget plus grand ; le plafond passe à 10 millions.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""« Plateformes littéraires » (07/09/2026) : compte créé, mail confirmé,
puis « budget de tokens de la mission épuisé (5 168 371 / 5 000 000) ».
Pour continuer il fallait un appel d'API à la main : la page n'avait pas de
bouton, et le plafond de création (5 M) était déjà atteint.

Run with:  cd backend && python -m pytest tests/test_relancer_une_mission_avec_un_nouveau_budget.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_budget_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Plateformes", goal="Ajoute le roman sur SensCritique.",
        budget_tokens=5_000_000,
    )
    yield uid, m.id
    await purge_user(uid)


async def _relancer(uid: str, mid: str, monkeypatch, **kwargs):
    from app.database import async_session
    from app.models.mission import Mission
    from app.models.user import User
    from app.routers import missions as routeur

    async def _fake_own(mission_id, _user):
        async with async_session() as db:
            return await db.get(Mission, mission_id)

    monkeypatch.setattr(routeur, "_own_or_404", _fake_own)
    return await routeur.restart(
        mid, body=routeur._RestartBody(**kwargs),
        current_user=User(id=uid, username="u", email="u@x", hashed_password="x"),
    )


def test_le_plafond_de_creation_est_de_dix_millions():
    from pydantic import ValidationError

    from app.routers.missions import MissionCreate

    ok = MissionCreate(title="T", goal="Objectif long", budget_tokens=10_000_000)
    assert ok.budget_tokens == 10_000_000
    with pytest.raises(ValidationError):
        MissionCreate(title="T", goal="Objectif long", budget_tokens=10_000_001)


@pytest.mark.asyncio
async def test_une_mission_a_bout_de_budget_se_relance_avec_dix_millions(mission, monkeypatch):
    uid, mid = mission
    from app.services import mission_service
    from app.services.mission_workspace import carnet_append_section, read_carnet

    await mission_service.start_mission(mid)
    await mission_service.mark_running(mid)
    await mission_service.add_tokens_used(mid, 5_100_000)
    carnet_append_section(mid, "Passages", "**Passage 3** — compte créé, mail confirmé")
    await mission_service.fail_mission(mid, "budget de tokens de la mission épuisé")

    out = await _relancer(uid, mid, monkeypatch, keep_history=True, max_tokens=10_000_000)

    assert out.status == "draft"
    assert out.budget_tokens == 10_000_000
    assert out.tokens_used == 0 and out.iterations_used == 0
    assert out.failure_reason is None
    assert "Passage 3" in (read_carnet(mid) or ""), "le carnet doit survivre à la relance"


@pytest.mark.asyncio
async def test_relancer_une_mission_en_attente_efface_sa_question(mission, monkeypatch):
    uid, mid = mission
    from app.services import mission_questions, mission_service

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(mission_questions, "notifier", _rien)
    await mission_service.start_mission(mid)
    await mission_questions.poser(mid, "Lequel ?")

    out = await _relancer(uid, mid, monkeypatch, keep_history=True)

    assert out.status == "draft"
    assert out.pending_question is None
