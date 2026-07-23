# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_generated_lint_contract.py
# @brief      Le lint appliqué au code généré doit être celui du projet, et
#             être ANNONCÉ au modèle qui écrit ce code.
# =============================================================================
"""Banc d'essai tier S du 23/07/2026 — ce que ces tests verrouillent.

Mesure sur 6 tâches réelles, deux modèles : **aucun des deux ne passait au
premier jet**, et les échecs étaient tous cosmétiques (E501/F401), jamais
logiques. Le pire cas : un échec DeepSeek pour une ligne de **89 caractères
contre une limite de 88**, alors que le projet lui-même autorise 120.

Deux défauts se cumulaient :

1. ``run_ruff`` tourne en ``--isolated`` et héritait donc de la longueur de
   ligne PAR DÉFAUT de ruff (88), plus stricte que le ``line-length = 120``
   du projet. Or un outil qui gradue devient un fichier du dépôt, soumis à
   la config du dépôt : le valider à 88 est arbitrairement plus sévère que
   ce qu'on exigera de lui ensuite.

2. Le prompt du générateur ne mentionnait NI la longueur de ligne NI
   l'interdiction des imports inutilisés — le modèle ne pouvait pas savoir.
   Même famille que l'incident initial : le validateur sanctionne une règle
   que la spec passe sous silence.
"""
from __future__ import annotations

from app.services.learning.static_checks import PROJECT_LINE_LENGTH, run_ruff
from app.services.learning.tool_generator import _SYSTEM_PROMPT


# ── Le lint du code généré s'aligne sur celui du projet ──────────────────────
def test_project_line_length_matches_pyproject():
    """Garde-fou : si le projet change sa limite, ce test le rappelle.

    La valeur vit dans backend/pyproject.toml ([tool.ruff] line-length).
    """
    assert PROJECT_LINE_LENGTH == 120


def test_line_between_88_and_project_limit_is_accepted():
    """Le cas exact qui a recalé DeepSeek : une ligne de 89 caractères."""
    line = "x = '" + "a" * 83 + "'"  # 5 + 83 + 1 = 89
    assert len(line) == 89
    assert 88 < len(line) <= PROJECT_LINE_LENGTH

    report = run_ruff(f"{line}\n")

    assert report.ok, report.summary()


def test_line_over_the_project_limit_is_still_rejected():
    """On aligne la limite, on ne la supprime pas."""
    line = "x = '" + "a" * 140 + "'"
    assert len(line) > PROJECT_LINE_LENGTH

    report = run_ruff(f"{line}\n")

    assert not report.ok
    assert "E501" in report.summary()


def test_unused_import_is_still_rejected():
    """F401 reste une erreur — c'est du code mort dans un outil livré."""
    report = run_ruff("import json\n\nx = 1\n")

    assert not report.ok
    assert "F401" in report.summary()


# ── Le modèle doit être PRÉVENU de ces règles ────────────────────────────────
def test_prompt_states_the_line_length_limit():
    assert str(PROJECT_LINE_LENGTH) in _SYSTEM_PROMPT
    assert "E501" in _SYSTEM_PROMPT


def test_prompt_forbids_unused_imports():
    assert "F401" in _SYSTEM_PROMPT
