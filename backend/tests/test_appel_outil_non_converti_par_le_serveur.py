# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_appel_outil_non_converti_par_le_serveur.py
# @brief      Un appel d'outil écrit en texte est EXPLIQUÉ, jamais affiché brut.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""16/09/2026 — MiniCPM 5 sous LM Studio répond à « quelle météo à Poitiers » :

    <function name="weather_get"><param name="location">Poitiers</param></function>

Le repêchage (#403) règle CE format. Mais le prochain modèle aura le sien, et
la personne qui installe Ely avec un modèle non testé lira un appel brut et
conclura qu'Ely ne fonctionne pas. Deux volets :

1. La détection « appel manqué » reconnaît aussi les formes balisées — elle ne
   voyait que `nom(…)`, et le XML de MiniCPM n'a pas de parenthèse.
2. Quand rien n'est repêchable, l'utilisateur lit une EXPLICATION : quel
   modèle, quel outil, quelle forme, et que c'est le serveur qui n'a pas
   converti l'appel — pas Ely.
"""
from __future__ import annotations

import inspect

import pytest

from app.agent.tool_call_recovery import (
    forme_de_l_appel_texte,
    looks_like_an_unexecuted_tool_call,
    message_appel_non_converti,
)

_NOMS = {"weather_get", "find_tool", "gmail_send_email"}


@pytest.mark.parametrize("texte, attendu", [
    ('<function name="weather_get"><param name="location">Poitiers</param></function>', "weather_get"),
    ('<functionname="weather_get"><paramname="location">Poitiers</param></function>', "weather_get"),
    ('<tool_call>{"name": "find_tool", "arguments": {"q": "x"}}</tool_call>', "find_tool"),
    ('<function_call>{"name":"gmail_send_email","arguments":"{}"}</function_call>', "gmail_send_email"),
    ("Je regarde.\n<function name=\'weather_get\'>\n</function>", "weather_get"),
])
def test_a_tagged_call_is_detected_as_unexecuted(texte, attendu):
    assert looks_like_an_unexecuted_tool_call(texte, _NOMS) == attendu


@pytest.mark.parametrize("texte", [
    '<function name="outil_inconnu"><param name="x">1</param></function>',
    "La météo à Poitiers est douce.",
    "",
])
def test_an_unknown_or_absent_call_is_not_detected(texte):
    assert looks_like_an_unexecuted_tool_call(texte, _NOMS) is None


@pytest.mark.parametrize("texte, attendu", [
    ('<function name="weather_get"></function>', "XML <function name=…>"),
    ('<tool_call>{"name": "x"}</tool_call>', "<tool_call>{…}</tool_call>"),
    ('<function_call>{"name": "x"}</function_call>', "<function_call>{…}</function_call>"),
    ('find_tool("sites")', "appel nu nom(…)"),
    ("Bonjour.", None),
])
def test_the_form_of_a_text_call_is_named(texte, attendu):
    assert forme_de_l_appel_texte(texte) == attendu


def test_the_message_says_who_wrote_what_and_that_it_is_not_ely():
    msg = message_appel_non_converti("weather_get", "XML <function name=…>", "minicpm5-2b")
    assert "minicpm5-2b" in msg
    assert "weather_get" in msg
    assert "XML <function name=…>" in msg
    assert "pas converti" in msg
    assert "Ely" in msg


def test_the_cloud_path_explains_an_unrecoverable_text_call():
    """Le volet manquant : la voie cloud repêchait, mais n'expliquait rien."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if response is None:", 1)[1]
    assert "looks_like_an_unexecuted_tool_call(" in bloc
    assert "message_appel_non_converti(" in bloc


def test_the_local_path_names_the_form_in_its_fallback_reason():
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]
    assert "forme_de_l_appel_texte(" in bloc
