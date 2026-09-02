# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_passage_ne_perd_ni_trace_ni_cout.py
# @brief      Relecture adverse du lot « la mission est le chat sans humain »
#             (02/09/2026) : un passage qui plante consigne quand meme ce
#             qu'il a fait, il journalise son cout, il compte ses tokens sans
#             usage_metadata, et son prompt systeme ne part pas en clair.
# @license    Elastic License 2.0
# =============================================================================
"""Ce qu'un passage de mission ne doit JAMAIS perdre en route (02/09/2026).

QUATRE DEFAUTS RELEVES SUR `app/agent/missions/chat_loop.py`
-----------------------------------------------------------
1. Le passage ne rattrapait que `MissionInterrompue`. Un 429 du fournisseur,
   un timeout, un 504 traversaient la fonction et SAUTAIENT l'ecriture du
   carnet. Or `_process_one_mission` REPORTE le tick sur ces erreurs-la : la
   mission se reveille avec un carnet arrete au passage precedent, et refait
   ce qu'elle a deja fait — le defaut meme que ce lot existe pour corriger.
2. Le passage n'ecrivait AUCUNE ligne `usage_logs` : le cout LLM des missions
   disparaissait du tableau de bord et du garde-fou de budget quotidien.
3. Le prompt SYSTEME (instantane memoire : profil, preferences, contraintes,
   souvenirs) est monte dans `agent_node` et part AU MODELE EN CLAIR. Seuls
   la consigne et les `ToolMessage` passaient par `mission_filter`. Le tier
   COMPLEX est cloud par defaut (`zhipu`, `anthropic`, `gemini`).
4. `_tokens_des_messages` rendait 0 quand le fournisseur ne renvoie pas
   d'`usage_metadata` (LM Studio en flux) : `Mission.tokens_used` restait a 0
   pour toujours et la clause tokens du budget ne pouvait plus mordre.
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

    Une reponse qui EST une exception est levee au lieu d'etre rendue : c'est
    ainsi qu'on simule le 429 du fournisseur au milieu d'un passage.
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
        tour = self._tours.pop(0)
        if isinstance(tour, BaseException):
            raise tour
        return tour


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_pas_{uuid.uuid4().hex[:8]}"
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


# ── 1. Le carnet survit au crash ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_passage_qui_plante_consigne_quand_meme_ce_qu_il_a_fait(
    mission, monkeypatch,
):
    """Le 429 du fournisseur REPORTE le tick, il ne tue pas la mission.

    Si le carnet n'est pas ecrit sur ce chemin, le reveil suivant repart du
    passage precedent et rejoue les actions deja faites."""
    uid, mid = mission
    joues: list = []
    modele = _ModeleScripte([
        _appel("drive_create_folder", name="Prospection"),
        RuntimeError("Provider returned error, code 429"),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche(joues))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services.mission_workspace import read_carnet

    with pytest.raises(RuntimeError, match="429"):
        await run_mission_chat_passage(mid, uid, _BUT)

    assert [n for n, _a, _m in joues] == ["drive_create_folder"]
    carnet = read_carnet(mid) or ""
    assert "drive_create_folder" in carnet, (
        "le passage a cree le dossier puis plante : sans cette ligne au "
        "carnet, le reveil suivant le recreera"
    )
    assert "INTERROMPU" in carnet, "la ligne doit DIRE que le passage a ete coupe"
    assert "429" in carnet, "et POURQUOI il a ete coupe"


@pytest.mark.asyncio
async def test_le_passage_releve_l_exception_pour_que_le_tick_soit_reporte(
    mission, monkeypatch,
):
    """Consigner ne doit pas avaler : `_process_one_mission` a besoin de
    l'exception pour reconnaitre une panne passagere et reporter le tick."""
    uid, mid = mission
    modele = _ModeleScripte([TimeoutError("gateway timeout")])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage

    with pytest.raises(TimeoutError):
        await run_mission_chat_passage(mid, uid, _BUT)


# ── 2. Le cout du passage est journalise ─────────────────────────────────────


@pytest.mark.asyncio
async def test_le_passage_ecrit_une_ligne_d_usage_attribuee_a_la_mission(
    mission, monkeypatch,
):
    """Sans ligne `usage_logs`, le cout LLM des missions n'existe ni au
    tableau de bord ni pour le garde-fou de budget quotidien du user."""
    uid, mid = mission
    modele = _ModeleScripte([
        _appel("web_search", query="imprimeries"),
        AIMessage(content="Trois imprimeries relevees."),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from sqlalchemy import select

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.database import async_session
    from app.models.usage_log import UsageLog

    await run_mission_chat_passage(mid, uid, _BUT)

    async with async_session() as db:
        lignes = (await db.execute(
            select(UsageLog).where(UsageLog.user_id == uid)
        )).scalars().all()

    assert lignes, "le passage n'a laisse aucune trace de cout"
    assert any(row.conversation_id == mid for row in lignes), (
        "la ligne d'usage doit porter l'identite de la mission"
    )
    assert any((row.channel or "") == "mission" for row in lignes), (
        "le tableau de bord ventile par canal : une mission n'est pas du web"
    )


# ── 3. La frontiere de souverainete tient sur le prompt SYSTEME ──────────────


@pytest.mark.asyncio
async def test_l_instantane_memoire_ne_part_pas_en_clair_au_modele(
    mission, monkeypatch,
):
    """Le prompt systeme porte le profil, les preferences et les souvenirs.

    Il est monte DANS `agent_node`, pas dans la consigne : il echappait au
    `mission_filter`. Le tier COMPLEX est cloud par defaut."""
    uid, mid = mission

    async def _instantane(**_kw):
        return (
            "🧠 Profil : le contact principal est jean.dupont@exemple.fr, "
            "joignable au 06 12 34 56 78.\n",
            None,
        )

    import app.agent.builders.memory_snapshot as ms

    monkeypatch.setattr(ms, "build_memory_snapshot", _instantane)

    modele = _ModeleScripte([AIMessage(content="Rien a faire.")])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    vus = "\n".join(modele.prompts)
    assert "jean.dupont@exemple.fr" not in vus, (
        "l'instantane memoire est parti EN CLAIR dans le prompt systeme : la "
        "frontiere de souverainete n'est pas tenue sur ce chemin"
    )
    assert "06 12 34 56 78" not in vus, (
        "meme constat pour le telephone du profil"
    )
    assert "[EMAIL_" in vus, (
        "le modele doit recevoir le placeholder, pas un profil ampute : "
        "l'anonymisation remplace, elle ne supprime pas"
    )


# ── 4. Les tokens se comptent meme sans usage_metadata ───────────────────────


@pytest.mark.asyncio
async def test_les_tokens_se_comptent_meme_quand_le_fournisseur_se_tait(
    mission, monkeypatch,
):
    """LM Studio en flux ne renvoie pas d'`usage_metadata`.

    Sans repli, `Mission.tokens_used` reste a 0 pour toujours et la clause
    tokens du budget de la mission ne peut plus jamais mordre."""
    uid, mid = mission
    modele = _ModeleScripte([
        _appel("web_search", query="imprimeries"),
        AIMessage(content="Trois imprimeries relevees, tableur rempli."),
    ])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    await run_mission_chat_passage(mid, uid, _BUT)

    m = await mission_service.get_mission(mid)
    assert (m.tokens_used or 0) > 0, (
        "aucun message ne portait d'usage_metadata : le passage a compte "
        "zero token, donc le budget de tokens ne mordra jamais"
    )


@pytest.mark.asyncio
async def test_le_repli_ne_recouvre_pas_la_mesure_du_fournisseur(
    mission, monkeypatch,
):
    """Un repli qui remplacerait la mesure serait pire que le trou."""
    uid, mid = mission
    reponse = AIMessage(content="Fait.")
    reponse.usage_metadata = {
        "input_tokens": 900, "output_tokens": 100, "total_tokens": 1000,
    }
    modele = _ModeleScripte([reponse])
    _branche(monkeypatch, modele, _dispatch_qui_marche([]))

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    await run_mission_chat_passage(mid, uid, _BUT)

    m = await mission_service.get_mission(mid)
    assert (m.tokens_used or 0) == 1000, (
        "quand le fournisseur mesure, c'est SA mesure qui compte"
    )
