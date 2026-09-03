# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_actor_chains_actions_in_a_tick.py
# @brief      L'acteur enchaîne ses appels d'outils dans le tick, relit
#             leurs résultats, et conclut l'étape en texte.
# @license    MIT
# =============================================================================
"""L'acteur ne voyait jamais ce qu'il venait de faire (31/08/2026).

LA TRACE
--------
Mission « Prospection LKDN », troisième société :

    it26  browser_open_tab      → « appeler browser_tab_wait_loaded avant de lire »
    it28  browser_open_tab      ← il rouvre, au lieu d'attendre
    it30  browser_open_tab      ← et encore
    it32  browser_open_tab      ← refusé par le garde-fou, étape abandonnée

Chaque tick ne jouait qu'UN appel d'outil, puis le graphe sortait. Au tour
suivant l'acteur repartait d'un prompt reconstruit depuis la base — sans le
fil de ce qu'il venait de faire. Ely réinventait tour après tour un canal
de plus (`_ACT_RETOUR`, `_foreach_outcomes`, `_item_tag`…) pour lui redire
ce qu'une simple conversation lui aurait laissé.

LA RÈGLE
--------
Hermes tient un seul fil : le modèle appelle un outil, reçoit son résultat
dans le même échange, enchaîne, et s'arrête en répondant en texte. C'est ce
que fait désormais `act_node` dans les bornes d'UN tick :

- une action à la fois, son résultat relu avant la suivante ;
- un appel identique à un appel déjà joué dans ce tick arrête la boucle
  (l'évaluateur tranche, on ne rejoue pas ce qui n'apprend rien) ;
- la boucle est bornée par `MAX_ACTIONS_PER_TICK` ;
- une réponse en texte après au moins une action est la conclusion de
  l'étape : elle est transmise à l'évaluateur, qui en dérive `step_result`.

Le premier tour reste soumis à la règle historique : sans appel d'outil ni
cas particulier, c'est un échec de sélection (repli sur les modèles de
secours). Une étape ne se conclut pas sans avoir agi.
"""
from __future__ import annotations

import json
import types
import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def mission():
    from sqlalchemy import delete

    from app.database import async_session, init_db
    from app.models.mission import Mission, MissionPlan, MissionStep, MissionStepRun
    from app.models.user import User
    from app.services import mission_service

    await init_db()
    uid = f"test_chaine_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Chaîne", goal="relever les décideurs",
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


def _plan() -> dict:
    return {"steps": [
        {"id": "contacts",
         "description": "Ouvre la recherche LinkedIn, lis la page, ajoute les contacts."},
    ]}


def _appel(nom: str, **args) -> dict:
    return {"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}


def _outil(nom: str, **args):
    return types.SimpleNamespace(content="", tool_calls=[_appel(nom, **args)])


def _texte(t: str):
    return types.SimpleNamespace(content=t, tool_calls=[])


class _ActeurScripte:
    """Rend ses réponses dans l'ordre, et garde chaque prompt reçu."""

    def __init__(self, reponses, *, boucle_sur_la_derniere=False):
        self.reponses = list(reponses)
        self.recus: list[list] = []
        self.boucle = boucle_sur_la_derniere

    async def ainvoke(self, messages, **_kw):
        self.recus.append(list(messages))
        if len(self.reponses) > 1 or not self.boucle:
            return self.reponses.pop(0)
        return self.reponses[0]


async def _tick(mn, mid, uid, acteur, dispatch, **etat):
    """Un passage dans act_node avec l'acteur et le dispatch fournis."""
    async def _llms(**_kw):
        return acteur, [], []

    originaux = (mn._get_actor_llms, mn.dispatch_tool)
    mn._get_actor_llms, mn.dispatch_tool = _llms, dispatch
    try:
        return await mn.act_node({
            "mission_id": mid, "user_id": uid, "goal": "relever les décideurs",
            "plan_json": _plan(), "plan_text": "# Plan", **etat,
        })
    finally:
        mn._get_actor_llms, mn.dispatch_tool = originaux


def _dispatch_qui_note(journal: list, sorties: dict | None = None):
    async def _d(tool_name, tool_args, *_a, **_kw):
        journal.append((tool_name, dict(tool_args)))
        return (sorties or {}).get(tool_name, f"{tool_name} : ok"), True
    return _d


async def _lignes_act(mid: str) -> list:
    from app.services import mission_service
    return [s for s in await mission_service.list_steps(mid) if s.phase == "act"]


# ── La chaîne ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_l_acteur_enchaine_ses_actions_dans_le_tick(mission) -> None:
    """Ouvrir, lire, conclure : trois tours de l'acteur, UN tick."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    journal: list = []
    acteur = _ActeurScripte([
        _outil("browser_open_tab", url="https://www.linkedin.com/search"),
        _outil("browser_tab_read_text", tab_id=7),
        _texte("2 profils relevés : Anne Martin (DG), Paul Roux (marketing)"),
    ])
    sorties = {"browser_open_tab": "Nouvel onglet ouvert : tab_id 7",
               "browser_tab_read_text": "Anne Martin — DG\nPaul Roux — marketing"}

    etat = await _tick(mn, mid, uid, acteur, _dispatch_qui_note(journal, sorties))

    assert [n for n, _ in journal] == ["browser_open_tab", "browser_tab_read_text"]
    assert len(await _lignes_act(mid)) == 2, "chaque action laisse sa ligne de trace"
    assert etat["last_tool_name"] == "browser_tab_read_text"
    assert etat["last_tool_output"] == sorties["browser_tab_read_text"]
    assert etat["actor_final_text"].startswith("2 profils relevés")
    assert [a["tool"] for a in etat["tick_actions"]] == [
        "browser_open_tab", "browser_tab_read_text",
    ]


@pytest.mark.asyncio
async def test_le_resultat_d_un_outil_est_relu_au_tour_suivant(mission) -> None:
    """C'est tout l'objet : le second tour voit ce que le premier a rendu."""
    from langchain_core.messages import ToolMessage

    import app.agent.missions.nodes as mn

    uid, mid = mission
    acteur = _ActeurScripte([
        _outil("browser_open_tab", url="https://www.linkedin.com/search"),
        _texte("fait"),
    ])
    sorties = {"browser_open_tab": "Nouvel onglet ouvert : tab_id 7"}

    await _tick(mn, mid, uid, acteur, _dispatch_qui_note([], sorties))

    assert len(acteur.recus) == 2
    second_tour = acteur.recus[1]
    retours = [m for m in second_tour if isinstance(m, ToolMessage)]
    assert retours and "tab_id 7" in str(retours[-1].content)


@pytest.mark.asyncio
async def test_un_appel_identique_dans_le_meme_tick_n_est_pas_rejoue(mission) -> None:
    """Rouvrir le même onglet n'apprend rien : la boucle s'arrête, l'évaluateur tranche."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    journal: list = []
    acteur = _ActeurScripte(
        [_outil("browser_open_tab", url="https://www.linkedin.com/search")],
        boucle_sur_la_derniere=True,
    )

    etat = await _tick(mn, mid, uid, acteur, _dispatch_qui_note(journal))

    assert len(journal) == 1
    assert len(await _lignes_act(mid)) == 1
    assert etat["last_tool_name"] == "browser_open_tab"
    assert not etat.get("actor_final_text")


@pytest.mark.asyncio
async def test_la_boucle_est_bornee(mission) -> None:
    """Un acteur qui trouve toujours un nouvel appel s'arrête à la borne."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    journal: list = []

    class _Infini:
        def __init__(self):
            self.n = 0
            self.recus = []

        async def ainvoke(self, messages, **_kw):
            self.n += 1
            self.recus.append(messages)
            return _outil("browser_tab_read_text", tab_id=self.n)

    etat = await _tick(mn, mid, uid, _Infini(), _dispatch_qui_note(journal))

    assert len(journal) == mn.MAX_ACTIONS_PER_TICK
    assert len(etat["tick_actions"]) == mn.MAX_ACTIONS_PER_TICK


@pytest.mark.asyncio
async def test_un_outil_reclame_est_lie_dans_le_meme_tick(mission) -> None:
    """Après `find_tool`, les outils sont reliés AVANT le tour suivant, pas au tick d'après."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    liaisons: list[int] = []
    acteur = _ActeurScripte([
        _outil("find_tool", capability="ajouter des lignes à un tableur"),
        _outil("sheets_append_rows", spreadsheet_id="s1", rows=[["a"]]),
        _texte("ligne ajoutée"),
    ])

    async def _llms(**_kw):
        liaisons.append(1)
        return acteur, [], []

    async def _d(tool_name, *_a, **_kw):
        return f"{tool_name} : ok", True

    originaux = (mn._get_actor_llms, mn.dispatch_tool)
    mn._get_actor_llms, mn.dispatch_tool = _llms, _d
    try:
        await mn.act_node({
            "mission_id": mid, "user_id": uid, "goal": "relever",
            "plan_json": _plan(), "plan_text": "# Plan",
        })
    finally:
        mn._get_actor_llms, mn.dispatch_tool = originaux

    assert len(liaisons) == 2, "une liaison au départ, une après la découverte"


@pytest.mark.asyncio
async def test_le_premier_tour_sans_outil_reste_un_echec_de_selection(mission) -> None:
    """Pin : une étape ne se conclut pas sans avoir agi."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    acteur = _ActeurScripte([_texte("je pense que c'est fait")])

    etat = await _tick(mn, mid, uid, acteur, _dispatch_qui_note([]))

    assert etat["last_eval_success"] is False
    assert "Aucun outil" in etat["last_eval_reason"]
    assert not etat.get("actor_final_text")


# ── L'évaluateur voit le tour entier ───────────────────────────────────


@pytest.mark.asyncio
async def test_l_evaluateur_voit_les_actions_du_tour_et_la_conclusion(mission) -> None:
    """Il juge l'ÉTAPE : les actions jouées et ce que l'acteur en conclut."""
    import app.agent.missions.nodes as mn

    uid, mid = mission
    vu: dict = {}

    class _Juge:
        async def ainvoke(self, messages, **_kw):
            vu["prompt"] = "\n".join(str(getattr(m, "content", m)) for m in messages)
            return types.SimpleNamespace(content=json.dumps({
                "success": True, "reason": "fait", "all_done": False,
                "step_result": "Anne Martin ; Paul Roux",
            }))

    original = mn._get_evaluator_llm
    mn._get_evaluator_llm = lambda **_kw: _Juge()
    try:
        await mn.eval_node({
            "mission_id": mid, "user_id": uid, "goal": "relever les décideurs",
            "plan_json": _plan(), "current_step_id": "contacts",
            "last_tool_name": "sheets_append_rows",
            "last_tool_input": {"rows": [["Anne"], ["Paul"]]},
            "last_tool_output": "2 ligne(s) ajoutée(s)",
            "tick_actions": [
                {"tool": "browser_open_tab", "ok": True},
                {"tool": "browser_tab_read_text", "ok": True},
                {"tool": "sheets_append_rows", "ok": True},
            ],
            "actor_final_text": "2 contacts ajoutés au tableur",
        })
    finally:
        mn._get_evaluator_llm = original

    prompt = vu["prompt"]
    assert "browser_open_tab" in prompt and "browser_tab_read_text" in prompt
    assert "2 contacts ajoutés au tableur" in prompt
