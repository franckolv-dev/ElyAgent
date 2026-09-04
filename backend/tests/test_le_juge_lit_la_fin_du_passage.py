# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_juge_lit_la_fin_du_passage.py
# @brief      Le juge de conformité lit la réponse finale et les derniers
#             retours d'outils, pas les premiers ; un passage automatisé ne
#             convoque pas le panel ; un budget épuisé clôt le passage sans
#             juge ni escalade ; le résumé forcé tolère un raisonnement
#             chiffré illisible.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « Nettoyage mails » (ff48cbc2), 04/09/2026, passages 3 et 4.

Le passage 4 a joué 39 actions (34 000 caractères de retours d'outils) puis
conclu « FAIT dans ce passage : j'ai vérifié la programmation… ». Le juge a
rendu 6 écarts, dont « rien n'a été analysé » : il lisait
``resultat[:8000]`` — les DEUX premiers retours d'outils, jamais la réponse
finale, coupée par la fin. « Aucun progrès » → panel sans outils → kimi-k3
rend un PLAN (« la mission n'a pas encore touché la boîte ») qui REMPLACE le
bilan et devient le résumé d'une mission « completed ». Coût : 0,07 $, et un
mail réellement mis à la corbeille nié.

Trois défauts, trois règles :
1. la troncature garde la FIN (réponse finale + derniers retours), comme la
   consigne de mission garde son début (``preserve_first``) ;
2. un passage automatisé ne convoque pas le panel : personne ne lit sa
   réponse, seul le travail compte, et un relais sans outils ne travaille pas ;
3. un budget épuisé clôt le passage : ni juge (aucune reprise possible), ni
   escalade, et la mission échoue en gardant le bilan du modèle.

Plus : ``force_summary`` (le résumé forcé du 80e appel) a échoué sur un 400
``invalid_encrypted_content`` — le même défaut que #371, sur un chemin qui
n'avait pas reçu la tolérance.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


async def _noop(*_a, **_k):
    return None


def _fil(n_retours: int, taille: int = 1000) -> list:
    messages = [HumanMessage(content="Nettoie la boîte.")]
    for i in range(n_retours):
        messages.append(ToolMessage(
            content=f"retour {i:02d} " + "x" * taille, tool_call_id=f"t{i}",
        ))
    messages.append(AIMessage(
        content="FAIT : un mail à la corbeille, trois conservés.", id="finale",
    ))
    return messages


# ── 1. La troncature garde la fin ────────────────────────────────────────────

def test_ce_qui_a_ete_produit_garde_la_reponse_finale_et_les_derniers_retours():
    from app.agent.conformity import _produced

    texte = _produced(_fil(60), maxi=8000)

    assert len(texte) <= 8000
    assert "[réponse finale] FAIT : un mail à la corbeille" in texte
    assert "retour 59" in texte
    assert "retour 00" not in texte


def test_un_passage_court_est_rendu_en_entier_et_dans_l_ordre():
    from app.agent.conformity import _produced

    texte = _produced(_fil(3, taille=10), maxi=8000)

    assert texte.index("retour 00") < texte.index("retour 02") < texte.index("[réponse finale]")


@pytest.mark.asyncio
async def test_le_juge_recoit_la_reponse_finale_d_un_long_passage(monkeypatch):
    recu: list[str] = []

    class _Juge:
        async def ainvoke(self, payload, **_kw):
            recu.append(payload[0].content)
            return AIMessage(content="CONFORME")

    monkeypatch.setattr("app.services.llm_provider.get_llm_for_tier", lambda tier: _Juge())
    monkeypatch.setattr("app.services.analytics_service.log_response_usage", _noop)
    from app.agent.conformity import conformity_node

    await conformity_node({
        "messages": _fil(60), "conformity_gap_count": 0, "conformity_retries": 0,
        "user_id": "u1", "conversation_id": "c1",
    })

    assert recu, "le juge n'a pas été appelé"
    assert "FAIT : un mail à la corbeille" in recu[0]
    assert "retour 59" in recu[0]


# ── 2. Un passage automatisé ne convoque pas le panel ────────────────────────

@pytest.mark.asyncio
async def test_un_passage_automatise_ne_convoque_pas_le_panel(monkeypatch):
    class _Juge:
        async def ainvoke(self, payload, **_kw):
            return AIMessage(content="ÉCARTS:\n- rien n'a été mis à la corbeille")

    monkeypatch.setattr("app.services.llm_provider.get_llm_for_tier", lambda tier: _Juge())
    monkeypatch.setattr("app.services.analytics_service.log_response_usage", _noop)
    appels = {"n": 0}

    async def _panel(**_kw):
        # Pas de `raise` : `_try_escalation` échoue OUVERT et avalerait
        # l'assertion — le test passerait pour de mauvaises raisons.
        appels["n"] += 1
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Plan en six points.", model="kimi-k3",
                           models_asked=3, cost_usd=0.07, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    out = await conformity_node({
        "messages": _fil(2, taille=10),
        "conformity_gap_count": 1, "conformity_retries": 1,
        "user_id": "u1", "conversation_id": "c1", "automated_task": True,
    })

    assert appels["n"] == 0, "le panel a été convoqué pendant un passage automatisé"
    texte = out["messages"][0].content if out["messages"] else ""
    assert "Plan en six points" not in texte


@pytest.mark.asyncio
async def test_un_tour_de_chat_convoque_toujours_le_panel(monkeypatch):
    """La règle 2 ne touche pas le chat : là, l'utilisateur lit la réponse."""
    class _Juge:
        async def ainvoke(self, payload, **_kw):
            return AIMessage(content="ÉCARTS:\n- rien n'a été mis à la corbeille")

    monkeypatch.setattr("app.services.llm_provider.get_llm_for_tier", lambda tier: _Juge())
    monkeypatch.setattr("app.services.analytics_service.log_response_usage", _noop)
    appels = {"n": 0}

    async def _panel(**_kw):
        appels["n"] += 1
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Meilleure réponse.", model="kimi-k3",
                           models_asked=3, cost_usd=0.0, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    await conformity_node({
        "messages": _fil(2, taille=10),
        "conformity_gap_count": 1, "conformity_retries": 1,
        "user_id": "u1", "conversation_id": "c1",
    })

    assert appels["n"] == 1


# ── 3. Un budget épuisé clôt le passage ──────────────────────────────────────

_BUT = "Trouve les trois imprimeries les plus proches et note-les dans un tableur."


def _appel(nom: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": nom, "args": args, "id": f"call_{nom}_{uuid.uuid4().hex[:4]}"}],
    )


class _ModeleScripte:
    def __init__(self, tours):
        self._tours = list(tours)

    def bind_tools(self, tools, **_kw):
        return self

    def with_config(self, *_a, **_kw):
        return self

    async def ainvoke(self, messages, config=None, **_kw):
        if not self._tours:
            return AIMessage(content="Plus rien a faire.")
        return self._tours.pop(0)


@pytest_asyncio.fixture
async def mission_a_deux_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSIONS_WORKSPACE_DIR", str(tmp_path / "missions"))
    from app.database import async_session, init_db
    from app.models.user import User
    from app.services import mission_service
    from tests._user_cleanup import purge_user

    await init_db()
    uid = f"test_bud_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[-8:]}",
                    email=f"{uid}@bench.local", hashed_password="x"))
        await db.commit()
    m = await mission_service.create_mission(
        user_id=uid, title="Prospection", goal=_BUT, budget_iterations=2,
    )
    await mission_service.start_mission(m.id)
    yield uid, m.id
    await purge_user(uid)


@pytest.mark.asyncio
async def test_un_budget_epuise_clot_le_passage_sans_juge_ni_panel(
    mission_a_deux_actions, monkeypatch,
):
    uid, mid = mission_a_deux_actions
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp
    from app.agent.missions import chat_loop

    modele = _ModeleScripte([
        _appel("web_search", query="imprimerie Nantes"),
        _appel("web_search", query="imprimerie Rezé"),
        _appel("web_search", query="imprimerie Vertou"),  # refusé : 2/2
        AIMessage(content=(
            "FAIT : deux recherches. Reste : le tableur. "
            f"{chat_loop.MARQUEUR_A_SUIVRE}"
        )),
    ])
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return f"Resultat de {nom}.", True

    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)

    async def _juge_interdit(state):
        raise AssertionError("le juge a été appelé alors que le budget est épuisé")

    monkeypatch.setattr(chat_loop, "conformity_node", _juge_interdit)

    resultat = await chat_loop.run_mission_chat_passage(mid, uid, _BUT)

    # Le modèle demandait un passage de plus : le budget ne le permet plus,
    # la mission échoue en le disant, avec le bilan — sans le marqueur.
    assert resultat["failed"] is True
    assert "budget" in (resultat["failure_reason"] or "").lower()
    assert "FAIT : deux recherches" in (resultat["final_summary"] or "")
    assert chat_loop.MARQUEUR_A_SUIVRE not in (resultat["final_summary"] or "")
    assert resultat["done"] is False


@pytest.mark.asyncio
async def test_un_budget_epuise_sur_une_conclusion_clot_la_mission(
    mission_a_deux_actions, monkeypatch,
):
    """Le modèle dit avoir fini malgré le refus : la mission est conclue sur
    SON bilan, pas sur celui d'un juge qui ne peut plus rien relancer."""
    uid, mid = mission_a_deux_actions
    import app.agent.missions.nodes as mn
    import app.services.llm_provider as lp
    from app.agent.missions import chat_loop

    modele = _ModeleScripte([
        _appel("web_search", query="imprimerie Nantes"),
        _appel("web_search", query="imprimerie Rezé"),
        _appel("web_search", query="imprimerie Vertou"),  # refusé : 2/2
        AIMessage(content="Les trois imprimeries sont dans le tableur."),
    ])
    monkeypatch.setattr(lp, "get_llm_for_tier", lambda *a, **k: modele)
    monkeypatch.setattr(lp, "get_fallback_llms", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(lp, "get_llm", lambda *a, **k: modele, raising=False)

    async def _dispatch(nom, args, _cid, _uid, **_kw):
        return f"Resultat de {nom}.", True

    monkeypatch.setattr(mn, "dispatch_tool", _dispatch)

    async def _juge_interdit(state):
        raise AssertionError("le juge a été appelé alors que le budget est épuisé")

    monkeypatch.setattr(chat_loop, "conformity_node", _juge_interdit)

    resultat = await chat_loop.run_mission_chat_passage(mid, uid, _BUT)

    assert resultat["done"] is True
    assert resultat["failed"] is False
    assert resultat["final_summary"] == "Les trois imprimeries sont dans le tableur."


@pytest.mark.asyncio
async def test_l_echec_pour_budget_garde_le_bilan_sur_la_mission(mission_a_deux_actions):
    uid, mid = mission_a_deux_actions
    from app.services import mission_service

    m = await mission_service.fail_mission(
        mid, "budget d'itérations de la mission épuisé (2/2)",
        final_summary="FAIT : deux recherches. Reste : le tableur.",
    )

    assert m.status == "failed"
    assert m.final_summary == "FAIT : deux recherches. Reste : le tableur."
    assert "budget" in m.failure_reason


# ── 4. Le résumé forcé tolère un raisonnement chiffré illisible ──────────────

@pytest.mark.asyncio
async def test_le_resume_force_rappelle_sans_le_raisonnement_chiffre(monkeypatch):
    from app.agent.force_summary import force_summary_node

    vrai = MagicMock()
    vrai.content = "Résumé : deux mails traités."
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=[
        RuntimeError("Error code: 400 - invalid_encrypted_content"), vrai,
    ])
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: fake_llm,
    )
    monkeypatch.setattr(
        "app.services.memory_service.maybe_spawn_fact_extraction", lambda *a, **k: None,
    )

    out = await force_summary_node({
        "messages": [
            HumanMessage(content="Nettoie la boîte."),
            AIMessage(content=[{"type": "reasoning", "id": "rs_1", "summary": []},
                               {"type": "text", "text": "je liste"}],
                      tool_calls=[{"name": "gmail_list", "args": {}, "id": "c1"}]),
            ToolMessage(content="2 mails", tool_call_id="c1"),
        ],
        "iteration_count": 80, "user_id": "u1", "conversation_id": "c1",
    })

    assert out["messages"][0].content == "Résumé : deux mails traités."
    assert fake_llm.ainvoke.await_count == 2
    second = fake_llm.ainvoke.await_args_list[1].args[0]
    assert not any(
        isinstance(b, dict) and b.get("type") == "reasoning"
        for m in second if isinstance(m, AIMessage) and isinstance(m.content, list)
        for b in m.content
    )
