# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_step_output_is_the_result.py
# @brief      `{{ etape.output }}` doit porter le RESULTAT de l'etape, pas la
#             sortie brute de l'outil qu'elle a employe.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La sortie d'une étape n'est pas la sortie de son outil (30/08/2026).

L'INCIDENT
----------
Mission « Prospection Print LinkedIn », étape `societes` :

    Cherche sur Calaméo (requête site:calameo.com) des catalogues de sociétés
    de négoce. [...] Rends une liste de 5 noms de sociétés, une par ligne, en
    excluant celles déjà présentes dans l'historique.

Ce qui a été archivé comme sortie de l'étape :

    Résultats Google [SearXNG] pour « site:calameo.com catalogue société
    négoce » (10 résultats) :
    1. CATALOGUE PARTICULIERS GEDIBOIS CCB 2026 - Calaméo
       https://www.calameo.com/books/0061304688673e9209636
    2. Catalogue Novapierre 2026 - Calaméo
    [...]

Des titres de catalogues, pas des noms de sociétés. L'étape `contacts` itère
sur `{{ societes.output }}` : l'expansion a reçu 2 691 caractères de ce dump
et a répondu `[]`. Zéro contact, tableur vide — trois jours de suite.

LA CAUSE
--------
``eval_node`` archivait ``output=state.get("last_tool_output")``. La sortie
d'une étape était, par construction, la sortie brute de son dernier outil.
Toute la moitié « et rends ceci » d'une étape — extraire, filtrer, mettre en
forme, exclure ce qui est déjà connu — n'avait nulle part où exister : un
tour sans appel d'outil est compté comme un échec, et le texte du modèle
part dans la colonne `thought`, que personne ne relit.

LE CORRECTIF
------------
L'évaluateur voit déjà l'étape et la sortie de l'outil, et il est déjà
appelé à chaque tour. Il rend désormais aussi `step_result` : ce que l'étape
SUIVANTE doit voir. Vide quand la sortie brute est déjà la réponse.

Et il le rend en voyant ce qui sera archivé : sa vue de la sortie d'outil
était coupée à 2 000 caractères quand l'archive en garde 6 000. On ne
résume pas fidèlement ce qu'on ne nous a pas montré — la sortie de `societes`
faisait 2 691 caractères.
"""
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio

_DUMP_OUTIL = (
    "Résultats Google [SearXNG] (10 résultats) :\n"
    "1. CATALOGUE PARTICULIERS GEDIBOIS CCB 2026 - Calaméo\n"
    "   https://www.calameo.com/books/0061304688673e9209636\n"
    "2. Catalogue Novapierre 2026 - Calaméo\n"
)
_RESULTAT_ATTENDU = "GEDIBOIS\nNovapierre"


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import (
        Mission, MissionPlan, MissionStep, MissionStepRun,
    )
    from app.models.user import User
    from app.services import mission_service
    from app.services.alembic_runner import ensure_migrations

    await init_db()
    await ensure_migrations()
    uid = f"test_sortie_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Sortie", goal="prospecter",
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


def _llm(journal: dict, **verdict):
    class _LLM:
        async def ainvoke(self, messages, **_kw):
            journal["prompt"] = "\n".join(
                str(getattr(m, "content", m)) for m in (messages or ())
            )
            return types.SimpleNamespace(content=json.dumps(verdict))

    return _LLM()


def _plan() -> dict:
    return {
        "from_spec": True,
        "steps": [{
            "id": "societes",
            "description": (
                "Cherche des catalogues de sociétés de négoce. Rends une "
                "liste de 5 noms de sociétés, une par ligne."
            ),
            "handlers": {},
        }],
    }


def _etat(mid: str, uid: str, sortie: str = _DUMP_OUTIL) -> dict:
    return {
        "mission_id": mid, "user_id": uid, "goal": "prospecter",
        "plan_json": _plan(), "current_step_id": "societes",
        "current_item_index": 0,
        "last_tool_name": "web_search",
        "last_tool_input": {"query": "site:calameo.com négoce"},
        "last_tool_output": sortie,
    }


async def _run_eval(mn, msr, mid, uid, **verdict) -> tuple[str, dict]:
    await msr.ensure_step_run(mid, "societes", 0, None)
    journal: dict = {}
    original = mn._get_evaluator_llm
    mn._get_evaluator_llm = lambda **_kw: _llm(journal, **verdict)
    try:
        await mn.eval_node(_etat(mid, uid))
    finally:
        mn._get_evaluator_llm = original
    run = (await msr.list_step_runs(mid, "societes"))[0]
    return run.output or "", journal


# ── Le contrat ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_sortie_archivee_est_le_resultat_de_l_etape(mission) -> None:
    """`{{ societes.output }}` doit donner les noms, pas le dump SearXNG."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    sortie, _ = await _run_eval(
        mn, msr, mid, uid,
        success=True, reason="cinq sociétés retenues",
        step_result=_RESULTAT_ATTENDU, all_done=False,
    )

    assert sortie == _RESULTAT_ATTENDU, (
        "l'étape suivante itère là-dessus : lui passer le dump de l'outil, "
        "c'est lui demander de deviner"
    )
    assert "SearXNG" not in sortie


@pytest.mark.asyncio
async def test_sans_resultat_declare_on_garde_la_sortie_de_l_outil(
    mission,
) -> None:
    """La plupart des étapes n'ont rien à reformuler — et un modèle qui
    ignore le champ ne doit rien casser."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    sortie, _ = await _run_eval(
        mn, msr, mid, uid, success=True, reason="fait", all_done=False,
    )
    assert sortie == _DUMP_OUTIL


@pytest.mark.asyncio
async def test_un_resultat_vide_ne_remplace_rien(mission) -> None:
    """Garde-fou : un `step_result` vide n'efface pas la sortie de l'outil."""
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    sortie, _ = await _run_eval(
        mn, msr, mid, uid,
        success=True, reason="fait", step_result="   ", all_done=False,
    )
    assert sortie == _DUMP_OUTIL


# ── Ce que l'évaluateur a le droit de voir ──────────────────────────────


@pytest.mark.asyncio
async def test_l_evaluateur_voit_autant_que_ce_qui_sera_archive(
    mission,
) -> None:
    """Sa vue était coupée à 2 000 car, l'archive en garde 6 000.

    La sortie de `societes` faisait 2 691 caractères : le modèle devait
    résumer une liste dont on lui avait caché le dernier quart.
    """
    import app.agent.missions.nodes as mn
    from app.services import mission_spec_runtime as msr

    uid, mid = mission
    longue = "".join(f"{i:04d} société Machin numéro {i}\n" for i in range(200))
    assert len(longue) > 2000

    await msr.ensure_step_run(mid, "societes", 0, None)
    journal: dict = {}
    original = mn._get_evaluator_llm
    mn._get_evaluator_llm = lambda **_kw: _llm(
        journal, success=True, reason="ok", all_done=False,
    )
    try:
        await mn.eval_node(_etat(mid, uid, sortie=longue))
    finally:
        mn._get_evaluator_llm = original

    vu = journal["prompt"]
    assert longue[:msr.STEP_OUTPUT_ARCHIVE_CHARS] in vu, (
        "on ne résume pas fidèlement ce qu'on ne nous a pas montré"
    )


def test_le_prompt_demande_le_resultat_de_l_etape() -> None:
    import app.agent.missions.nodes as mn

    assert '"step_result"' in mn._EVAL_SYSTEM
