# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_discovery_never_completes.py
# @brief      Un outil de DÉCOUVERTE ne peut pas accomplir une étape. Il
#             prépare l'action, il ne la fait pas — le confondre avec un
#             résultat marque « done » une étape dont rien n'a été produit.
# @license    Elastic License 2.0
# =============================================================================
"""`find_tool` ne valide jamais une étape (incident du 28/08/2026).

Mission structurée « Prospection Calameo-LinkedIn », étape `tableur` —
« Crée sur mon Google Drive un Google Sheet nommé … » :

    it6  ACT   find_tool("create a new Google Sheet with specific headers")
    it7  EVAL  ok=1 — « find_tool a correctement identifié les outils
                        disponibles pour répondre à la demande »

L'étape est passée `done`. Aucun tableur n'a été créé, et la suite du plan
a travaillé sur un fichier qui n'existait pas.

L'évaluateur avait raison sur ce qu'il jugeait : `find_tool` A bien
fonctionné. Mais une étape mutative ne peut pas être accomplie par un outil
qui ne modifie rien — c'est un fait de nature, pas une question d'opinion,
et il se tranche sans appeler le modèle.
"""
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def free_mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionStep
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_disc_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal="créer un tableur",
    )
    yield uid, m.id
    async with async_session() as db:
        await db.execute(delete(MissionStep).where(MissionStep.mission_id == m.id))
        await db.execute(delete(Mission).where(Mission.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


def _llm_valide(reason: str):
    """L'évaluateur d'origine : il valide, parce que l'outil a répondu."""
    class _FakeLLM:
        appels = 0

        async def ainvoke(self, _payload, **_kw):
            _FakeLLM.appels += 1
            return types.SimpleNamespace(content=json.dumps({
                "success": True, "reason": reason, "all_done": False,
            }))
    _FakeLLM.appels = 0
    return _FakeLLM()


_PLAN = {
    "steps": [
        {"id": "tableur", "description": "Crée un Google Sheet nommé prospection"},
        {"id": "suite", "description": "Remplis le tableur"},
    ],
}


@pytest.mark.asyncio
async def test_find_tool_ne_valide_pas_une_etape(free_mission, monkeypatch) -> None:
    """Trouver l'outil n'est pas faire le travail."""
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    monkeypatch.setattr(
        mn, "_get_evaluator_llm",
        lambda **_kw: _llm_valide("find_tool a identifié les bons outils"),
    )

    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "créer un tableur",
        "plan_json": _PLAN, "current_step_id": "tableur",
        "last_tool_name": "find_tool",
        "last_tool_input": {"capability": "create a new Google Sheet"},
        "last_tool_output": "Outils disponibles : sheets_create_spreadsheet …",
    })

    assert out["last_eval_success"] is False, (
        "une étape ne peut pas être accomplie par un outil de découverte"
    )
    etape = out["plan_json"]["steps"][0]
    assert etape["status"] != "done", "l'étape ne doit surtout pas passer done"
    assert "découverte" in (out["last_eval_reason"] or "").lower()


@pytest.mark.asyncio
async def test_ce_verdict_ne_coute_aucun_appel_au_modele(
    free_mission, monkeypatch,
) -> None:
    """C'est un fait de nature : il se tranche sans consulter le modèle."""
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    faux = _llm_valide("peu importe")
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: faux)

    await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "créer un tableur",
        "plan_json": _PLAN, "current_step_id": "tableur",
        "last_tool_name": "find_tool", "last_tool_input": {"capability": "x"},
        "last_tool_output": "Outils disponibles : …",
    })

    assert type(faux).appels == 0


@pytest.mark.asyncio
async def test_un_outil_qui_agit_reste_juge_par_le_modele(
    free_mission, monkeypatch,
) -> None:
    """Le garde-fou vise la DÉCOUVERTE, pas la lecture ni l'action.

    `sheets_create_spreadsheet` produit un effet : son verdict appartient à
    l'évaluateur, comme avant.
    """
    import app.agent.missions.nodes as mn

    uid, mid = free_mission
    faux = _llm_valide("le tableur a bien été créé")
    monkeypatch.setattr(mn, "_get_evaluator_llm", lambda **_kw: faux)

    out = await mn.eval_node({
        "mission_id": mid, "user_id": uid, "goal": "créer un tableur",
        "plan_json": _PLAN, "current_step_id": "tableur",
        "last_tool_name": "sheets_create_spreadsheet",
        "last_tool_input": {"title": "prospection"},
        "last_tool_output": "Feuille de calcul créée : 'prospection'",
    })

    assert out["last_eval_success"] is True
    assert out["plan_json"]["steps"][0]["status"] == "done"
    assert type(faux).appels == 1, "le modèle doit bien avoir été consulté"
