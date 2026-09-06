# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_ne_se_conclut_pas_sur_sa_parole.py
# @brief      Audit GPT-6 F01 (06/09/2026) : une mission dont les exigences
#             ne sont pas satisfaites ne peut pas finir « completed ».
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le protocole de clôture était négatif : sans `[MISSION_A_SUIVRE]`, le
passage valait conclusion. Reproduit par l'audit : un modèle qui écrit « je
ne peux pas remplir le tableur, il reste tout le travail à faire », sans un
seul appel d'outil, rendait `done=True` — et le heartbeat clôturait la
mission « completed » sur cette phrase. Le juge de conformité ne tournait
même pas : il exigeait un retour d'outil à juger.

Deux règles désormais :
- un passage de mission est TOUJOURS jugé, même sans retour d'outil — sa
  réponse finale est confrontée à l'objectif ;
- des écarts que la reprise n'a pas résorbés ferment la mission en ÉCHEC,
  avec les écarts pour raison. Jamais « completed » sur la parole du modèle.

Run with:  cd backend && python -m pytest tests/test_une_mission_ne_se_conclut_pas_sur_sa_parole.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage

_BUT = "Trouve les trois imprimeries les plus proches et note-les dans un tableur."
_ECARTS = "ÉCARTS:\n- le tableur n'a pas été rempli : aucune ligne écrite"


def _texte(messages) -> str:
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


class _ModeleEtJuge:
    """Le même objet sert d'agent (tours scriptés) et de juge (verdict fixe).

    `get_llm_for_tier` est monkeypatché partout : le juge, le rapport
    d'écarts et l'agent reçoivent cette instance."""

    def __init__(self, tours, verdict: str):
        self._tours = list(tours)
        self.verdict = verdict
        self.verdicts_rendus = 0

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        texte = _texte(messages)
        if "Tu vérifies qu'un travail répond" in texte:
            self.verdicts_rendus += 1
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
    uid = f"test_f01_{uuid.uuid4().hex[:8]}"
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


def _branche(monkeypatch, modele):
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return f"Resultat de {nom} : trois imprimeries trouvees.", True

    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)


@pytest.mark.asyncio
async def test_une_mission_qui_n_a_rien_fait_ne_se_conclut_pas_sur_sa_parole(
    mission, monkeypatch,
):
    """La reproduction de l'audit : zéro action, un aveu d'inachèvement, et la
    mission finissait « completed »."""
    uid, mid = mission
    aveu = "Je ne peux pas remplir le tableur, il reste tout le travail à faire."
    modele = _ModeleEtJuge([AIMessage(content=aveu), AIMessage(content=aveu)], _ECARTS)
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert modele.verdicts_rendus >= 1, "un passage sans outil doit quand même être jugé"
    assert res["done"] is False, "une mission aux exigences non satisfaites n'est pas terminée"
    assert res["failed"] is True
    assert "tableur" in (res["failure_reason"] or "").lower()
    assert res["actions"] == 0


@pytest.mark.asyncio
async def test_une_mission_qui_affirme_avoir_livre_sans_preuve_n_est_pas_terminee(
    mission, monkeypatch,
):
    """Le scénario du test historique « produit son livrable » : une recherche,
    puis la phrase « j'ai rempli le tableur » — sans écriture. Le juge nomme
    l'écart, la reprise ne le résorbe pas : la mission échoue en le disant."""
    uid, mid = mission
    modele = _ModeleEtJuge([
        _appel("web_search", query="imprimeries Lyon"),
        AIMessage(content="J'ai relevé trois imprimeries et rempli le tableur."),
        AIMessage(content="J'ai relevé trois imprimeries et rempli le tableur."),
    ], _ECARTS)
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert res["done"] is False
    assert res["failed"] is True
    assert "tableur" in (res["failure_reason"] or "").lower()
    assert "tableur" in (res["final_summary"] or "").lower(), (
        "le bilan doit dire à l'utilisateur ce qui manque"
    )


@pytest.mark.asyncio
async def test_une_mission_jugee_conforme_se_conclut(mission, monkeypatch):
    """Le juge tourne sans retour d'outil, et il peut être satisfait : une
    mission dont le livrable est un texte reste possible."""
    uid, mid = mission
    modele = _ModeleEtJuge(
        [AIMessage(content="Les trois imprimeries : A, B, C. Tableur rempli, relu, 3 lignes.")],
        "CONFORME",
    )
    _branche(monkeypatch, modele)

    from app.agent.missions.chat_loop import run_mission_chat_passage

    res = await run_mission_chat_passage(mid, uid, _BUT)

    assert modele.verdicts_rendus == 1
    assert res["done"] is True
    assert res["failed"] is False
    assert "imprimeries" in (res["final_summary"] or "")
