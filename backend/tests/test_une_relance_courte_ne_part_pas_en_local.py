# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_relance_courte_ne_part_pas_en_local.py
# @brief      Une relance qui renvoie au passé de la conversation, ou dont
#             l'historique ne tient pas dans la fenêtre du modèle local,
#             part au cloud.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Ce que ça corrige (tests « Ely dans ses retranchements », 05/09/2026).

« annule ce que tu viens de faire » et « où en es-tu de ce que je t'avais
demandé sur les factures ? » ont été répondus par le modèle LOCAL : deux
demandes courtes, notées simples par le routeur d'intention. Or elles ne
veulent rien dire sans l'historique — que la voie locale ne voit pas : elle
ne charge pas la mémoire, et sa fenêtre ne contenait plus la demande sur les
factures, 96 messages plus haut. Résultat : une annulation affirmée sans
outil, et « je n'ai aucune trace d'une demande concernant des factures ».

Deux règles :
- une demande qui RENVOIE au passé (« ce que tu viens de faire », « où en
  es-tu », « annule », « recommence »…) va au cloud, quel que soit son score ;
- si l'historique ne tient pas entier dans la fenêtre du modèle local, la
  voie locale n'est pas prise — un modèle qui n'a pas vu la conversation ne
  peut pas la continuer.

Run with:  cd backend && python -m pytest tests/test_une_relance_courte_ne_part_pas_en_local.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services.intent_router import IntentRouter, ModelTier


def _slm_on(threshold: int = 55):
    s = MagicMock()
    s.slm_enabled = True
    s.slm_complexity_threshold = threshold
    return s


def _route(texte: str):
    with patch("app.config.get_settings", return_value=_slm_on()):
        return IntentRouter().route(texte)


@pytest.mark.parametrize("texte", [
    "annule ce que tu viens de faire",
    "Où en es-tu de ce que je t'avais demandé sur les factures ?",
    "recommence",
    "refais-le",
    "et ensuite ?",
    "continue",
    "reprends où tu en étais",
    "défais la dernière action",
    "pareil pour demain",
    "tu as fini ?",
])
def test_une_relance_qui_renvoie_au_passe_va_au_cloud(texte):
    d = _route(texte)
    assert d.tier == ModelTier.LLM, f"{texte!r} est parti en local : {d.reason}"
    assert "historique" in d.reason.lower()


@pytest.mark.parametrize("texte", [
    "météo à Nantes",
    "traduis bonjour en anglais",
    "mon agenda de demain",
])
def test_une_demande_simple_et_autonome_reste_locale(texte):
    d = _route(texte)
    assert d.tier == ModelTier.SLM, f"{texte!r} a fui au cloud : {d.reason}"


def test_l_historique_qui_deborde_de_la_fenetre_locale_ecarte_la_voie_locale():
    from app.agent.nodes import _historique_deborde

    long_fil = []
    for i in range(40):
        long_fil.append(HumanMessage(content=f"demande {i} " + "x" * 1200))
        long_fil.append(AIMessage(content=f"réponse {i} " + "y" * 1200))
    long_fil.append(HumanMessage(content="où en es-tu ?"))

    # 8 192 tokens de fenêtre par défaut pour un nom inconnu : 40 échanges de
    # 600 tokens n'y tiennent pas.
    assert _historique_deborde(long_fil, "modele-inconnu-8k") is True


def test_un_fil_court_tient_dans_la_fenetre_locale():
    from app.agent.nodes import _historique_deborde

    court = [HumanMessage(content="météo ?"), AIMessage(content="Beau temps."),
             HumanMessage(content="et demain ?")]
    assert _historique_deborde(court, "modele-inconnu-8k") is False


def test_le_noeud_agent_ecarte_la_voie_locale_quand_l_historique_deborde():
    """Pin de câblage (même geste que `test_general_node_traces_slm_and_turn`) :
    le garde est appelé dans le bloc de routage, sur la décision SLM."""
    import inspect

    import app.agent.nodes as nodes

    src = inspect.getsource(nodes)
    assert "if use_slm and _historique_deborde(" in src, (
        "le nœud agent ne consulte plus la fenêtre locale avant de prendre la voie locale"
    )
