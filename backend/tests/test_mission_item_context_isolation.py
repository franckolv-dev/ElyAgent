# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_item_context_isolation.py
# @brief      Les sorties d'outil d'une AUTRE societe d'un foreach n'ont rien
#             a faire dans le contexte de la societe courante.
# @license    Elastic License 2.0
# =============================================================================
"""Un item qui échoue contaminait tous les suivants (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print », trois sociétés à traiter :

    it10-20  Rullier Bois      6 actions, la page LinkedIn répond
                               « Aucun résultat » (vérifié, la page était
                               réellement vide)
    it22     Rullier Bois      not_found → sauté
    it24     Négoce Drouillet  not_found — ZÉRO action
    it26     Novapierre        not_found — ZÉRO action

Les deux dernières sociétés n'ont jamais été cherchées. Pas un onglet
ouvert, pas une lecture. Ely a déclaré « aucun contact trouvé » pour des
sociétés qu'elle n'a pas regardées, et le handler `skip_with_note` l'a
consigné comme un fait.

LA CAUSE
--------
``_load_recent_step_outputs`` sert à l'acteur les dernières sorties d'outils
réussies, sans distinguer l'item auquel elles appartiennent. Au moment de
traiter Négoce Drouillet, son contexte était rempli des pages « Aucun
résultat » de **Rullier Bois**. Il les a lues comme si elles portaient sur
la société courante, et a conclu.

Le correctif de la veille l'a aggravé : en donnant 6 000 caractères à la
dernière sortie au lieu de 1 200, la page parasite est devenue beaucoup plus
présente dans le prompt.

LA RÈGLE
--------
Les sorties d'un AUTRE item sont écartées. Celles des étapes ordinaires
(l'identifiant du tableur, la liste des sociétés) restent : elles valent
pour tous les items.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_iso_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Isolation", goal="prospecter",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStep).where(MissionStep.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


async def _trace(mid: str) -> None:
    """Une étape ordinaire, puis l'item 1 qui ne trouve rien."""
    from app.services import mission_service

    await mission_service.add_step(
        mid, phase="act", tool_name="sheets_create_spreadsheet",
        tool_input={}, tool_output="Feuille créée. ID : ss-42",
        thought="Étape « Crée le tableur du jour »",
        success=True, duration_ms=1,
    )
    await mission_service.add_step(
        mid, phase="act", tool_name="browser_tab_read_text",
        tool_input={}, tool_output="Aucun résultat pour RULLIER BOIS",
        thought="Étape « [Item 1 : Rullier Bois] Ouvre LinkedIn et cherche »",
        success=True, duration_ms=1,
    )


@pytest.mark.asyncio
async def test_la_page_d_une_autre_societe_est_ecartee(mission) -> None:
    """C'est elle qui a fait conclure « aucun contact » sans chercher."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trace(mid)

    # On traite maintenant l'item 2 (Négoce Drouillet).
    contexte = await mn._load_recent_step_outputs(mid, item_index=1)

    assert "RULLIER BOIS" not in contexte, (
        "la page « Aucun résultat » d'une autre société n'a rien à faire "
        "dans le contexte de celle-ci"
    )


@pytest.mark.asyncio
async def test_les_etapes_ordinaires_restent_visibles(mission) -> None:
    """L'identifiant du tableur vaut pour TOUS les items."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trace(mid)

    contexte = await mn._load_recent_step_outputs(mid, item_index=1)
    assert "ss-42" in contexte, (
        "sans lui, l'item ne sait plus dans quelle feuille écrire"
    )


@pytest.mark.asyncio
async def test_l_item_courant_garde_ses_propres_sorties(mission) -> None:
    """Ce qu'IL a lui-même lu reste indispensable — c'est ce qu'il recopie."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trace(mid)

    contexte = await mn._load_recent_step_outputs(mid, item_index=0)
    assert "RULLIER BOIS" in contexte


@pytest.mark.asyncio
async def test_hors_foreach_rien_n_est_filtre(mission) -> None:
    """Une étape ordinaire voit tout, comme avant."""
    import app.agent.missions.nodes as mn

    _uid, mid = mission
    await _trace(mid)

    contexte = await mn._load_recent_step_outputs(mid)
    assert "ss-42" in contexte
    assert "RULLIER BOIS" in contexte
