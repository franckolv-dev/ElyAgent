# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_discovered_tools_binding.py
# @brief      Ce que `find_tool` surface dans une MISSION doit devenir
#             appelable au tick suivant. Le filet existait pour le chat
#             depuis le 23/08 ; il n'a jamais été câblé pour les missions.
# @license    MIT
# =============================================================================
"""Les découvertes de `find_tool` sont liées au tick suivant (28/08/2026).

Mission structurée « Prospection Calameo-LinkedIn », étape `tableur` :

    it6  find_tool("create a new Google Sheet with specific headers")
         -> « Outils disponibles […] sheets_create_spreadsheet »
    it8  find_tool("create a new Google Sheet with specific headers")   (idem)
    it10 sheets_batch_update(spreadsheet_id="prospection_catalogue_2025_05_22")
         -> HTTP 404, identifiant inventé

`find_tool` avait donné la bonne réponse. L'agent ne pouvait pas l'appeler.

Double trou, tous deux pinnés ici :
  1. `find_tool` enregistre ses découvertes sous ``CURRENT_CONVERSATION_ID``,
     que seul le chemin du chat posait — en mission, il n'enregistrait rien ;
  2. la sélection d'outils par étape ne relisait jamais ces découvertes.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission_id():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations
    from app.skills.builtin import register_all

    # Le registre n'est peuplé qu'au démarrage de l'app : sans ça, la
    # sélection d'outils travaille sur un catalogue vide et ne prouve rien.
    register_all()
    await init_db()
    await ensure_migrations()
    uid = f"test_disco_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="créer un tableur",
    )
    yield uid, m.id
    from app.agent.discovered_tools import discard_discovered
    discard_discovered(m.id)
    async with async_session() as db:
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


@pytest.mark.asyncio
async def test_dispatch_pose_le_contexte_de_la_mission(mission_id) -> None:
    """Sans ce contexte, `find_tool` enregistre ses trouvailles… nulle part."""
    from app.agent.missions.nodes import dispatch_tool
    from app.agent.tool_context import CURRENT_CONVERSATION_ID

    uid, mid = mission_id
    vu: list[str] = []

    async def _sonde(**_kwargs):
        vu.append(CURRENT_CONVERSATION_ID.get())
        return "ok"

    import app.agent.missions.nodes as mn
    from app.skills import get_skill_registry

    class _FauxOutil:
        name = "sonde_contexte"
        description = "sonde"
        coroutine = staticmethod(_sonde)

        async def ainvoke(self, _args):
            return await _sonde()

    reg = get_skill_registry()
    # ⚠️ On restaure la PROPRIÉTÉ D'ORIGINE, pas une qui rend l'instantané.
    # Avant le 02/09/2026, le `finally` reposait `property(lambda: original)` :
    # `all_tools` restait FIGÉ pour tout le reste de la session pytest, et
    # toute compétence enregistrée plus tard devenait invisible en silence.
    # Un test du lot « la mission est le chat sans humain » est tombé dessus —
    # il enregistrait un faux outil que le nœud agent ne voyait jamais.
    propriete_originale = type(reg).__dict__["all_tools"]
    instantane = list(reg.all_tools)
    try:
        type(reg).all_tools = property(lambda _self: instantane + [_FauxOutil()])
        await dispatch_tool("sonde_contexte", {}, "call-1", uid, mission_id=mid)
    finally:
        type(reg).all_tools = propriete_originale

    assert vu and vu[0] == mid, (
        "l'exécution d'un outil de mission doit porter l'identité de la "
        "mission, sinon find_tool n'a nulle part où consigner ses découvertes"
    )


@pytest.mark.asyncio
async def test_les_decouvertes_sont_liees_a_l_etape_suivante(mission_id) -> None:
    """Ce que find_tool a surfacé doit être appelable au tick d'après."""
    import app.agent.missions.nodes as mn
    from app.agent.discovered_tools import add_discovered
    from app.skills import get_skill_registry

    uid, mid = mission_id
    add_discovered(mid, ["sheets_create_spreadsheet"])

    tous = get_skill_registry().all_tools
    # Description volontairement pauvre en signal : c'est le cas où la
    # sélection sémantique échoue et où la découverte doit prendre le relais.
    outils = await mn._filter_tools_for_step(
        tous, None, "objectif quelconque", "Fais ce qu'il faut ici.",
        mission_id=mid,
    )

    assert "sheets_create_spreadsheet" in [t.name for t in outils], (
        "find_tool promet « utilise-les directement maintenant » — "
        "la liaison du tick suivant doit tenir cette promesse"
    )


@pytest.mark.asyncio
async def test_sans_decouverte_la_selection_est_inchangee(mission_id) -> None:
    """Le filet n'élargit rien tant que rien n'a été découvert."""
    import app.agent.missions.nodes as mn
    from app.skills import get_skill_registry

    _uid, mid = mission_id
    tous = get_skill_registry().all_tools

    avec = await mn._filter_tools_for_step(
        tous, None, "objectif", "Cherche des informations.", mission_id=mid,
    )
    sans = await mn._filter_tools_for_step(
        tous, None, "objectif", "Cherche des informations.",
    )

    assert [t.name for t in avec] == [t.name for t in sans]
