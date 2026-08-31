# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_last_output_not_truncated.py
# @brief      La sortie que l'acteur doit RECOPIER ne doit pas etre coupee
#             a 1 200 caracteres avant qu'il la lise.
# @license    Elastic License 2.0
# =============================================================================
"""On ne recopie pas ce qu'on ne voit pas (31/08/2026).

L'INCIDENT
----------
Mission « Prospection STE Print », société Négoce Drouillet. La trace :

    it22  browser_tab_read_text   → 4 581 caractères de profils LinkedIn
    it23  eval : « Les profils ont été identifiés mais ils n'ont pas encore
                   été ajoutés au Google Sheet comme demandé. »
    it24  browser_open_tab        ← il rouvre l'onglet au lieu d'écrire
    it26  browser_tab_wait_loaded
    it28  browser_tab_read_text   → 4 581 caractères, à l'identique

Le verdict était juste et l'acteur le lisait (le bloc de retour existe
depuis la veille). Il ne relançait pas la lecture par entêtement : il
n'avait tout simplement jamais reçu les profils.

LA CAUSE
--------
``_load_recent_step_outputs`` coupe CHAQUE sortie à ``max_chars=1200``. Une
page LinkedIn lue fait 4 200 à 4 600 caractères, dont ~280 rien que pour
l'URL de recherche. L'acteur voyait l'adresse et le début de la page, jamais
la liste qu'il devait transcrire dans le tableur.

Océalia est passée par chance : ses premiers profils tenaient dans les
1 200 premiers caractères.

LA RÈGLE
--------
La DERNIÈRE sortie est celle sur laquelle l'étape courante travaille : elle
a droit à la même place que ce qu'on archive (``STEP_OUTPUT_ARCHIVE_CHARS``).
Les précédentes restent au régime serré — elles servent de rappel, pas de
matière première, et huit sorties larges feraient exploser le prompt.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

_PAGE_LINKEDIN = "URL : https://www.linkedin.com/search/results/people/?keywords=" + (
    "x" * 200
) + "\n" + "\n".join(
    f"{i}. Prénom{i} Nom{i} — Directeur marketing — linkedin.com/in/profil{i}"
    for i in range(60)
)


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
    uid = f"test_ctx_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Contexte", goal="prospecter",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStep).where(MissionStep.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_la_derniere_sortie_arrive_entiere(mission) -> None:
    """4 581 caractères de profils, coupés à 1 200 : rien à recopier."""
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    _uid, mid = mission
    assert len(_PAGE_LINKEDIN) > 3000, "l'échantillon doit dépasser l'ancienne coupe"
    await mission_service.add_step(
        mid, phase="act", tool_name="browser_tab_read_text",
        tool_input={}, tool_output=_PAGE_LINKEDIN, success=True, duration_ms=1,
    )

    contexte = await mn._load_recent_step_outputs(mid)

    assert "profil59" in contexte, (
        "le dernier profil de la page doit arriver jusqu'à l'acteur — sans "
        "lui, il relit la page au lieu d'écrire la ligne"
    )


@pytest.mark.asyncio
async def test_les_sorties_plus_anciennes_restent_au_regime_serre(
    mission,
) -> None:
    """Huit sorties larges feraient exploser le prompt."""
    import app.agent.missions.nodes as mn
    from app.services import mission_service

    _uid, mid = mission
    await mission_service.add_step(
        mid, phase="act", tool_name="browser_tab_read_text",
        tool_input={}, tool_output=_PAGE_LINKEDIN, success=True, duration_ms=1,
    )
    await mission_service.add_step(
        mid, phase="act", tool_name="sheets_append_rows",
        tool_input={}, tool_output="1 ligne ajoutée", success=True, duration_ms=1,
    )

    contexte = await mn._load_recent_step_outputs(mid)

    assert "1 ligne ajoutée" in contexte, "la dernière sortie est bien là"
    assert "[…tronqué]" in contexte, (
        "la page LinkedIn, devenue une sortie ancienne, doit être resserrée"
    )
    assert "profil59" not in contexte
