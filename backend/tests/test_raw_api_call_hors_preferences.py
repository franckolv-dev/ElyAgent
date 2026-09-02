# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_raw_api_call_hors_preferences.py
# @brief      Les passe-plats *_raw_api_call ne sont plus dispensables de HITL.
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Audit sécurité 2026-09-02 — la porte la plus large fermable d'un clic.

Les sept outils ``*_raw_api_call`` (gmail, drive, calendar, docs, sheets,
tasks, contacts) sont des passe-plats vers l'API Google ENTIÈRE : la méthode
arrive en chemin pointé, donc ``users.settings.forwardingAddresses.create``
et ``users.settings.filters.create`` passent par là. Un transfert automatique
de toute la boîte s'installe avec cet outil.

Ils étaient bien dans ``LOCKED_HITL_TOOLS``, donc la confirmation partait.
Mais depuis 2026-06-19 la préférence utilisateur « Toujours autoriser » vaut
AUSSI pour les outils dangereux, et ``user_requires_hitl`` l'honore : un seul
clic, dans une fenêtre d'approbation qui n'affiche qu'un JSON brut, éteignait
définitivement la garde de ces sept outils — et donc, par ricochet, celle de
tous les autres outils Google, puisqu'un ``raw_api_call`` refait ce qu'ils
font sans passer par eux.

La règle posée ici : la préférence reste honorée partout ailleurs, seuls les
passe-plats deviennent non dispensables. On teste les trois niveaux :
la résolution (qui prime sur la ligne déjà en base), l'écriture de la
préférence, et l'API qui l'expose.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.hitl_preference import HitlPreference
from app.routers.hitl_prefs import (
    HitlPrefUpdate,
    list_preferences,
    update_preference,
)
from app.services.hitl_preferences import (
    LOCKED_HITL_TOOLS,
    is_hitl_waivable,
    set_user_preference,
    user_requires_hitl,
)

# Les sept passe-plats recensés dans app/agent/tools/ au 02/09/2026.
_PASSE_PLATS = (
    "gmail_raw_api_call",
    "drive_raw_api_call",
    "calendar_raw_api_call",
    "docs_raw_api_call",
    "sheets_raw_api_call",
    "tasks_raw_api_call",
    "contacts_raw_api_call",
)
# Outil DANGEREUX mais ordinaire : la dispense doit continuer d'y marcher.
_DANGEREUX_ORDINAIRE = "gmail_trash_emails"


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "raw_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid}", email=f"{uid}@test.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(HitlPreference).where(HitlPreference.user_id == uid))
        await db.commit()


async def _forcer_dispense_en_base(user_id: str, tool_name: str) -> None:
    """Écrit la dispense DIRECTEMENT en base, sans passer par le service.

    Reproduit une ligne déjà présente en production (28 lignes au 02/09) :
    la règle doit primer sur la donnée existante, sans migration.
    """
    async with async_session() as db:
        db.add(HitlPreference(
            user_id=user_id, tool_name=tool_name, requires_confirmation=False,
        ))
        await db.commit()


# ── 1. La résolution prime sur la ligne en base ──────────────────────────────
@pytest.mark.parametrize("tool_name", _PASSE_PLATS)
@pytest.mark.asyncio
async def test_une_dispense_deja_en_base_est_ignoree_pour_un_passe_plat(
    _user, tool_name,
):
    await _forcer_dispense_en_base(_user, tool_name)
    assert await user_requires_hitl(_user, tool_name) is True


@pytest.mark.asyncio
async def test_la_dispense_reste_honoree_pour_un_outil_dangereux_ordinaire(_user):
    """La liberté du 19/06 n'est pas retirée : seuls les passe-plats sortent."""
    assert _DANGEREUX_ORDINAIRE in LOCKED_HITL_TOOLS
    await _forcer_dispense_en_base(_user, _DANGEREUX_ORDINAIRE)
    assert await user_requires_hitl(_user, _DANGEREUX_ORDINAIRE) is False


# ── 2. L'écriture de la préférence refuse la dispense ────────────────────────
@pytest.mark.asyncio
async def test_set_user_preference_refuse_de_dispenser_un_passe_plat(_user):
    assert await set_user_preference(
        _user, "gmail_raw_api_call", requires_confirmation=False,
    ) is False
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlPreference).where(HitlPreference.user_id == _user)
        )).scalars().all()
    assert rows == [], "aucune ligne ne doit être écrite pour une dispense refusée"


@pytest.mark.asyncio
async def test_set_user_preference_accepte_de_reactiver_la_confirmation(_user):
    """Refuser la dispense n'interdit pas d'écrire l'inverse (re-armement)."""
    assert await set_user_preference(
        _user, "gmail_raw_api_call", requires_confirmation=True,
    ) is True


# ── 3. L'API : liste et enregistrement ───────────────────────────────────────
class _FakeUser:
    id = "raw-api-prefs-test-user"


@pytest.mark.asyncio
async def test_l_api_refuse_d_enregistrer_la_dispense_d_un_passe_plat():
    await init_db()
    with pytest.raises(HTTPException) as exc:
        await update_preference(
            body=HitlPrefUpdate(
                tool_name="gmail_raw_api_call", requires_confirmation=False,
            ),
            current_user=_FakeUser(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_la_liste_marque_les_passe_plats_non_dispensables():
    await init_db()
    rows = await list_preferences(current_user=_FakeUser(), accept_language="fr")
    par_nom = {r.tool_name: r for r in rows}
    for tool_name in _PASSE_PLATS:
        assert tool_name in par_nom, f"{tool_name} doit rester listé"
        assert par_nom[tool_name].waivable is False
        assert par_nom[tool_name].requires_confirmation is True
        assert par_nom[tool_name].dangerous is True
    # Un outil ordinaire reste réglable.
    assert par_nom["gmail_send_email"].waivable is True
    assert par_nom[_DANGEREUX_ORDINAIRE].waivable is True


# ── 4. La règle est générique, pas une liste en dur ──────────────────────────
def test_la_regle_couvre_un_passe_plat_pas_encore_ecrit():
    """Le prochain ``*_raw_api_call`` ajouté doit être couvert sans édition."""
    assert is_hitl_waivable("keep_raw_api_call") is False
    assert is_hitl_waivable("gmail_send_email") is True


def test_les_sept_passe_plats_connus_sont_tous_dans_locked():
    for tool_name in _PASSE_PLATS:
        assert tool_name in LOCKED_HITL_TOOLS
        assert is_hitl_waivable(tool_name) is False
