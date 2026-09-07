# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_un_passage_compacte_ses_anciens_retours.py
# @brief      Lot 4 (07/09/2026) : les retours d'outils anciens d'un passage
#             sont compactés avant l'appel au modèle ; l'état, lui, garde tout.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""« Plateformes littéraires » (07/09/2026) : 2,27 M tokens d'entrée pour 57
appels dans un seul passage, soit 40 000 par appel. Le passage 2 a produit
87 000 caractères de retours d'outils (26 lectures de HTML à 8 600
caractères) et TOUT repartait à chaque appel : la fenêtre de 1 M tokens du
modèle ne tronque jamais, donc rien ne compactait.

Le modèle a déjà agi sur un retour vieux de six tours. Il en garde un
aperçu ; le détail reste dans l'état (traces, juge) et l'outil se relance
si besoin.

Run with:  cd backend && python -m pytest tests/test_un_passage_compacte_ses_anciens_retours.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}],
    )


def _fil(n: int, taille: int = 8_600) -> list:
    """n retours d'outils de `taille` caractères, chacun précédé de son appel."""
    fil = [HumanMessage(content="Objectif.")]
    for i in range(n):
        a = _appel("browser_tab_read_html", selector=f"#s{i}")
        fil.append(a)
        fil.append(ToolMessage(
            content=f"RETOUR {i} " + ("x" * taille), tool_call_id=a.tool_calls[0]["id"],
            name="browser_tab_read_html",
        ))
    return fil


# ── La fonction ─────────────────────────────────────────────────────────────


def test_les_anciens_retours_sont_compactes_les_derniers_gardes_entiers():
    from app.agent.missions.chat_loop import compacter_les_retours

    fil = _fil(10)
    compact = compacter_les_retours(fil, garder=6, apercu=400)

    retours = [m for m in compact if isinstance(m, ToolMessage)]
    assert len(retours) == 10, "aucun message ne disparaît"
    for m in retours[:4]:
        assert len(m.content) < 600
        assert m.content.startswith("RETOUR ")
        assert "compacté" in m.content and "8 6" in m.content.replace(" ", " ").replace("\xa0", " ")
    for m in retours[4:]:
        assert len(m.content) > 8_000, "les six derniers restent entiers"


def test_les_ids_et_l_ordre_sont_preserves():
    from app.agent.missions.chat_loop import compacter_les_retours

    fil = _fil(8)
    compact = compacter_les_retours(fil, garder=2)

    assert [type(m) for m in compact] == [type(m) for m in fil]
    assert [getattr(m, "tool_call_id", None) for m in compact] == [
        getattr(m, "tool_call_id", None) for m in fil
    ]
    assert compact[0] is fil[0], "les messages non touchés sont les mêmes objets"


def test_un_retour_court_n_est_pas_touche():
    from app.agent.missions.chat_loop import compacter_les_retours

    fil = _fil(10, taille=300)
    compact = compacter_les_retours(fil, garder=2, apercu=400)
    assert all(m.content == o.content for m, o in zip(compact, fil))


def test_l_etat_d_origine_n_est_pas_modifie():
    from app.agent.missions.chat_loop import compacter_les_retours

    fil = _fil(10)
    avant = [m.content for m in fil]
    compacter_les_retours(fil, garder=2)
    assert [m.content for m in fil] == avant


def test_la_mesure_du_passage_senscritique():
    """26 lectures de HTML à 8 600 caractères : ce qui repart au modèle
    tombe sous le tiers de l'original."""
    from app.agent.missions.chat_loop import compacter_les_retours

    fil = _fil(26)
    original = sum(len(m.content) for m in fil if isinstance(m, ToolMessage))
    compact = compacter_les_retours(fil, garder=6, apercu=400)
    reste = sum(len(m.content) for m in compact if isinstance(m, ToolMessage))
    assert reste < original / 3, f"{reste} / {original}"


# ── Le branchement dans le passage ──────────────────────────────────────────


class _ModeleQuiVoit:
    def __init__(self, tours):
        self._tours = list(tours)
        self.vus: list[str] = []

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        morceaux = []
        for m in messages or ():
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            morceaux.append(c if isinstance(c, str) else str(c))
        texte = "\n".join(morceaux)
        self.vus.append(texte)
        if "Tu vérifies qu'un travail répond" in texte:
            return AIMessage(content="CONFORME")
        if not self._tours:
            return AIMessage(content="Fini.")
        return self._tours.pop(0)


@pytest_asyncio.fixture
async def mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_compact_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Compaction", goal="Lis dix pages puis conclus.",
        budget_iterations=50,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


@pytest.mark.asyncio
async def test_le_modele_recoit_les_retours_compactes_et_l_etat_les_garde(mission, monkeypatch):
    uid, mid = mission
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp
    from app.services import mission_questions

    tours = [_appel("browser_tab_read_html", selector=f"#s{i}") for i in range(10)]
    tours.append(AIMessage(content="Dix pages lues, conclusion écrite."))
    modele = _ModeleQuiVoit(tours)
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(mission_questions, "notifier", _rien)
    # La fenêtre du modèle en prod (gpt-5.6 : 1 M) ne tronque JAMAIS — c'est
    # tout le sujet. Sans ce réglage, le modèle factice tombe sur la fenêtre
    # par défaut de 8 192 et `fit_messages_to_context` jette les anciens
    # messages avant qu'on voie ce que la compaction en fait.
    import app.services.context_manager as cm

    monkeypatch.setattr(cm, "get_context_window", lambda _model: 1_000_000)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return f"RETOUR {args.get('selector')} " + ("x" * 8_600), True

    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)

    from app.agent.missions.chat_loop import run_mission_chat_passage
    from app.services import mission_service

    res = await run_mission_chat_passage(mid, uid, "Lis dix pages puis conclus.")

    assert res["done"] is True
    dernier_prompt = modele.vus[-2] if len(modele.vus) >= 2 else modele.vus[-1]
    # Au dernier tour d'agent, le premier retour n'est plus entier…
    assert dernier_prompt.count("x" * 8_000) <= 6, "plus de six retours entiers dans le prompt"
    assert "compacté" in dernier_prompt
    # …mais la trace en base garde le retour complet.
    steps = await mission_service.list_steps(mid)
    assert max(len(s.tool_output or "") for s in steps if s.phase == "act") > 8_000


def test_le_journal_ne_liste_plus_les_230_outils_a_chaque_appel():
    """`[diag.bind] tier=… tools(230)=[…]` en WARNING, à CHAQUE appel du
    modèle : 230 noms par ligne, plusieurs lignes par action. Le compte et
    le profil suffisent à l'usage ; la liste passe en DEBUG."""
    import inspect

    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    i = src.index('"[diag.bind] tier=%s profile=%r→%r tools(%d)')
    bloc = src[i - 200:i + 400]
    assert "logger.debug(" in bloc or "logger.info(" in bloc
    assert "logger.warning(" not in src[i - 120:i]
