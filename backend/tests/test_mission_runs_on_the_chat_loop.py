# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_runs_on_the_chat_loop.py
# @brief      Une mission libre est un chat sans humain : elle tourne sur la
#             boucle plate, garde son carnet entre deux reveils, et ses
#             budgets mordent toujours.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La mission libre tourne sur la boucle du chat (02/09/2026).

LE CONSTAT
----------
Ely avait DEUX moteurs. Le chat est une boucle plate — agent, outils, agent,
jusqu'a la reponse. Les missions avaient leur machine a etats (plan / act /
eval / replan) dont le graphe SORT apres chaque tour : chaque tick devait
reconstruire depuis SQL ce qu'une conversation aurait simplement garde.
Vingt lots de rustines n'ont pas suffi a faire aboutir une prospection.

CE QUE CES TESTS EPINGLENT
--------------------------
- une mission libre produit son livrable en tournant sur la boucle du chat ;
- le carnet de bord est la memoire entre deux reveils : le second passage
  RELIT ce que le premier a fait, et ne le refait pas ;
- les budgets (iterations, echeance) mordent AU MILIEU d'un passage : les
  outils sont refuses et le modele est somme de conclure ;
- l'arret d'urgence stoppe le passage en cours, il n'attend pas sa fin ;
- une mission STRUCTUREE (spec_yaml) garde son executeur — c'est un contrat
  que l'utilisateur ecrit, on n'y touche pas ;
- le reglage `missions_on_chat_loop` ramene l'ancien chemin.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

_BUT = "Trouve les trois imprimeries les plus proches et note-les dans un tableur."


# ── Le faux modele ───────────────────────────────────────────────────────────


def _texte_des_messages(messages) -> str:
    morceaux = []
    for m in messages or ():
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        morceaux.append(c if isinstance(c, str) else str(c))
    return "\n".join(morceaux)


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}],
    )


class _ModeleScripte:
    """Rend ses reponses dans l'ordre et garde chaque prompt recu.

    Le juge de conformite tourne sur le meme modele : on le reconnait a son
    prompt et on le laisse passer, sinon il consommerait le script.
    """

    def __init__(self, tours):
        self._tours = list(tours)
        self.prompts: list[str] = []

    def bind_tools(self, tools, **_kw):
        self.outils_lies = [getattr(t, "name", "?") for t in tools]
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        texte = _texte_des_messages(messages)
        self.prompts.append(texte)
        if "Tu vérifies qu'un travail répond à la demande" in texte:
            return AIMessage(content="CONFORME")
        if not self._tours:
            return AIMessage(content="Plus rien a faire.")
        return self._tours.pop(0)


# ── Le decor ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_bcl_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


def _branche(monkeypatch, modele, dispatch=None):
    """Le modele factice partout ou la boucle du chat en cherche un."""
    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)
    if dispatch is not None:
        import app.agent.missions.nodes as mn

        monkeypatch.setattr(mn, "dispatch_tool", dispatch)


def _dispatch_qui_marche(journal: list):
    async def _d(nom, args, _cid, _uid, **_kw):
        journal.append((nom, args, _kw.get("mission_id")))
        return f"Resultat de {nom} : trois imprimeries trouvees.", True

    return _d


# ── Le livrable ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_mission_libre_produit_son_livrable_sur_la_boucle_du_chat(
    mission, monkeypatch,
):
    uid, mid = mission
    joues: list = []
    modele = _ModeleScripte([
        _appel("web_search", query="imprimeries Lyon"),
        AIMessage(content="J'ai releve trois imprimeries et rempli le tableur."),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche(joues))

    from app.agent.missions.chat_loop import run_mission_chat_passage

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert res["done"] is True, "une mission qui conclut doit se terminer"
    assert "imprimeries" in (res["final_summary"] or "")
    # L'outil est passe par la passerelle des missions, avec l'identite de la
    # mission : c'est elle qui porte la garde du mandat.
    assert [n for n, _a, _m in joues] == ["web_search"]
    assert joues[0][2] == mid, "la passerelle doit recevoir l'identite de la mission"


@pytest.mark.asyncio
async def test_le_passage_laisse_sa_trace_en_base(mission, monkeypatch):
    """Les actions restent auditables et comptent pour le budget."""
    uid, mid = mission
    modele = _ModeleScripte([
        _appel("web_search", query="imprimeries"),
        AIMessage(content="Fait."),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    await run_mission_chat_passage(mid, uid, _BUT)

    steps = await mission_service.list_steps(mid)
    actes = [s for s in steps if s.phase == "act"]
    assert [s.tool_name for s in actes] == ["web_search"]
    m = await mission_service.get_mission(mid)
    assert m.iterations_used == 1


@pytest.mark.asyncio
async def test_la_mission_voit_tout_le_catalogue_pas_le_filtre_de_mots_cles(
    mission, monkeypatch,
):
    """Une mission n'a personne a qui dire « je n'ai pas d'outil ».

    Le filtre de mots-cles du chat ne connait ni « convertis » ni
    « transforme » ; il laissait 119 outils sur 206 injoignables (#323). Le
    passage colle donc le profil « tout le catalogue »."""
    uid, mid = mission
    from app.skills import get_skill_registry
    from app.skills.base import Skill
    from langchain_core.tools import StructuredTool

    def _faux(nom: str):
        return StructuredTool.from_function(
            func=lambda x="": "ok", name=nom, description=f"Outil de test {nom}.",
        )

    # Plus de 20 outils : en dessous, le filtre de mots-cles ne filtre rien.
    # Et un outil que l'objectif NOMME (« tableur » → sheets_) : sans lui le
    # filtre ne retiendrait rien, sa securite rendrait tout, et le test
    # passerait pour de mauvaises raisons.
    faux = [_faux(f"zzz_outil_{i:02d}") for i in range(25)]
    faux.append(_faux("sheets_ajoute_une_ligne"))
    registre = get_skill_registry()
    registre.register_or_replace(Skill(
        name="_bench_boucle_chat", display_name="B", description="B", icon="B",
        tools=faux,
    ))
    try:
        modele = _ModeleScripte([AIMessage(content="Rien a faire.")])
        _branche(monkeypatch, modele)

        from app.agent.missions.chat_loop import run_mission_chat_passage

        await run_mission_chat_passage(mid, uid, _BUT)
    finally:
        registre.unregister("_bench_boucle_chat")

    assert "zzz_outil_00" in getattr(modele, "outils_lies", []), (
        "la mission est retombee sur le filtre de mots-cles : elle ne verra "
        "pas les outils que son objectif ne nomme pas"
    )


# ── La memoire entre deux reveils ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_second_reveil_relit_ce_que_le_premier_a_fait(mission, monkeypatch):
    """Le carnet est la memoire de la mission : un passage qui reprend sait
    ce qui est FAIT sans le refaire."""
    uid, mid = mission

    from app.agent.missions.chat_loop import (
        MARQUEUR_A_SUIVRE,
        run_mission_chat_passage,
    )

    premier = _ModeleScripte([
        _appel("web_search", query="imprimeries Lyon"),
        AIMessage(content=(
            "PUBLIGIFTS releve et ajoute au tableur. Il reste deux societes "
            f"a traiter. {MARQUEUR_A_SUIVRE}"
        )),
    ])
    _branche(monkeypatch, premier, _dispatch_qui_marche([]))
    r1 = await run_mission_chat_passage(mid, uid, _BUT)
    assert r1["done"] is False, "le modele a demande un passage de plus"

    second = _ModeleScripte([
        _appel("sheets_append_row", values=["IMPRIM2"]),
        AIMessage(content="Les trois societes sont dans le tableur."),
    ])
    _branche(monkeypatch, second, _dispatch_qui_marche([]))
    r2 = await run_mission_chat_passage(mid, uid, _BUT)

    assert r2["done"] is True
    ouverture = second.prompts[0]
    assert "PUBLIGIFTS" in ouverture, (
        "le second passage n'a pas relu le carnet : il repart de zero, ce qui "
        "est exactement le defaut que ce chantier corrige"
    )
    assert "web_search" in ouverture, "le carnet doit nommer les actions faites"


@pytest.mark.asyncio
async def test_le_carnet_garde_les_passages_dates(mission, monkeypatch):
    uid, mid = mission
    from app.agent.missions.chat_loop import (
        MARQUEUR_A_SUIVRE,
        run_mission_chat_passage,
    )
    from app.services.mission_workspace import read_carnet

    modele = _ModeleScripte([
        _appel("web_search", query="x"),
        AIMessage(content=f"Une societe faite, deux restantes. {MARQUEUR_A_SUIVRE}"),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))
    await run_mission_chat_passage(mid, uid, _BUT)

    carnet = read_carnet(mid) or ""
    assert "Passages" in carnet
    assert "web_search" in carnet
    assert "deux restantes" in carnet
    assert MARQUEUR_A_SUIVRE not in carnet, (
        "le marqueur de continuation est un signal de protocole, pas une lecon"
    )


@pytest.mark.asyncio
async def test_une_mission_deja_commencee_ailleurs_ne_repart_pas_de_zero(
    mission, monkeypatch,
):
    """Le jour du deploiement, des missions tournent deja sur l'ancien moteur.

    Leur carnet est vide, mais leur trace ne l'est pas. Un premier passage qui
    ignore `mission_steps` refait ce qui est deja fait — et c'est precisement
    le defaut que ce chantier corrige."""
    uid, mid = mission
    from app.services import mission_service

    await mission_service.add_step(
        mid, phase="act", tool_name="drive_create_folder",
        tool_output="Dossier Prospection cree.", success=True,
    )
    await mission_service.add_step(
        mid, phase="act", tool_name="sheets_create_spreadsheet",
        tool_output="Tableur cree.", success=True,
    )

    modele = _ModeleScripte([AIMessage(content="Deja fait, je conclus.")])
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    ouverture = modele.prompts[0]
    assert "drive_create_folder" in ouverture and "sheets_create_spreadsheet" in ouverture, (
        "le premier passage ignore le travail deja trace : il va le refaire"
    )


# ── Souverainete : le LLM vit dans le monde des placeholders ─────────────────


@pytest.mark.asyncio
async def test_le_modele_ne_voit_pas_la_pii_mais_le_resume_la_rend(
    mission, monkeypatch,
):
    """L'invariant du chemin missions : la base et l'utilisateur vivent dans
    le monde reel, seul le LLM vit dans le monde des placeholders.

    Le chemin du chat n'anonymise pas de lui-meme (le planificateur le fait
    dans son appelant) : c'est au passage de tenir la frontiere."""
    uid, mid = mission
    but = "Ecris a jean.dupont@exemple.fr pour lui demander un devis."

    async def _dispatch(_nom, _args, _cid, _uid, **_kw):
        return "Message envoye a jean.dupont@exemple.fr.", True

    modele = _ModeleScripte([
        _appel("gmail_send_email", to="[EMAIL_0]"),
        AIMessage(content="Devis demande a [EMAIL_0]."),
    ])
    _branche(monkeypatch, modele, _dispatch)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services.mission_workspace import read_carnet

    res = await run_mission_chat_passage(mid, uid, but)

    vus = "\n".join(modele.prompts)
    assert "jean.dupont@exemple.fr" not in vus, (
        "l'adresse est partie en clair au modele : la frontiere de "
        "souverainete n'est pas tenue sur ce chemin"
    )
    assert "jean.dupont@exemple.fr" in (res["final_summary"] or ""), (
        "l'utilisateur doit recevoir la vraie valeur, pas un placeholder"
    )
    assert "[EMAIL_" not in (read_carnet(mid) or ""), (
        "aucun placeholder ne doit toucher le disque"
    )


# ── Les budgets ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_budget_d_iterations_coupe_les_outils_au_milieu_du_passage(
    mission, monkeypatch,
):
    """Un passage peut durer longtemps : le budget doit mordre DEDANS, pas
    seulement entre deux reveils."""
    uid, mid = mission
    from app.database import async_session
    from app.models.mission import Mission
    from sqlalchemy import update

    async with async_session() as db:
        await db.execute(
            update(Mission).where(Mission.id == mid).values(budget_iterations=1)
        )
        await db.commit()

    joues: list = []
    modele = _ModeleScripte([
        _appel("web_search", query="un"),
        _appel("web_search", query="deux"),
        AIMessage(content="J'arrete : plus de budget."),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche(joues))

    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    assert len(joues) == 1, "le second appel devait etre refuse, pas execute"
    refus = modele.prompts[-1] if modele.prompts else ""
    assert "budget" in refus.lower(), (
        "le modele doit APPRENDRE que le budget est epuise, pas subir un silence"
    )


@pytest.mark.asyncio
async def test_l_arret_d_urgence_stoppe_le_passage_en_cours(mission, monkeypatch):
    uid, mid = mission
    from app.services import mission_service

    joues: list = []

    async def _dispatch_puis_arret(nom, args, _cid, _uid, **_kw):
        joues.append(nom)
        await mission_service.abort_mission(mid, "test")
        return "ok", True

    modele = _ModeleScripte([
        _appel("web_search", query="un"),
        _appel("web_search", query="deux"),
        AIMessage(content="Fini."),
    ])
    _branche(monkeypatch, modele, _dispatch_puis_arret)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert joues == ["web_search"], "l'arret d'urgence n'a pas coupe le passage"
    assert res["done"] is False
    assert res.get("interrupted") is True
    m = await mission_service.get_mission(mid)
    assert m.status == "aborted", "un passage interrompu ne conclut pas la mission"


# ── Ce qu'on ne casse pas ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_mission_structuree_garde_son_executeur(mission, monkeypatch):
    """Une spec YAML est un CONTRAT ecrit par l'utilisateur : elle continue
    de passer par la machine a etats, pas par la boucle du chat."""
    uid, mid = mission
    from app.database import async_session
    from app.models.mission import Mission
    from sqlalchemy import update

    async with async_session() as db:
        await db.execute(
            update(Mission).where(Mission.id == mid).values(
                spec_yaml="version: 1\nsteps:\n  - id: a\n    do: rien\n"
            )
        )
        await db.commit()

    appels = {"graphe": 0, "chat": 0}

    async def _faux_graphe(*_a, **_k):
        appels["graphe"] += 1
        return {"iteration": 1}

    async def _fausse_boucle(*_a, **_k):
        appels["chat"] += 1
        return {"done": True, "final_summary": "x"}

    import app.services.mission_heartbeat as hb
    import app.agent.missions.chat_loop as cl

    monkeypatch.setattr(hb, "_tick_mission_graph", _faux_graphe)
    monkeypatch.setattr(cl, "run_mission_chat_passage", _fausse_boucle)

    await hb._tick_one_mission(mid, uid, _BUT)

    assert appels == {"graphe": 1, "chat": 0}


@pytest.mark.asyncio
async def test_le_reglage_ramene_l_ancien_chemin(mission, monkeypatch):
    uid, mid = mission
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MISSIONS_ON_CHAT_LOOP", "false")
    get_settings.cache_clear()

    appels = {"graphe": 0, "chat": 0}

    async def _faux_graphe(*_a, **_k):
        appels["graphe"] += 1
        return {"iteration": 1}

    async def _fausse_boucle(*_a, **_k):
        appels["chat"] += 1
        return {"done": True, "final_summary": "x"}

    import app.services.mission_heartbeat as hb
    import app.agent.missions.chat_loop as cl

    monkeypatch.setattr(hb, "_tick_mission_graph", _faux_graphe)
    monkeypatch.setattr(cl, "run_mission_chat_passage", _fausse_boucle)
    try:
        await hb._tick_one_mission(mid, uid, _BUT)
    finally:
        get_settings.cache_clear()

    assert appels == {"graphe": 1, "chat": 0}


@pytest.mark.asyncio
async def test_par_defaut_une_mission_libre_prend_la_boucle_du_chat(
    mission, monkeypatch,
):
    uid, mid = mission
    appels = {"graphe": 0, "chat": 0}

    async def _faux_graphe(*_a, **_k):
        appels["graphe"] += 1
        return {"iteration": 1}

    async def _fausse_boucle(*_a, **_k):
        appels["chat"] += 1
        return {"done": True, "final_summary": "x"}

    import app.services.mission_heartbeat as hb
    import app.agent.missions.chat_loop as cl

    monkeypatch.setattr(hb, "_tick_mission_graph", _faux_graphe)
    monkeypatch.setattr(cl, "run_mission_chat_passage", _fausse_boucle)

    await hb._tick_one_mission(mid, uid, _BUT)

    assert appels == {"graphe": 0, "chat": 1}
