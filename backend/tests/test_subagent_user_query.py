# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_subagent_user_query.py
# @brief      La complexité d'un sous-agent se classe sur la QUESTION de
#             l'utilisateur, pas sur le dernier message (résultat d'outil).
# @license    Elastic License 2.0
# =============================================================================
"""Bug prod 18/07/2026 : ``user_query = messages[-1].content`` dans la factory.

Au cycle post-outil, ``messages[-1]`` est un ToolMessage (le blob renvoyé par
l'outil) → ``classify_complexity(<blob>)`` escaladait la SYNTHÈSE vers le tier
C à chaque tour outillé — la synthèse partait sur l'instance codex quel que
soit le routage tier B choisi par l'admin (vu en prod : Telegram muet alors
que DeepSeek venait d'être mis en primary B). Même piège que le bloc
``tool_choice`` du même fichier, qui remonte déjà au dernier HumanMessage.

Run with:  cd backend && python -m pytest tests/test_subagent_user_query.py -v
"""
from __future__ import annotations

import inspect

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.sub_agents.factory import _last_human_query


def test_walks_past_tool_messages_to_the_user_question():
    msgs = [
        HumanMessage(content="Peux tu vérifier si j'ai reçu de nouveaux mails ?"),
        AIMessage(content=""),
        ToolMessage(content="De: a@b.c — Objet: facture — …(gros blob)…", tool_call_id="t1"),
    ]
    assert _last_human_query(msgs) == "Peux tu vérifier si j'ai reçu de nouveaux mails ?"


def test_takes_the_latest_user_message_not_the_first():
    msgs = [
        HumanMessage(content="bonjour"),
        AIMessage(content="salut"),
        HumanMessage(content="liste mes fichiers Drive"),
        ToolMessage(content="42 fichiers…", tool_call_id="t1"),
    ]
    assert _last_human_query(msgs) == "liste mes fichiers Drive"


def test_flattens_content_blocks():
    # Tier codex (Responses API) : content en liste de blocs, même côté user
    # (historique re-masqué). classify_complexity attend une string.
    msgs = [HumanMessage(content=[{"type": "text", "text": "salut Ely"}])]
    assert _last_human_query(msgs) == "salut Ely"


def test_empty_and_no_human_fallbacks():
    assert _last_human_query([]) == ""
    # Pas de HumanMessage (théorique) → retombe sur le dernier message, aplati.
    assert _last_human_query([AIMessage(content="seul")]) == "seul"


def test_factory_keys_user_query_on_the_helper():
    """Pin source : la dérivation ``messages[-1].content`` ne doit pas revenir."""
    import app.agent.sub_agents.factory as factory

    src = inspect.getsource(factory)
    assert "user_query = _last_human_query(messages)" in src
    assert 'user_query = messages[-1].content if messages else ""' not in src
