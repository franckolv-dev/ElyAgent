# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_conformity_progress_and_report.py
# @brief      Les reprises s'arrêtent quand elles n'avancent plus, et ce qui
#             reste non satisfait est DIT à l'utilisateur.
# @license    MIT
# =============================================================================
"""Deux défauts du plafond fixe livré en #288.

1. **Le plafond était aveugle.** ``MAX_CONFORMITY_RETRIES = 2`` était un
   chiffre posé SANS mesure — la boucle n'avait jamais tourné en production.
   Il traitait de la même façon une tâche qui progresse (6 exigences non
   satisfaites → 2 → 1) et une qui tourne en rond (les mêmes 3 écarts à chaque
   reprise). La première méritait de continuer, la seconde devait s'arrêter
   tout de suite au lieu de brûler deux reprises pour rien.

2. **Le plafond était SILENCIEUX.** Une fois épuisé,
   ``should_verify_conformity`` rendait False, ``should_continue`` rendait
   « end », et l'utilisateur ne savait jamais qu'il restait des écarts. C'est
   exactement le « résultat incomplet rendu en silence » que tout ce chantier
   vise à supprimer.

Décisions de Franck (28/07/2026)
--------------------------------
- On continue tant que les écarts DIMINUENT ; on s'arrête dès qu'une reprise
  ne fait plus reculer la liste. Plafond de sécurité haut, contre l'emballement.
- Quand on s'arrête avec des écarts restants, Ely le DIT et propose une piste.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.conformity import (
    MAX_CONFORMITY_RETRIES,
    count_gaps,
    is_making_progress,
)


# ─────────────────────────────────────────────────────────────────────────
# Compter les écarts
# ─────────────────────────────────────────────────────────────────────────


def test_each_bullet_is_one_gap():
    assert count_gaps(
        "- les marges ne sont pas conservées\n"
        "- la police d'origine est remplacée\n"
        "- les couleurs sont perdues"
    ) == 3


def test_blank_lines_and_prose_do_not_inflate_the_count():
    assert count_gaps("\n- une seule exigence\n\nvoilà.\n") == 1


def test_no_bullet_at_all_still_counts_as_one_gap():
    """Le juge peut répondre en prose. Un écart signalé reste un écart —
    mais un seul, pour ne pas gonfler artificiellement le compte."""
    assert count_gaps("la mise en page n'est pas respectée") == 1


def test_nothing_is_zero_gaps():
    assert count_gaps("") == 0
    assert count_gaps("   \n  ") == 0


# ─────────────────────────────────────────────────────────────────────────
# Le progrès décide, pas le compteur
# ─────────────────────────────────────────────────────────────────────────


def test_the_first_verification_always_gets_a_chance():
    """Aucun tour précédent : on ne peut pas parler de progrès, on laisse
    la première reprise se faire."""
    assert is_making_progress(new_count=3, previous_count=0) is True


def test_fewer_gaps_than_last_time_is_progress():
    assert is_making_progress(new_count=1, previous_count=3) is True


def test_the_same_number_of_gaps_is_not_progress():
    """Le cas qui coûtait deux reprises pour rien : le modèle rend la même
    liste, la reprise suivante rendra la même."""
    assert is_making_progress(new_count=3, previous_count=3) is False


def test_more_gaps_than_last_time_is_not_progress():
    """La reprise a empiré les choses — insister n'a aucune raison d'aider."""
    assert is_making_progress(new_count=5, previous_count=3) is False


def test_the_safety_ceiling_is_high_enough_to_let_a_task_converge():
    """Le plafond n'est plus le régulateur, c'est un garde-fou d'emballement.
    Il doit laisser de la place à une tâche qui avance vraiment."""
    assert MAX_CONFORMITY_RETRIES >= 5


# ─────────────────────────────────────────────────────────────────────────
# Le nœud : relance tant que ça avance, rapport quand ça s'arrête
# ─────────────────────────────────────────────────────────────────────────


def _turn(*, retries: int = 0, gap_count: int = 0) -> dict:
    return {
        "messages": [
            HumanMessage(content="convertis ce pdf en docx sans perdre les marges"),
            AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {}, "id": "1"}]),
            ToolMessage(content="Document créé", tool_call_id="1"),
            AIMessage(content="Voilà ton document.", id="final-1"),
        ],
        "conformity_retries": retries,
        "conformity_gap_count": gap_count,
    }


@pytest.fixture
def judge(monkeypatch):
    """Fait dire au juge ce qu'on veut, verdict après verdict."""
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
async def test_progress_triggers_a_retry_and_records_the_gap_count(judge):
    from app.agent.conformity import conformity_node

    judge("ÉCARTS:\n- les marges\n- les couleurs")
    out = await conformity_node(_turn(retries=1, gap_count=4))

    assert out["conformity_retries"] == 2
    assert out["conformity_gap_count"] == 2, "le compte doit être mémorisé pour le tour suivant"
    assert isinstance(out["messages"][0], HumanMessage)


@pytest.mark.asyncio
async def test_a_stalled_retry_stops_immediately_instead_of_burning_the_budget(judge):
    """Mêmes 2 écarts qu'au tour précédent : on arrête, sans consommer les
    reprises restantes."""
    from app.agent.conformity import conformity_node

    judge("ÉCARTS:\n- les marges\n- les couleurs", "RAPPORT")
    out = await conformity_node(_turn(retries=1, gap_count=2))

    assert out.get("conformity_retries") != 2, "une reprise a été gaspillée malgré l'absence de progrès"


@pytest.mark.asyncio
async def test_the_user_is_told_what_could_not_be_satisfied(judge):
    """Le défaut le plus grave de #288 : le tour se terminait en silence.

    Le second verdict du juge est le texte de rapport qui remplace la réponse
    finale — même ``id``, donc LangGraph le SUBSTITUE au lieu de l'empiler.
    """
    from app.agent.conformity import conformity_node

    judge(
        "ÉCARTS:\n- les marges d'origine ne sont pas reprises",
        "Le document est converti, mais les marges d'origine n'ont pas pu être "
        "conservées. Piste : fournis-moi le PDF avec ses repères de coupe.",
    )
    out = await conformity_node(_turn(retries=1, gap_count=1))

    rapport = out["messages"][0]
    assert isinstance(rapport, AIMessage), "le rapport s'adresse à l'utilisateur"
    assert rapport.id == "final-1", (
        "le rapport doit REMPLACER la réponse finale (même id), pas s'ajouter "
        "après elle"
    )
    assert "marges" in rapport.content
    assert "Piste" in rapport.content


@pytest.mark.asyncio
async def test_the_safety_ceiling_also_produces_a_report(judge):
    """Même quand c'est le plafond qui arrête — et non l'absence de progrès —
    l'utilisateur doit savoir ce qui manque."""
    from app.agent.conformity import conformity_node

    judge("ÉCARTS:\n- une exigence", "Il reste une exigence non satisfaite. Piste : …")
    out = await conformity_node(
        _turn(retries=MAX_CONFORMITY_RETRIES, gap_count=99)
    )

    assert isinstance(out["messages"][0], AIMessage)


@pytest.mark.asyncio
async def test_a_failing_report_call_leaves_the_original_answer_alone(judge, monkeypatch):
    """Échouer OUVERT reste la règle : si l'appel de rapport tombe, on rend la
    réponse telle quelle plutôt que de retenir le tour."""
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )
    appels = {"n": 0}

    async def _fake(*_a, **_k):
        appels["n"] += 1
        if appels["n"] == 1:
            return AIMessage(content="ÉCARTS:\n- les marges")
        raise RuntimeError("modèle indisponible pour le rapport")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _fake)
    out = await conformity_node(_turn(retries=1, gap_count=1))

    assert out.get("messages", []) == []


@pytest.mark.asyncio
async def test_a_conforming_turn_still_costs_a_single_judge_call(monkeypatch):
    """Le cas nominal — de loin le plus fréquent — ne doit pas payer l'appel
    de rapport en plus de celui du juge."""
    from app.agent import conformity as conf
    from app.agent.conformity import conformity_node

    appels = {"n": 0}
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _fake(*_a, **_k):
        appels["n"] += 1
        return AIMessage(content="CONFORME")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _fake)
    out = await conformity_node(_turn())

    assert out.get("messages", []) == []
    assert appels["n"] == 1
