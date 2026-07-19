# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_meta_capability_trigger.py
# @brief      C4-1 — le déclencheur conversationnel du funnel de capacités :
#             les questions MÉTA (« peux-tu créer un outil qui… ») doivent
#             passer par find_tool, pas par une réponse conversationnelle.
# @license    Elastic License 2.0
# =============================================================================
"""C4-1 — cran 1 de la vision « capacité manquante → création → validation ».

Épisode fondateur (17/07/2026, PDF→DOCX) : l'utilisateur demande « peux-tu
créer un outil qui convertit un PDF en .docx ? Considère ça comme une capacité
manquante ». Ely répond honnêtement… en pur conversationnel : la règle prompt
ne couvrait que « il te manque un outil pour LA TÂCHE » — une question MÉTA
ne déclenchait ni find_tool, ni consignation. Zéro trace dans « Capacités
manquantes », zéro signal d'apprentissage.

Ces pins verrouillent : (1) la règle prompt étendue aux questions méta,
(2) l'ancienne règle « pour la tâche » toujours présente, (3) le message
no-match de find_tool qui nomme le panneau où le gap atterrit.

Run with:  cd backend && python -m pytest tests/test_meta_capability_trigger.py -v
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _prompts_src() -> str:
    return (_REPO / "app/agent/prompts.py").read_text(encoding="utf-8")


def test_prompt_covers_meta_capability_questions():
    src = _prompts_src()
    assert "Questions sur tes CAPACITÉS" in src, (
        "La règle méta doit exister : une question « peux-tu créer un outil "
        "qui… » doit déclencher find_tool même SANS tâche à exécuter "
        "(épisode PDF→DOCX du 17/07 : aucune trace consignée)."
    )
    assert "même sans tâche à exécuter" in src
    assert "Capacités manquantes" in src, (
        "Ely doit DIRE à l'utilisateur que le gap est consigné (au lieu d'un "
        "simple « je ne peux pas ») — c'est ce qui rend le funnel visible."
    )


def test_prompt_keeps_the_task_scoped_rule():
    """La règle historique (#56) reste — la méta s'AJOUTE, ne remplace pas."""
    src = _prompts_src()
    assert "Découverte d'outils AVANT d'abandonner" in src
    assert "qu'APRÈS un `find_tool` resté sans résultat pertinent" in src


def test_find_tool_no_match_names_the_gaps_panel():
    src = (_REPO / "app/skills/builtin/find_tool_skill.py").read_text(encoding="utf-8")
    assert "Capacités manquantes" in src, (
        "Le message no-match doit nommer le panneau où le gap est consigné — "
        "le modèle le répète à l'utilisateur, la boucle devient visible."
    )


def test_find_tool_docstring_covers_meta_questions():
    """Le docstring de l'outil guide le modèle au moment du bind — il doit
    couvrir le cas méta, pas seulement l'exécution de tâche."""
    src = (_REPO / "app/skills/builtin/find_tool_skill.py").read_text(encoding="utf-8")
    assert "POSE LA QUESTION" in src, (
        "Le docstring de find_tool doit dire : à appeler AUSSI quand "
        "l'utilisateur demande si la capacité existe (question méta)."
    )
