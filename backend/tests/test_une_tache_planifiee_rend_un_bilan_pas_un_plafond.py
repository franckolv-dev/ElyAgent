# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_tache_planifiee_rend_un_bilan_pas_un_plafond.py
# @brief      Une tâche planifiée qui déborde rend un bilan, plus « Recursion
#             limit of 60 » ; et le juge n'exige pas de relire un Telegram.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""« Traitement factures », seconde exécution du 17/09/2026, Google reconnecté.

À 20:32:55 le travail est FINI en 12 actions : deux mails lus, deux PDF dans
Drive, mails marqués comme lus. Puis le juge de conformité renvoie au travail
(« le dossier n'a pas été relu », « la notification Telegram n'a pas été
relue », « le statut Lu n'a pas été relu »…). Un Telegram ne se relit pas, et
son outil est débranché après le premier envoi : l'exigence est insatisfiable.
Ely tâtonne (7 ``find_tool``, ``system_get_logs``, ``report_missing_capability``)
et la tâche meurt à 20:34:36 sur « Recursion limit of 60 » — travail fait,
résultat perdu, statut « erreur ».

Deux défauts :

1. ``force_summary`` devait garantir un bilan avant le plafond LangGraph. Il
   se déclenche à 80 itérations ; le planificateur plafonne à 60 super-pas,
   soit ~29 itérations. Même bug que celui corrigé pour le chat le 01/06/2026.
2. La règle « une écriture n'est satisfaite que RELUE » n'a pas d'exception
   pour ce qui ne peut pas être relu.

Run with:  cd backend && python -m pytest tests/test_une_tache_planifiee_rend_un_bilan_pas_un_plafond.py -v
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.agent.conformity import MAX_CONFORMITY_RETRIES


def _demande_un_outil() -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "find_tool", "args": {}, "id": "c1"}])


# ── 1. Le bilan forcé arrive AVANT le plafond LangGraph ──────────────────────


@pytest.mark.parametrize("plafond", [25, 60, 120, 200])
def test_le_bilan_force_tient_dans_le_plafond(plafond):
    """Pire cas : T itérations d'outils, puis autant de réponses finales et de
    vérifications que le juge a de reprises (+1), puis le bilan forcé."""
    from app.agent.routing import iterations_avant_plafond

    t = iterations_avant_plafond(plafond)
    rondes_du_juge = MAX_CONFORMITY_RETRIES + 1
    assert t >= 1
    assert 2 * t + 2 * rondes_du_juge + 1 <= max(plafond, 2 * 1 + 2 * rondes_du_juge + 1)


def test_soixante_pas_laissent_vingt_trois_iterations():
    from app.agent.routing import iterations_avant_plafond

    assert iterations_avant_plafond(60) == 23


def test_le_plafond_du_tour_declenche_le_bilan_force():
    from app.agent.routing import should_continue

    etat = {"messages": [_demande_un_outil()], "iteration_count": 23, "max_iterations": 23}
    assert should_continue(etat) == "force_summary"


def test_sans_plafond_de_tour_le_chat_garde_ses_quatre_vingts_iterations():
    from app.agent.routing import should_continue

    etat = {"messages": [_demande_un_outil()], "iteration_count": 23}
    assert should_continue(etat) == "tools"


@pytest.mark.asyncio
async def test_le_planificateur_pose_le_plafond_du_tour(monkeypatch):
    import app.agent.graph as graph_mod
    import app.services.scheduler as sched
    from app.agent.routing import iterations_avant_plafond
    from tests.test_scheduler_status import _seed_task

    from app.database import init_db
    await init_db()
    vu: dict = {}

    class _Agent:
        async def ainvoke(self, state, config=None):
            vu["etat"], vu["config"] = state, config
            return {"messages": [AIMessage(content="rapport produit")]}

    async def _rien(*_a, **_k):
        return None

    monkeypatch.setattr(graph_mod, "build_simple_agent_graph", lambda: _Agent())
    monkeypatch.setattr(sched, "_deliver_result", _rien)

    _uid, tid = await _seed_task()
    await sched._execute_task(tid)

    limite = vu["config"]["recursion_limit"]
    assert vu["etat"]["max_iterations"] == iterations_avant_plafond(limite)


# ── 2. Le juge n'exige pas de relire ce qui ne se relit pas ──────────────────


def test_le_juge_n_exige_pas_de_relire_un_message_envoye_sur_telegram():
    from app.agent.conformity import _JUDGE_PROMPT

    regle = _JUDGE_PROMPT.replace("\n", " ")
    assert "RELUE" in regle, "la règle de relecture des écritures reste"
    assert "Telegram" in regle
    assert "qu'aucun outil ne permet de relire" in regle
