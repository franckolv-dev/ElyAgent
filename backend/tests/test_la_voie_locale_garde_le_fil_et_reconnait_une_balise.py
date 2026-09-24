# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_la_voie_locale_garde_le_fil_et_reconnait_une_balise.py
# @brief      La voie locale lie ses outils sur le fil de la conversation, et
#             une balise d'appel au nom inventé est un échec, pas une réponse.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Conversation 2918577f, 23/09/2026, en production.

    « Ajoute un rendez-vous à mon agenda pour demain matin 9h30 … »
    → « Quelle durée ? »            (gemma, calendar_create_event lié)
    « 30mn »
    → <tool_call>
      add_calendar_event(start_time="2026-09-10 09:30:00", …)
      </tool_call>                   (gemma, rendu tel quel, persisté)

Deux défauts dans le second tour.

1. La voie locale liait ses outils d'après le DERNIER message humain. « 30mn »
   ne réclame rien : plus aucun outil calendrier, alors que le tour d'avant
   les avait. Le modèle a inventé `add_calendar_event`.

2. Il l'a écrit dans une balise `<tool_call>` avec un nom qui n'existe pas.
   Les deux détecteurs exigeaient un nom RÉEL : ni récupéré, ni bascule au
   cloud, le texte est parti à l'écran et dans l'historique. Or une balise
   d'appel n'est jamais une réponse, quel que soit le nom qu'elle porte.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.agent import nodes
from app.agent.tool_call_recovery import looks_like_an_unexecuted_tool_call


class _Registry:
    def __init__(self, noms):
        self.all_tools = [SimpleNamespace(name=n) for n in noms]


_FIL = [
    {"role": "user", "content": "Ajoute un rendez-vous à mon agenda pour demain matin 9h30 dont l'objet est appelé le médecin"},
    {"role": "assistant", "content": "Pour créer cet événement, j'ai besoin de la durée prévue."},
    {"role": "user", "content": "30mn"},
]


def test_le_fil_humain_garde_les_demandes_recentes_dans_l_ordre():
    fil = nodes._demandes_humaines_recentes(_FIL)
    assert fil.index("Ajoute un rendez-vous") < fil.index("30mn")
    assert "durée prévue" not in fil


def test_le_fil_humain_est_borne():
    longue = [{"role": "user", "content": f"demande {i}"} for i in range(10)]
    fil = nodes._demandes_humaines_recentes(longue, n=3)
    assert "demande 9" in fil and "demande 7" in fil and "demande 6" not in fil


def test_un_message_court_ne_fait_pas_perdre_les_outils_du_tour_d_avant():
    registry = _Registry(list(nodes._SLM_TOOL_NAMES) + ["calendar_create_event", "calendar_quick_add"])
    seul = {t.name for t in nodes._slm_toolset(registry, "30mn")}
    assert "calendar_create_event" not in seul  # le défaut, à l'état pur
    fil = {t.name for t in nodes._slm_toolset(registry, nodes._demandes_humaines_recentes(_FIL))}
    assert {"calendar_list_events", "calendar_create_event"} <= fil


def test_la_liaison_locale_lit_le_fil_pas_le_dernier_message():
    src = inspect.getsource(nodes.create_agent_node)
    assert "_slm_toolset(registry, _fil_humain)" in src
    assert "_slm_discovered_extras(registry, _conv_id_fb, _fil_humain)" in src
    # Le routeur, lui, garde la DERNIÈRE demande : sa décision du 23/08.
    assert "intent_router.route(_a_router" in src


@pytest.mark.parametrize("texte, attendu", [
    ('<tool_call>\nadd_calendar_event(start_time="2026-09-10 09:30:00", title="Médecin")\n</tool_call>',
     "add_calendar_event"),
    ('<tool_call>{"name": "envoyer_mail", "arguments": {"to": "x"}}</tool_call>', "envoyer_mail"),
    ('<function_call>{"name":"meteo_demain","arguments":"{}"}</function_call>', "meteo_demain"),
    ('<function name="meteo_demain"><param name="ville">Nantes</param></function>', "meteo_demain"),
])
def test_une_balise_d_appel_au_nom_inconnu_est_un_echec(texte, attendu):
    assert looks_like_an_unexecuted_tool_call(texte, {"calendar_create_event", "weather_get"}) == attendu


def test_une_mention_nue_d_un_nom_inconnu_reste_une_phrase():
    reels = {"calendar_create_event"}
    assert looks_like_an_unexecuted_tool_call("Je peux utiliser print() pour ça.", reels) is None
    assert looks_like_an_unexecuted_tool_call("foo_bar(x=1)", reels) is None
    assert looks_like_an_unexecuted_tool_call("calendar_create_event(title='x')", reels) == "calendar_create_event"
