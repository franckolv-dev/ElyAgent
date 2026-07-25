# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_bench_architecture_ab.py
# @brief      V2-2 — verrous du banc A/B : le jeu de tâches et le calcul des
#             agrégats doivent être justes avant de servir à décider de V1.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du banc A/B (`bench/run_architecture_ab.py`).

Ce banc produira le tableau sur lequel Franck tranchera mono-agent contre
sous-agents. Un agrégat faux orienterait la décision — d'où ces verrous sur la
partie pure (jeu de tâches, résumé, restitution), sans appel LLM.

Run with:  cd backend && python -m pytest tests/test_bench_architecture_ab.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parent.parent.parent / "bench"
if str(_BENCH.parent) not in sys.path:
    sys.path.insert(0, str(_BENCH.parent))

from bench.run_architecture_ab import TASKS, Turn, _summarise, render  # noqa: E402


# ------------------------------------------------------------ jeu de tâches

def test_the_task_set_is_large_enough_to_conclude():
    """Le cadrage annonçait 20 à 30 tâches réelles."""
    assert len(TASKS) >= 20


def test_every_task_declares_at_least_one_expected_tool():
    for t in TASKS:
        assert t.expected, f"tâche sans outil attendu : {t.prompt!r}"


def test_expected_tools_allow_several_defensible_answers():
    """« lister » et « chercher » des mails sont tous deux défendables :
    compter comme faux un choix raisonnable fausserait la comparaison."""
    multi = [t for t in TASKS if len(t.expected) > 1]
    assert len(multi) >= 8, "jeu de tâches trop rigide sur la bonne réponse"


def test_tasks_are_unique():
    prompts = [t.prompt for t in TASKS]
    assert len(prompts) == len(set(prompts))


def test_the_task_set_covers_both_dominant_domains():
    """L'usage réel des canaux se partage entre workspace (mail, agenda,
    drive) et research (météo, news). Le banc doit refléter ce mélange —
    sinon il mesure une architecture sur un domaine qu'elle ne sert pas."""
    joined = " ".join(t.prompt.lower() for t in TASKS)
    assert "mail" in joined
    assert "météo" in joined or "meteo" in joined


# ------------------------------------------------------------- agrégats

def _turn(arch="mono", *, ms=100.0, correct=True, tokens=1000, error=None, calls=1):
    return Turn(architecture=arch, task="t", chosen=["x"], correct=correct,
                latency_ms=ms, prompt_tokens=tokens, llm_calls=calls, error=error)


def test_summary_medians_use_only_successful_turns():
    """Un tour en erreur n'a pas de latence : l'inclure tirerait la médiane
    vers zéro et flatterait l'architecture qui échoue."""
    turns = [_turn(ms=100), _turn(ms=200), _turn(ms=0, error="boom")]

    summary = _summarise(turns)

    assert summary["erreurs"] == 1
    assert summary["p50_ms"] == 150.0


def test_summary_counts_the_extra_routing_call():
    """Le surcoût structurel des sous-agents est ce deuxième appel."""
    summary = _summarise([_turn(calls=2), _turn(calls=2)])

    assert summary["appels_llm"] == 4


def test_summary_survives_an_all_error_run():
    summary = _summarise([_turn(error="boom"), _turn(error="boom")])

    assert summary["p50_ms"] == 0.0
    assert summary["erreurs"] == 2


def test_summary_on_an_empty_run_does_not_raise():
    assert _summarise([])["n"] == 0


def test_success_rate_is_computed_on_turns_that_ran():
    """2 corrects sur 3 tours dont 1 en erreur → 2/2, pas 2/3 : un appel qui
    n'a jamais eu lieu n'est pas un mauvais choix d'outil."""
    turns = [_turn(correct=True), _turn(correct=True), _turn(error="boom")]

    summary = _summarise(turns)

    assert summary["reussite_choix"] == 2
    assert summary["n"] - summary["erreurs"] == 2


# ------------------------------------------------------------ restitution

def test_render_states_which_architecture_is_slower():
    mono = [_turn("mono", ms=800)]
    subs = [_turn("sub_agents", ms=2000, calls=2)]

    out = render(mono, subs)

    assert "plus LENTS" in out
    assert "1200 ms" in out or "1 200 ms" in out


def test_render_states_the_limits_of_the_bench():
    """Le banc n'exécute aucun outil : le tableau doit le dire lui-même,
    sinon quelqu'un lira « réussite de la tâche » là où il n'y a que
    « choix d'outil »."""
    out = render([_turn("mono")], [_turn("sub_agents", calls=2)])

    assert "n'exécute AUCUN outil" in out
    assert "multi-étapes" in out


def test_render_does_not_raise_on_an_empty_run():
    assert isinstance(render([], []), str)
