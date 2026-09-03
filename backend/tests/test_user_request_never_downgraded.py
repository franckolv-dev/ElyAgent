# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_user_request_never_downgraded.py
# @brief      Une demande de l'utilisateur ne descend jamais sous le modèle
#             principal, et voit toujours ses outils.
# @license    MIT
# =============================================================================
"""Le routeur dégradait les demandes, et cachait les outils.

Le défaut, mesuré le 27/07/2026
--------------------------------
``classify_complexity`` choisissait le modèle avec **des regex de mots-clés et
un compte de mots, sans aucun appel LLM**. Testé contre les vraies demandes de
Franck, le classement était **inversé par rapport à la difficulté réelle** :

    « Traduis ce document en gardant exactement la mise en page »  (12 mots)
        → SIMPLE   → Gemma-4-E4B en LOCAL en tête de chaîne
    « Convertis ce PDF en Word sans perte de mise en page, marges… » (26 mots)
        → MEDIUM   → GPT-5.6 puis DeepSeek **Flash**
    « refactor cette fonction python »                              (4 mots)
        → COMPLEX  → GPT-5.6 → Kimi K3 → DeepSeek **Pro**

Et le tier ne pilotait pas que le modèle : il pilotait aussi le **branchement
des outils**. Hors tier COMPLEX, l'agent ne voyait ses outils que si la demande
matchait une regex de 40 lignes, patchée à répétition. Les commentaires du code
en portaient l'aveu : « the LLM said "I have no tool for that" while
browser_history_search … were sitting right there ».

``convertis`` et ``transforme`` n'y figuraient pas. La demande qui a déclenché
tout ce chantier n'avait donc **aucun outil branché**.

La justification d'origine — « the supervisor already routes tool-needing
queries to sub-agents » — était périmée : le superviseur a été supprimé
(mono-agent depuis le 26/07).

Le correctif
------------
Décision de Franck (27/07) : **un seul modèle principal, comme Hermes** — dont
le code ne contient aucun routeur de complexité. Une demande formulée par
l'utilisateur part toujours sur la chaîne la plus capable ; les petits modèles
et le local ne servent plus que les corvées de fond, qui demandent leur tier
explicitement (``MAINTENANCE``, ``SKILL``) sans passer par le classement.

``IMAGE`` survit : ce n'est pas un niveau de difficulté, c'est une capacité
distincte (génération d'images).
"""
from __future__ import annotations

import pytest

from app.agent.routing import should_bind_tools
from app.services.llm_provider import ComplexityTier, classify_complexity


# Les demandes réellement formulées par Franck qui étaient dégradées.
_DEMANDES_DEGRADEES = [
    "Traduis ce document en anglais en gardant exactement la mise en page",
    "Convertis ce PDF en Word sans perte de mise en page, en gardant la taille, "
    "les marges, les polices, les couleurs et les tailles de caractère",
    "convertis ce pdf en docx",
    "Fais-moi un tableau comparatif des offres de mes 3 fournisseurs",
    "transforme ce fichier en présentation",
    "résume-moi ça",
    "bonjour",
]


@pytest.mark.parametrize("demande", _DEMANDES_DEGRADEES)
def test_no_user_request_is_routed_below_the_main_model(demande):
    assert classify_complexity(demande) is ComplexityTier.COMPLEX, (
        f"« {demande[:50]}… » repart sur un modèle dégradé"
    )


def test_image_generation_keeps_its_own_lane():
    """IMAGE n'est pas un niveau de difficulté mais une capacité : le modèle
    principal ne sait pas forcément produire une image."""
    assert classify_complexity("génère une image d'un chat astronaute") is ComplexityTier.IMAGE


def test_the_word_counter_no_longer_decides():
    """Le défaut d'origine : une demande courte était réputée facile. Deux
    formulations de la MÊME demande doivent désormais atterrir au même endroit."""
    courte = classify_complexity("convertis ce pdf en docx")
    longue = classify_complexity(
        "Convertis ce PDF en Word sans perte de mise en page, en gardant la "
        "taille, les marges, les polices, les couleurs et les tailles de "
        "caractère, et dis-moi ce qui n'a pas pu être conservé"
    )
    assert courte is longue is ComplexityTier.COMPLEX


def test_background_chores_keep_their_own_tier():
    """Les corvées de fond ne passent pas par le classement : elles demandent
    ``MAINTENANCE`` explicitement (mémoire, résumés, titres). Ce lot ne doit pas
    les faire monter en gamme — c'est tout l'intérêt d'avoir libéré ce budget.

    Le classement ne doit donc jamais rendre MAINTENANCE de lui-même : ce tier
    n'appartient pas aux demandes de l'utilisateur.
    """
    assert ComplexityTier.MAINTENANCE.value == "maintenance"
    for demande in _DEMANDES_DEGRADEES:
        assert classify_complexity(demande) is not ComplexityTier.MAINTENANCE


# ─────────────────────────────────────────────────────────────────────────
# Les outils : plus jamais cachés à une demande de l'utilisateur
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("demande", _DEMANDES_DEGRADEES)
def test_a_user_request_always_sees_its_tools(demande):
    """Le cœur du « je n'ai pas l'outil » : les outils n'étaient branchés que
    sur tier COMPLEX ou sur match d'une regex de mots-clés."""
    assert should_bind_tools(
        classify_complexity(demande),
        has_profile=False,
        automated_task=False,
        user_query=demande,
    ) is True


def test_tools_are_bound_even_when_no_keyword_matches():
    """La régression précise : « convertis » n'était dans aucune liste. Le
    branchement ne doit plus dépendre du vocabulaire employé."""
    assert should_bind_tools(
        ComplexityTier.COMPLEX,
        has_profile=False,
        automated_task=False,
        user_query="zzzz qwerty azerty",   # aucun mot-clé métier
    ) is True


def test_a_sticky_toolset_profile_still_forces_binding():
    """Comportement conservé : un profil collant branche ses outils quel que
    soit le tier, pour que le modèle apprenne un catalogue stable."""
    assert should_bind_tools(
        ComplexityTier.SIMPLE,
        has_profile=True,
        automated_task=False,
        user_query="bonjour",
    ) is True


def test_an_automated_task_still_forces_binding():
    """Les tâches planifiées tournent sur le graphe flat avec
    ``automated_task=True`` et doivent voir tous les outils que leur consigne
    nomme (régression du briefing quotidien, 2026-05-31)."""
    assert should_bind_tools(
        ComplexityTier.SIMPLE,
        has_profile=False,
        automated_task=True,
        user_query="briefing du matin",
    ) is True
