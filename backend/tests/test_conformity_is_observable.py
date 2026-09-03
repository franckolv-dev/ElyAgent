# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_conformity_is_observable.py
# @brief      La boucle de conformité doit laisser une trace — sinon on ne
#             peut ni la mesurer ni la corriger.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La vérification tournait à l'aveugle.

Le constat (28/07/2026, première conversion PDF→DOCX réelle après #288)
------------------------------------------------------------------------
Les journaux du conteneur montraient tout le tour — ``tier=complex``,
GPT-5.6 retenu, 111 outils bindés, ``pdf_to_docx`` en 3,84 s, succès — mais
**aucune trace du nœud ``verify``**.

Cause : ``conformity_node`` ne journalisait QUE les relances et les arrêts. Le
chemin nominal (verdict conforme) rendait ``{"messages": []}`` en silence, et
l'appel du juge n'était compté dans aucune ligne d'``usage_logs``.

Conséquence : impossible de savoir si la boucle s'exécutait, ce qu'elle
coûtait, ni si le juge était complaisant — c'est-à-dire impossible de mesurer
précisément ce que cette boucle a été construite pour rendre mesurable.

Ce lot rend les trois choses observables : le verdict (journal), le coût
(``usage_logs.skill_used = "conformity_check"``, comme ``memory_extraction``),
et le fait même que la vérification a eu lieu.
"""
from __future__ import annotations

import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _turn(retries: int = 0) -> dict:
    return {
        "messages": [
            HumanMessage(content="convertis ce pdf en docx sans perdre les marges"),
            AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {}, "id": "1"}]),
            ToolMessage(content="Document créé", tool_call_id="1"),
            AIMessage(content="Voilà ton document.", id="final-1"),
        ],
        "user_id": "user-1",
        "conformity_retries": retries,
        "conformity_gap_count": 0,
    }


@pytest.fixture
def judge(monkeypatch):
    def _install(*verdicts: str):
        from app.agent import conformity as conf

        monkeypatch.setattr(
            "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
        )
        restants = list(verdicts)

        async def _fake(*_a, **_k):
            return AIMessage(content=restants.pop(0) if restants else "CONFORME")

        monkeypatch.setattr(conf, "ainvoke_with_deadline", _fake)

    return _install


@pytest.mark.asyncio
async def test_a_conforming_verdict_leaves_a_trace(judge, caplog):
    """LE défaut : un tour conforme ne disait rien. On ne pouvait donc pas
    distinguer « la vérification a jugé conforme » de « la vérification n'a
    jamais tourné » — exactement la question posée le 28/07."""
    from app.agent.conformity import conformity_node

    judge("CONFORME")
    with caplog.at_level(logging.INFO, logger="app.agent.conformity"):
        await conformity_node(_turn())

    trace = " ".join(r.message for r in caplog.records).lower()
    assert "conform" in trace, "le chemin nominal reste muet dans les journaux"


@pytest.mark.asyncio
async def test_the_judge_call_is_counted_in_usage(judge, monkeypatch):
    """Sans ligne d'usage, le coût de la boucle est invisible au tableau de
    bord — et on ne peut pas arbitrer s'il vaut ce qu'il rapporte."""
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    logged: dict = {}

    async def _fake_log(user_id, response, **kwargs):
        logged.update(user_id=user_id, **kwargs)

    monkeypatch.setattr(conf, "log_response_usage", _fake_log)
    judge("CONFORME")
    await conformity_node(_turn())

    assert logged.get("skill_used") == "conformity_check"
    assert logged.get("user_id") == "user-1"


@pytest.mark.asyncio
async def test_a_broken_usage_logger_never_breaks_the_turn(judge, monkeypatch):
    """La journalisation est un confort, jamais une dépendance."""
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    async def _boom(*_a, **_k):
        raise RuntimeError("analytics indisponible")

    monkeypatch.setattr(conf, "log_response_usage", _boom)
    judge("CONFORME")
    assert await conformity_node(_turn()) == {"messages": []}


@pytest.mark.asyncio
async def test_a_gap_still_names_the_gap_in_the_logs(judge, caplog):
    """Comportement déjà présent — on le pin pour ne pas le perdre en
    réorganisant la journalisation."""
    from app.agent.conformity import conformity_node

    judge("ÉCARTS:\n- les marges ne sont pas conservées")
    with caplog.at_level(logging.INFO, logger="app.agent.conformity"):
        await conformity_node(_turn(retries=0))

    assert "marges" in " ".join(r.message for r in caplog.records)
