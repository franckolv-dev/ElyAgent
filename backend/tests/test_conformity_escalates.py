# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_conformity_escalates.py
# @brief      Quand la reprise n'avance plus, la boucle ESCALADE au lieu
#             d'abandonner.
# @license    MIT
# =============================================================================
"""Le branchement du panel dans la boucle de conformité — lot 2.

Ce que la boucle faisait jusqu'ici
-----------------------------------
#289 détecte déjà l'instant où la reprise cesse de faire reculer les écarts
(``3 → 3`` : on arrête ; ``3 → 5`` : la reprise a empiré). À cet instant, elle
rédige un constat d'échec honnête et rend la main.

C'est mieux que le silence d'avant #289, mais c'est encore un abandon : Ely a
trois autres modèles configurés dans son tier ``complex``, et elle n'en essaie
aucun. Ils ne servaient qu'en cas de PANNE.

Ce que ce lot change
---------------------
Au même instant, la boucle interroge d'abord 2-3 de ces modèles en parallèle,
fait choisir la meilleure réponse, et la substitue. Le constat d'échec ne
devient plus que le dernier recours — si le panel n'a rien de mieux à offrir.

⚠️ L'ordre compte : escalader D'ABORD, rapporter ensuite. L'inverse ferait
payer un appel de rédaction pour un texte aussitôt remplacé.

Run with:  cd backend && python -m pytest tests/test_conformity_escalates.py -v
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _state(*, gap_count: int, retries: int = 1) -> dict:
    """Un tour qui a produit quelque chose et attend son verdict."""
    return {
        "messages": [
            HumanMessage(content="Traduis ce document en néerlandais."),
            ToolMessage(content="document traduit en anglais", tool_call_id="t1"),
            AIMessage(content="Voici la traduction.", id="reponse-finale"),
        ],
        "conformity_gap_count": gap_count,
        "conformity_retries": retries,
        "user_id": "u1",
        "conversation_id": "c1",
    }


@pytest.fixture
def judge_says_gaps(monkeypatch):
    """Le juge de conformité rend toujours le même écart : rien ne progresse."""
    class _Judge:
        async def ainvoke(self, payload, **kwargs):
            class _R:
                content = "ÉCARTS:\n- la langue demandée était le néerlandais"

            return _R()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _Judge(),
    )
    monkeypatch.setattr(
        "app.services.analytics_service.log_response_usage",
        lambda *a, **k: _noop(),
    )


async def _noop():
    return None


@pytest.mark.asyncio
async def test_the_panel_is_convened_before_giving_up(judge_says_gaps, monkeypatch):
    """LE branchement du lot. Trois modèles configurés, aucun n'était essayé."""
    appels = {"n": 0}

    async def _panel(**kwargs):
        appels["n"] += 1
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Hier is de vertaling.", model="kimi-k3",
                           models_asked=3, cost_usd=0.0, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    out = await conformity_node(_state(gap_count=1))

    assert appels["n"] == 1, "le panel n'a pas été convoqué"
    assert "Hier is de vertaling" in out["messages"][0].content


@pytest.mark.asyncio
async def test_the_escalated_answer_replaces_the_original(judge_says_gaps, monkeypatch):
    """Même ``id`` ⇒ ``add_messages`` SUBSTITUE au lieu d'empiler. Sans ça
    l'utilisateur verrait deux réponses, dont une périmée."""
    async def _panel(**kwargs):
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Meilleure réponse.", model="kimi-k3",
                           models_asked=2, cost_usd=0.0, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    out = await conformity_node(_state(gap_count=1))

    assert out["messages"][0].id == "reponse-finale"


@pytest.mark.asyncio
async def test_the_user_learns_which_model_answered(judge_says_gaps, monkeypatch):
    """« Prendre le meilleur retour et me le proposer. » Sans savoir d'où vient
    la réponse, Franck ne peut ni arbitrer sa configuration ni la corriger."""
    async def _panel(**kwargs):
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Meilleure réponse.", model="kimi-k3",
                           models_asked=3, cost_usd=0.0, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    texte = (await conformity_node(_state(gap_count=1)))["messages"][0].content
    assert "kimi-k3" in texte


@pytest.mark.asyncio
async def test_a_metered_escalation_states_its_cost(judge_says_gaps, monkeypatch):
    """« Si c'est via API […] qu'Ely me le dise. » Un coût nul (forfait) ne
    s'affiche pas : l'annoncer à chaque fois apprendrait à ne plus le lire."""
    async def _panel(**kwargs):
        from app.agent.escalation import PanelResult

        return PanelResult(answer="Réponse.", model="deepseek-v4-pro",
                           models_asked=2, cost_usd=0.032, skipped_for_budget=[])

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    texte = (await conformity_node(_state(gap_count=1)))["messages"][0].content
    assert "0.03" in texte or "0,03" in texte


@pytest.mark.asyncio
async def test_without_a_better_answer_the_gaps_are_still_reported(
    judge_says_gaps, monkeypatch,
):
    """Échouer OUVERT jusqu'au bout : panel indisponible ou sans rien de mieux
    → on retombe sur le constat d'échec de #289, jamais sur le silence."""
    async def _panel(**kwargs):
        return None

    rapports = {"n": 0}

    async def _report(messages, llm, ecarts):
        rapports["n"] += 1
        return {"messages": []}

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    monkeypatch.setattr("app.agent.conformity._report_remaining_gaps", _report)
    from app.agent.conformity import conformity_node

    await conformity_node(_state(gap_count=1))
    assert rapports["n"] == 1


@pytest.mark.asyncio
async def test_a_turn_that_progresses_never_pays_for_a_panel(monkeypatch):
    """Le garde-fou de la facture. ``6 écarts → 1`` se règle par une reprise
    ordinaire ; convoquer le panel là multiplierait le coût de toutes les
    demandes qui allaient très bien."""
    class _Judge:
        async def ainvoke(self, payload, **kwargs):
            class _R:
                content = "ÉCARTS:\n- un seul point reste"

            return _R()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _Judge(),
    )
    monkeypatch.setattr(
        "app.services.analytics_service.log_response_usage", lambda *a, **k: _noop(),
    )
    appels = {"n": 0}

    async def _panel(**kwargs):
        appels["n"] += 1
        return None

    monkeypatch.setattr("app.agent.escalation.escalate_to_panel", _panel)
    from app.agent.conformity import conformity_node

    # 6 écarts au tour précédent, 1 maintenant : ça progresse nettement.
    out = await conformity_node(_state(gap_count=6))

    assert appels["n"] == 0, "le panel a été convoqué alors que ça progressait"
    assert out.get("conformity_retries") == 2, "la reprise ordinaire doit avoir lieu"
