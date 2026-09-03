# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_conformity_check_and_retry.py
# @brief      Le retour du modèle est confronté à la demande, et relancé avec
#             les écarts nommés s'il n'y répond pas.
# @license    MIT
# =============================================================================
"""Rien ne vérifiait que la réponse répondait à la demande.

Le manque, mesuré le 27/07/2026
--------------------------------
- ``completion_guard`` détecte les affirmations **non étayées par un appel
  d'outil** — pas l'écart au cahier des charges.
- ``mission_critic`` ne sert que les missions : **0 appel sur 7 jours**.

Donc quand Franck demandait « convertis sans perte de mise en page, en gardant
la taille, les marges, les polices, les couleurs et les tailles de caractère »,
rien ne confrontait le résultat à ces six exigences, et **aucune relance
n'était possible**. Le tour se terminait sur un résultat médiocre.

La forme, tranchée par Franck (27/07)
-------------------------------------
« Quand elle a le retour, elle regarde si c'est ce que j'ai demandé […] pour
que si ce n'est pas le cas, elle relance la demande auprès d'un LLM Cloud avec
des infos complémentaires ou des paramètres différents. »

Le juge est **le modèle principal, dans le même tour** — il connaît déjà le
contexte, et rien de plus n'est à configurer.

Les deux garde-fous qui font la différence entre une boucle utile et une
boucle folle :

1. **Conforme par défaut.** Un modèle à qui l'on demande « liste les écarts »
   en trouvera toujours. Le contrat inverse la charge : il ne signale un écart
   que si l'utilisateur a formulé une exigence EXPLICITE non satisfaite.
2. **Plafond de relances.** Sinon deux modèles se renvoient la balle sur un
   critère qu'aucun ne sait satisfaire.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.conformity import (
    MAX_CONFORMITY_RETRIES,
    parse_conformity_verdict,
    should_verify_conformity,
)


# ─────────────────────────────────────────────────────────────────────────
# Quand vérifie-t-on ? Un tour sans production n'a rien à vérifier.
# ─────────────────────────────────────────────────────────────────────────


def _turn(*, tool_ran: bool, retries: int = 0) -> dict:
    messages = [HumanMessage(content="convertis ce pdf en docx")]
    if tool_ran:
        messages += [
            AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {}, "id": "1"}]),
            ToolMessage(content="Document Word créé : /app/uploads/x.docx", tool_call_id="1"),
        ]
    messages.append(AIMessage(content="Voilà ton document."))
    return {"messages": messages, "conformity_retries": retries}


def test_a_turn_that_produced_something_gets_verified():
    assert should_verify_conformity(_turn(tool_ran=True)) is True


def test_chitchat_is_not_verified():
    """« bonjour » n'a rien produit : le vérifier coûterait un appel pour rien.

    Le déclencheur est l'exécution d'un outil, pas un mot-clé — on ne
    réintroduit pas l'heuristique qu'on vient de supprimer en L2.
    """
    assert should_verify_conformity(_turn(tool_ran=False)) is False


def test_the_retry_budget_is_enforced():
    """Sans plafond, deux modèles se renvoient la balle sur une exigence
    qu'aucun ne sait satisfaire."""
    assert should_verify_conformity(_turn(tool_ran=True, retries=MAX_CONFORMITY_RETRIES)) is False


def test_the_budget_allows_at_least_one_retry():
    assert MAX_CONFORMITY_RETRIES >= 1
    assert should_verify_conformity(_turn(tool_ran=True, retries=MAX_CONFORMITY_RETRIES - 1)) is True


def test_a_turn_still_holding_tool_calls_is_not_the_end_of_the_turn():
    """La vérification porte sur le RÉSULTAT, donc seulement quand le tour se
    termine — pas au milieu de la boucle d'outils."""
    state = _turn(tool_ran=True)
    state["messages"].append(
        AIMessage(content="", tool_calls=[{"name": "drive_upload", "args": {}, "id": "2"}])
    )
    assert should_verify_conformity(state) is False


# ─────────────────────────────────────────────────────────────────────────
# Le verdict : conforme par défaut
# ─────────────────────────────────────────────────────────────────────────


def test_conforme_verdict_ends_the_turn():
    ok, gaps = parse_conformity_verdict("CONFORME")
    assert ok is True
    assert gaps == ""


def test_conforme_is_recognised_despite_model_chattiness():
    """Les modèles ajoutent volontiers une phrase autour du mot attendu."""
    ok, _ = parse_conformity_verdict("Après vérification : CONFORME.")
    assert ok is True


def test_named_gaps_trigger_a_retry():
    ok, gaps = parse_conformity_verdict(
        "ÉCARTS:\n- les marges du document source ne sont pas reprises\n"
        "- la police d'origine est remplacée par Calibri"
    )
    assert ok is False
    assert "marges" in gaps
    assert "police" in gaps


def test_an_unreadable_verdict_is_treated_as_conforme():
    """Le garde ne doit JAMAIS échouer fermé : un verdict illisible qui
    relancerait le tour transformerait une panne du juge en boucle de
    relances payantes. En cas de doute, on laisse passer.
    """
    for bruit in ("", "   ", "je ne sais pas quoi répondre", "{json cassé"):
        ok, _ = parse_conformity_verdict(bruit)
        assert ok is True, f"{bruit!r} a déclenché une relance"


def test_the_content_blocks_shape_is_handled():
    """Le tier codex rend ``content`` en LISTE de blocs — ce piège a déjà
    coûté plusieurs incidents (#205, #250)."""
    ok, gaps = parse_conformity_verdict(
        [{"type": "text", "text": "ÉCARTS:\n- les couleurs sont perdues"}]
    )
    assert ok is False
    assert "couleurs" in gaps


# ─────────────────────────────────────────────────────────────────────────
# Le nœud : conforme → fin ; écarts → retour à l'agent avec la consigne
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_judge(monkeypatch):
    """Remplace l'appel au modèle juge par un verdict fixé."""
    def _install(verdict: str):
        from app.agent import conformity as conf

        monkeypatch.setattr(
            "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
        )

        async def _fake(*_a, **_k):
            return AIMessage(content=verdict)

        monkeypatch.setattr(conf, "ainvoke_with_deadline", _fake)

    return _install


@pytest.mark.asyncio
async def test_a_conforming_result_adds_nothing_to_the_conversation(stub_judge):
    from app.agent.conformity import conformity_node

    stub_judge("CONFORME")
    out = await conformity_node(_turn(tool_ran=True))
    assert out.get("messages", []) == []


@pytest.mark.asyncio
async def test_a_gap_sends_the_agent_back_with_the_gap_named(stub_judge):
    from app.agent.conformity import conformity_node

    stub_judge("ÉCARTS:\n- les marges ne sont pas conservées")
    out = await conformity_node(_turn(tool_ran=True))

    assert len(out["messages"]) == 1
    relance = out["messages"][0]
    assert isinstance(relance, HumanMessage)
    assert "marges" in relance.content, "l'écart doit être nommé dans la relance"
    assert out["conformity_retries"] == 1


@pytest.mark.asyncio
async def test_a_failing_judge_never_blocks_the_turn(stub_judge, monkeypatch):
    """Si le juge tombe (réseau, quota), le tour se termine normalement.
    Une vérification en panne ne doit pas retenir la réponse de l'utilisateur.
    """
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("juge indisponible")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _boom)
    out = await conformity_node(_turn(tool_ran=True))
    assert out.get("messages", []) == []


@pytest.mark.asyncio
async def test_the_judge_call_does_not_leak_into_the_user_stream(stub_judge, monkeypatch):
    """Cet appel tourne PENDANT un tour actif. Sans isolation, ses tokens
    partent dans le stream de l'utilisateur — bug réel du 19/07 avec le
    générateur tier-S entrelacé caractère par caractère dans le chat.
    """
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    seen: dict = {}

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _capture(_llm, _msgs, **kwargs):
        seen.update(kwargs)
        return AIMessage(content="CONFORME")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _capture)
    await conformity_node(_turn(tool_ran=True))

    assert seen.get("config", {}).get("callbacks") == [], (
        "l'appel du juge doit couper les callbacks, sinon ses tokens "
        "s'affichent dans la réponse de l'utilisateur"
    )


# ─────────────────────────────────────────────────────────────────────────
# Le câblage dans le graphe
# ─────────────────────────────────────────────────────────────────────────


def test_a_producing_turn_is_routed_to_verification_instead_of_ending():
    from app.agent.routing import should_continue

    assert should_continue(_turn(tool_ran=True)) == "verify"


def test_chitchat_still_ends_directly():
    from app.agent.routing import should_continue

    assert should_continue(_turn(tool_ran=False)) == "end"


def test_a_turn_with_pending_tool_calls_still_goes_to_tools():
    from app.agent.routing import should_continue

    state = _turn(tool_ran=True)
    state["messages"].append(
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "9"}])
    )
    assert should_continue(state) == "tools"


def test_after_verification_a_named_gap_goes_back_to_the_agent():
    from app.agent.conformity import route_after_conformity

    state = _turn(tool_ran=True)
    state["messages"].append(HumanMessage(content="[Vérification — …]\n- les marges"))
    assert route_after_conformity(state) == "agent"


def test_after_verification_a_conforming_turn_ends():
    from app.agent.conformity import route_after_conformity

    assert route_after_conformity(_turn(tool_ran=True)) == "end"


def test_the_graph_wires_the_verification_node():
    """Le nœud doit être joignable dans le graphe de production, pas seulement
    exister. Un nœud non câblé serait indétectable par les tests unitaires."""
    from app.agent.graph import build_agent_graph

    nodes = set(build_agent_graph().get_graph().nodes)
    assert "verify" in nodes


@pytest.mark.asyncio
async def test_the_deadline_helper_really_forwards_config():
    """Anti-faux-positif. Le test du stream ci-dessus remplace
    ``ainvoke_with_deadline`` par un stub qui gobe ``**kwargs`` : il passerait
    au vert même si la vraie fonction refusait ``config``. On appelle donc ici
    la VRAIE fonction, avec un faux LLM, pour vérifier que le paramètre existe
    et arrive jusqu'à ``llm.ainvoke``.

    (Écrit après avoir constaté que la signature ne l'acceptait pas — l'appel
    du nœud aurait levé un TypeError en production.)
    """
    from app.services.llm_deadline import ainvoke_with_deadline

    vu = {}

    class _FakeLLM:
        async def ainvoke(self, payload, config=None):
            vu["config"] = config
            return AIMessage(content="CONFORME")

    await ainvoke_with_deadline(
        _FakeLLM(), [HumanMessage(content="x")],
        surface="test", config={"callbacks": []},
    )
    assert vu["config"] == {"callbacks": []}


@pytest.mark.asyncio
async def test_the_deadline_helper_stays_usable_without_config():
    """Les dizaines d'appels existants ne passent pas ``config`` — ils doivent
    continuer de marcher sans que rien ne soit transmis."""
    from app.services.llm_deadline import ainvoke_with_deadline

    vu = {}

    class _FakeLLM:
        async def ainvoke(self, payload, **kwargs):
            vu.update(kwargs)
            return AIMessage(content="ok")

    await ainvoke_with_deadline(_FakeLLM(), [HumanMessage(content="x")])
    assert "config" not in vu


def test_the_recursion_budget_absorbs_the_extra_super_steps():
    """Chaque relance ajoute des super-steps. Le plafond de récursion doit
    rester au-dessus, sinon LangGraph coupe le tour avant force_summary —
    l'incident du 2026-06-01."""
    from app.agent.conformity import MAX_CONFORMITY_RETRIES
    from app.agent.routing import CHAT_RECURSION_LIMIT, MAX_AGENT_ITERATIONS

    assert CHAT_RECURSION_LIMIT > MAX_AGENT_ITERATIONS * 2 + 2 * MAX_CONFORMITY_RETRIES
