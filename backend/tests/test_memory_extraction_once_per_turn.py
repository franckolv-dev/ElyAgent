# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_memory_extraction_once_per_turn.py
# @brief      Régression : l'extraction de faits doit partir UNE fois par tour,
#             pas une fois par itération de la boucle d'outils.
# @license    Elastic License 2.0
# =============================================================================
"""L'extraction de faits partait à chaque itération de la boucle d'outils.

Le défaut, mesuré en production le 27/07/2026
---------------------------------------------
``extract_and_store_facts`` était lancé à la fin du **nœud agent**
(``app/agent/nodes.py``). Or le graphe boucle : ``add_edge("tools", "agent")``.
Le nœud agent est donc ré-entré après CHAQUE lot d'outils, et une extraction
partait à chaque passage — sur un contenu quasi identique à chaque fois.

Mesure sur 7 jours glissants :

    memory_extraction ....... 755 appels (74,5 % de TOUS les appels de modèle)
    (chat direct) ............ 27 appels (2,7 %)

Signature de la boucle dans les données : jusqu'à **14 extractions dans la
même minute**, 755 réparties sur 188 minutes seulement. Rendement : 1,79 fait
distinct par appel, 33 % de doublons littéraux, et « L'utilisateur travaille
sur un projet nommé ELY » réécrit 111 fois en une semaine.

Le correctif
------------
Une extraction ne part que lorsque la réponse **termine le tour**, c'est-à-dire
quand elle ne porte pas de ``tool_calls`` (sinon le graphe repasse par
``tools`` puis revient dans le nœud agent).

Le cas du tour tronqué est couvert aussi : quand le budget d'itérations est
épuisé, ``should_continue`` route vers ``force_summary`` et TOUTES les réponses
du nœud agent portent des ``tool_calls``. Sans extraction dans
``force_summary_node``, ce tour-là n'aurait plus AUCUNE extraction — on
échangerait une redondance contre une perte. ``force_summary_node`` en émet
donc une, et sa réponse ne porte jamais de ``tool_calls`` par construction
(l'appel se fait sans ``bind_tools``).

Invariant visé, tous chemins confondus : **exactement une extraction par tour**.

⚠️ CE QUI A CHANGÉ DEPUIS (02/09/2026)
--------------------------------------
Une extraction par tour, c'était encore trop cher : sur 30 jours glissants,
l'extraction pesait 336 appels de modèle contre 208 demandes web réelles. Le
chemin par tour est donc **débranché par défaut** et remplacé par une passe
quotidienne qui groupe tout en un appel par utilisateur
(``extract_new_facts_for_user``).

Ce fichier n'est pas caduc pour autant : il pin désormais la **porte de
sortie** ``MEMORY_EXTRACTION_PER_TURN=true``, qui rétablit le comportement
décrit ci-dessus. Le drapeau est allumé par une fixture autouse — sans elle,
les tests d'ordonnancement ne verraient plus rien partir, ce qui est
justement le comportement pinné par
``tests/test_extraction_memoire_par_lot.py``.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services.memory_service import (
    maybe_spawn_fact_extraction,
    should_extract_facts,
)


@pytest.fixture(autouse=True)
def _per_turn_extraction(monkeypatch):
    """Rallume le chemin par tour : c'est lui que ce fichier décrit."""
    monkeypatch.setenv("MEMORY_EXTRACTION_PER_TURN", "true")


# ─────────────────────────────────────────────────────────────────────────
# Le prédicat : cette réponse termine-t-elle le tour ?
# ─────────────────────────────────────────────────────────────────────────


def _with_tool_calls() -> AIMessage:
    """Une réponse intermédiaire : le graphe va repasser par ``tools``."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "gmail_list_emails", "args": {}, "id": "call_1"},
        ],
    )


def _final_text() -> AIMessage:
    """La réponse qui termine le tour."""
    return AIMessage(content="Tu as 3 mails non lus.")


def test_response_carrying_tool_calls_does_not_end_the_turn():
    assert should_extract_facts(_with_tool_calls()) is False


def test_bare_text_response_ends_the_turn():
    assert should_extract_facts(_final_text()) is True


def test_empty_tool_calls_list_counts_as_final():
    """``tool_calls=[]`` est le cas normal d'une réponse textuelle chez
    LangChain — il ne doit pas être confondu avec « il reste des outils »."""
    assert should_extract_facts(AIMessage(content="Voilà.", tool_calls=[])) is True


def test_absent_response_extracts_nothing():
    """Défensif : pas de réponse, rien à extraire — et surtout pas de crash
    dans un chemin qui tourne en tâche de fond."""
    assert should_extract_facts(None) is False


# ─────────────────────────────────────────────────────────────────────────
# Le point d'entrée appelé par les nœuds du graphe
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def spawned(monkeypatch) -> list:
    """Intercepte les extractions réellement lancées.

    On ne remplace QUE l'appel LLM (``extract_and_store_facts``) : le vrai
    ``spawn`` tourne, donc on exerce le vrai chemin d'ordonnancement en tâche
    de fond. Les tests appellent ``await drain()`` pour laisser la tâche
    s'exécuter avant d'affirmer quoi que ce soit.
    """
    calls: list[tuple] = []

    async def _fake_extract(user_id, conversation_id, messages):
        calls.append((user_id, conversation_id, list(messages)))

    monkeypatch.setattr(
        "app.services.memory_service.extract_and_store_facts", _fake_extract
    )
    return calls


async def drain() -> None:
    """Cède la main pour que les tâches de fond déjà planifiées s'exécutent."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_no_extraction_while_the_tool_loop_is_still_running(spawned):
    scheduled = maybe_spawn_fact_extraction(
        "user-1", [HumanMessage(content="mes mails ?")], _with_tool_calls()
    )
    await drain()
    assert scheduled is False
    assert spawned == []


@pytest.mark.asyncio
async def test_one_extraction_when_the_turn_ends(spawned):
    assert (
        maybe_spawn_fact_extraction(
            "user-1", [HumanMessage(content="mes mails ?")], _final_text()
        )
        is True
    )
    await drain()
    assert len(spawned) == 1
    assert spawned[0][0] == "user-1"


@pytest.mark.asyncio
async def test_anonymous_turn_extracts_nothing(spawned):
    """Sans ``user_id`` il n'y a pas de mémoire à alimenter."""
    assert maybe_spawn_fact_extraction("", [HumanMessage(content="?")], _final_text()) is False
    await drain()
    assert spawned == []


@pytest.mark.asyncio
async def test_the_final_response_is_included_in_what_gets_extracted(spawned):
    """Ce que le modèle a répondu fait partie du tour — l'extraction doit le voir."""
    history = [HumanMessage(content="je bosse sur Ely")]
    final = _final_text()
    maybe_spawn_fact_extraction("user-1", history, final)
    await drain()
    _, _, messages = spawned[0]
    assert messages[-1] is final
    assert messages[0] is history[0]


# ─────────────────────────────────────────────────────────────────────────
# LE test de régression : un tour outillé de 5 itérations
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_five_iteration_turn_extracts_once_not_five_times(spawned):
    """Reproduit la boucle telle que le graphe l'exécute réellement.

    Avant le correctif : 5 extractions (une par passage dans le nœud agent).
    C'est ce comportement qui produisait 755 appels de modèle en 7 jours.
    """
    history = [HumanMessage(content="fais le tri dans mes mails")]

    for _ in range(4):                       # agent → tools → agent → tools…
        maybe_spawn_fact_extraction("user-1", history, _with_tool_calls())
    maybe_spawn_fact_extraction("user-1", history, _final_text())  # …→ agent (texte)
    await drain()

    assert len(spawned) == 1, (
        f"{len(spawned)} extractions pour UN tour — la boucle refuit"
    )


# ─────────────────────────────────────────────────────────────────────────
# Le tour tronqué : force_summary doit reprendre le relais
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_capped_turn_still_extracts_once_via_force_summary(spawned, monkeypatch):
    """Budget d'itérations épuisé : toutes les réponses du nœud agent portent
    des ``tool_calls``, donc aucune n'a déclenché d'extraction. C'est
    ``force_summary_node`` qui doit en émettre une — sinon le tour entier
    passe à la trappe.

    On force l'appel LLM à échouer : le nœud retombe alors sur son
    ``AIMessage`` de repli, ce qui exerce le vrai chemin de sortie sans
    dépendre d'un modèle.
    """
    from app.agent import force_summary as fs

    # ``get_llm_for_tier`` / ``classify_complexity`` sont importés DANS la
    # fonction : c'est le module d'origine qu'il faut patcher, pas ``fs``.
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        "app.services.llm_provider.classify_complexity", lambda *_a, **_k: None
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("pas de modèle en test")

    # Celui-ci est bien un import de niveau module dans force_summary.py.
    monkeypatch.setattr(fs, "ainvoke_with_deadline", _boom)

    history = [HumanMessage(content="tâche interminable")]
    for _ in range(3):
        maybe_spawn_fact_extraction("user-1", history, _with_tool_calls())
    await drain()
    assert spawned == []

    out = await fs.force_summary_node(
        {"messages": history, "user_id": "user-1", "iteration_count": 80}
    )
    await drain()

    assert out["messages"], "force_summary doit toujours rendre une réponse"
    assert len(spawned) == 1, "le tour tronqué a perdu son extraction"
