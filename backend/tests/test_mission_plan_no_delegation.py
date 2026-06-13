# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_plan_no_delegation.py
# @brief      Garde-fou 13/06 : le planificateur de mission EXÉCUTE le travail,
#             il ne le DÉLÈGUE pas à une tâche planifiée. Un goal « tous les
#             matins à 8h, fais X » doit produire un plan qui FAIT X, pas un
#             plan qui crée une scheduler_create_task.
# @license    Elastic License 2.0
# =============================================================================
"""Run with:  cd backend && python -m pytest tests/test_mission_plan_no_delegation.py -v"""
from __future__ import annotations

from app.agent.missions.nodes import _PLAN_SYSTEM, _build_plan_system


def test_plan_system_forbids_scheduler_delegation():
    sys = _PLAN_SYSTEM.lower()
    # Le prompt doit explicitement interdire la délégation / re-planification.
    assert "scheduler_create_task" in sys
    assert "ne crée jamais" in sys or "ne crée pas" in sys
    # Et expliquer que la récurrence du goal est gérée ailleurs.
    assert "récurrence" in sys


def test_build_plan_system_keeps_the_guardrail():
    rendered = _build_plan_system(
        date_str="vendredi 13 juin 2026, 09:00",
        tools_catalog="- web_search\n- desktop_write_file\n- scheduler_create_task",
        n_tools=3,
    )
    assert "TU EXÉCUTES LE TRAVAIL MAINTENANT" in rendered
    assert "scheduler_create_task" in rendered  # cité dans la règle d'interdiction
