# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_pose_une_question_et_attend.py
# @brief      Une mission libre peut poser une question à l'utilisateur, se
#             mettre en attente, et reprendre avec la réponse.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « RDV » du 06/09/2026 : « réserve un créneau d'une heure avec Paul ;
si plusieurs sont libres, demande-moi lequel ». La consigne des missions
disait « tu agis, tu ne demandes pas », et aucun outil ne permettait de
demander. Le modèle a planifié « demander le créneau » six fois entre les
itérations 40 et 211, a réservé sans choix, puis a tourné : 217 actions,
3,7 M tokens, 28 minutes.

Ce qui manque n'est pas l'intelligence du modèle, c'est le droit de
s'arrêter pour demander. Désormais :
- `ask_user(question)` met la mission en `waiting_user`, notifie, et arrête
  le passage — le travail déjà fait est conservé ;
- la mission n'est plus réveillée tant qu'elle attend ;
- la réponse va au carnet et à la consigne du passage suivant ; la mission
  redevient due tout de suite ;
- des écarts que la reprise ne résorbe pas deviennent une question, jamais
  un échec silencieux (évolution de #389).

Run with:  cd backend && python -m pytest tests/test_une_mission_pose_une_question_et_attend.py -v
"""
from __future__ import annotations

import sqlite3
import types
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from langchain_core.messages import AIMessage

_BUT = (
    "Réserve-moi un créneau d'une heure la semaine prochaine pour un point "
    "avec Paul ; si plusieurs créneaux sont libres, demande-moi lequel."
)
_QUESTION = "Trois créneaux libres : lundi 9 h, mardi 14 h, jeudi 10 h. Lequel ?"


def _texte(messages) -> str:
    out = []
    for m in messages or ():
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        out.append(c if isinstance(c, str) else str(c))
    return "\n".join(out)


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}],
    )


class _Modele:
    def __init__(self, tours, verdict: str = "CONFORME"):
        self._tours = list(tours)
        self.verdict = verdict
        self.vus: list[str] = []

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        texte = _texte(messages)
        self.vus.append(texte)
        if "Tu vérifies qu'un travail répond" in texte:
            return AIMessage(content=self.verdict)
        if "Réécris ta réponse" in texte:
            return AIMessage(content="Le tableur n'a pas été rempli : accès Sheets manquant.")
        if not self._tours:
            return AIMessage(content="Plus rien à faire.")
        return self._tours.pop(0)


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_ask_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="RDV", goal=_BUT, budget_iterations=30,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


def _branche(monkeypatch, modele, joues: list, notifications: list):
    """Le modèle factice partout ; `ask_user` est dispatché POUR DE VRAI
    (c'est lui qu'on teste), les autres outils sont simulés."""
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp
    from app.services import mission_questions

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)

    async def _notifier(mission_id, question):
        notifications.append((mission_id, question))

    monkeypatch.setattr(mission_questions, "notifier", _notifier)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        joues.append(nom)
        if nom == "ask_user":
            from app.agent.tool_context import CURRENT_CONVERSATION_ID
            from app.agent.tools.ask_user_tool import ask_user

            jeton = CURRENT_CONVERSATION_ID.set(_kw.get("mission_id") or "")
            try:
                return await ask_user.ainvoke(args), True
            finally:
                CURRENT_CONVERSATION_ID.reset(jeton)
        return f"Resultat de {nom}.", True

    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)


# ── L'outil ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_user_met_la_mission_en_attente_et_arrete_le_passage(mission, monkeypatch):
    uid, mid = mission
    joues: list = []
    notifs: list = []
    modele = _Modele([
        _appel("calendar_check_availability", week="next"),
        _appel("ask_user", question=_QUESTION),
        _appel("calendar_create_event", title="Point avec Paul"),  # ne doit PAS tourner
        AIMessage(content="Créneau réservé."),
    ])
    _branche(monkeypatch, modele, joues, notifs)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert res["done"] is False and res["failed"] is False
    assert res.get("waiting_user") is True
    assert "calendar_create_event" not in joues, "le passage doit s'arrêter sur la question"
    m = await mission_service.get_mission(mid)
    assert m.status == "waiting_user"
    assert "Lequel" in (m.pending_question or "")
    assert m.question_asked_at is not None
    assert notifs == [(mid, _QUESTION)]
    from app.services.mission_workspace import read_carnet
    carnet = read_carnet(mid) or ""
    assert "calendar_check_availability ✓" in carnet, "le travail déjà fait est consigné"
    assert _QUESTION in carnet


@pytest.mark.asyncio
async def test_ask_user_hors_mission_dit_de_poser_la_question_directement():
    from app.agent.tool_context import CURRENT_CONVERSATION_ID
    from app.agent.tools.ask_user_tool import ask_user

    jeton = CURRENT_CONVERSATION_ID.set(f"conv-chat-{uuid.uuid4().hex[:6]}")
    try:
        texte = await ask_user.ainvoke({"question": "Lequel ?"})
    finally:
        CURRENT_CONVERSATION_ID.reset(jeton)
    assert "directement" in texte.lower()


def test_ask_user_est_un_outil_de_mission_qui_ne_demande_pas_d_accord():
    from app.agent.missions.outillage import NOYAU_MISSION
    from app.agent.tool_nature import requires_approval

    assert "ask_user" in NOYAU_MISSION, "il doit être branché quelle que soit la famille choisie"
    assert requires_approval("ask_user") is False


# ── L'attente, puis la réponse ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_mission_en_attente_n_est_pas_reveillee(mission):
    uid, mid = mission
    from app.database import async_session
    from app.models.mission import Mission
    from app.services import mission_questions, mission_service
    from sqlalchemy import update

    await mission_questions.poser(mid, _QUESTION)
    async with async_session() as db:
        await db.execute(update(Mission).where(Mission.id == mid).values(
            next_tick_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        ))
        await db.commit()

    dues = [m.id for m in await mission_service.list_due_missions()]
    assert mid not in dues


@pytest.mark.asyncio
async def test_repondre_relance_la_mission_avec_la_reponse_au_carnet(mission, monkeypatch):
    uid, mid = mission
    from app.services import mission_questions, mission_service
    from app.services.mission_workspace import read_carnet

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(mission_questions, "notifier", _rien)
    await mission_questions.poser(mid, _QUESTION)

    m = await mission_questions.repondre(mid, "mardi 14 h")

    assert m.status == "running"
    assert m.pending_question is None
    assert m.next_tick_at is not None, "la mission redevient due tout de suite"
    carnet = read_carnet(mid) or ""
    assert _QUESTION in carnet and "mardi 14 h" in carnet


@pytest.mark.asyncio
async def test_le_passage_suivant_lit_la_reponse_dans_sa_consigne(mission, monkeypatch):
    uid, mid = mission
    joues: list = []
    modele = _Modele([AIMessage(content="Créneau de mardi 14 h réservé et relu.")])
    _branche(monkeypatch, modele, joues, [])
    from app.services import mission_questions

    await mission_questions.poser(mid, _QUESTION)
    await mission_questions.repondre(mid, "mardi 14 h")

    from app.agent.missions.chat_loop import run_mission_chat_passage

    await run_mission_chat_passage(mid, uid, _BUT)

    premiere_consigne = modele.vus[0]
    assert "mardi 14 h" in premiere_consigne
    assert _QUESTION in premiere_consigne


@pytest.mark.asyncio
async def test_repondre_refuse_une_mission_qui_n_attend_rien(mission):
    uid, mid = mission
    from app.services import mission_questions

    with pytest.raises(ValueError):
        await mission_questions.repondre(mid, "mardi 14 h")


@pytest.mark.asyncio
async def test_l_utilisateur_repond_par_l_api(mission, monkeypatch):
    uid, mid = mission
    from app.routers.missions import AnswerBody, answer_question
    from app.services import mission_questions

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(mission_questions, "notifier", _rien)
    await mission_questions.poser(mid, _QUESTION)

    out = await answer_question(mid, AnswerBody(answer="mardi 14 h"),
                                current_user=SimpleNamespace(id=uid))
    assert out.status == "running"
    assert out.pending_question is None

    with pytest.raises(HTTPException) as exc:
        await answer_question(mid, AnswerBody(answer="encore"),
                              current_user=SimpleNamespace(id=uid))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_une_mission_en_attente_peut_etre_abandonnee(mission, monkeypatch):
    uid, mid = mission
    from app.services import mission_questions, mission_service

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(mission_questions, "notifier", _rien)
    await mission_questions.poser(mid, _QUESTION)
    m = await mission_service.abort_mission(mid, "plus besoin")
    assert m.status == "aborted"


# ── Les écarts non résorbés deviennent une question ──────────────────────────


@pytest.mark.asyncio
async def test_des_ecarts_non_resolus_deviennent_une_question(mission, monkeypatch):
    uid, mid = mission
    notifs: list = []
    aveu = "Je ne peux pas remplir le tableur, il reste tout le travail à faire."
    modele = _Modele(
        [AIMessage(content=aveu), AIMessage(content=aveu)],
        verdict="ÉCARTS:\n- le tableur n'a pas été rempli : aucune ligne écrite",
    )
    _branche(monkeypatch, modele, [], notifs)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert res["failed"] is False and res["done"] is False
    assert res.get("waiting_user") is True
    m = await mission_service.get_mission(mid)
    assert m.status == "waiting_user"
    assert "tableur" in (m.pending_question or "").lower()
    assert len(notifs) == 1


# ── La consigne ──────────────────────────────────────────────────────────────


def test_la_consigne_dit_de_demander_plutot_que_de_deviner():
    from app.agent.missions.chat_loop import _consigne

    texte = _consigne(_BUT, "")
    assert "ask_user" in texte
    assert "tu ne demandes pas" not in texte


def test_le_bloc_d_execution_automatique_distingue_mission_et_tache():
    from app.agent.nodes import bloc_execution_automatique

    tache = bloc_execution_automatique(mission_passage=False)
    mission = bloc_execution_automatique(mission_passage=True)
    assert "NE pose AUCUNE question" in tache
    assert "ask_user" in mission
    assert "NE pose AUCUNE question" not in mission


# ── La migration ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_0037_ajoute_la_question_en_attente(tmp_path, monkeypatch):
    import app.config as app_config
    from app.services import alembic_runner as ar

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        app_config, "get_settings",
        lambda: types.SimpleNamespace(database_url=f"sqlite+aiosqlite:///{db_path}"),
    )
    await ar.ensure_migrations()

    check = sqlite3.connect(db_path)
    cols = {r[1] for r in check.execute("PRAGMA table_info(missions)")}
    check.close()
    assert {"pending_question", "question_asked_at"} <= cols


@pytest.mark.asyncio
async def test_une_question_en_dernier_appel_arrete_aussi_le_passage(mission, monkeypatch):
    """Sans outil après la question, le graphe rend la main au modèle, qui
    conclut : sans arrêt explicite, le passage se croyait terminé."""
    uid, mid = mission
    joues: list = []
    modele = _Modele([
        _appel("ask_user", question=_QUESTION),
        AIMessage(content="Créneau réservé, mission terminée."),
    ])
    _branche(monkeypatch, modele, joues, [])

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert res["done"] is False
    assert res.get("waiting_user") is True
    assert (await mission_service.get_mission(mid)).status == "waiting_user"
