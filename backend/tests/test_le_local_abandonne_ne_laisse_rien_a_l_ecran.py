# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_le_local_abandonne_ne_laisse_rien_a_l_ecran.py
# @brief      Les tokens d'une voie locale abandonnée sont retirés de la
#             réponse, de l'écran et de l'historique.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""19/09/2026 — « Quelle heure est-il en Californie actuellement », sur mobile :

    <function name="web_search"><param name="query">heure actuelle CalifornieIl
    est actuellement 8 h 06 en Californie, soit 9 heures de moins qu'à Paris.

MiniCPM (niveau A) a été coupé par le délai de 25 s au milieu de son appel
d'outil. GPT-5.6 a pris le relais et bien répondu. Mais `routers/chat.py`
ajoute à la réponse CHAQUE token streamé par n'importe quel modèle du nœud, et
rien ne retirait ceux du modèle abandonné : le texte du cloud venait se coller
derrière, à l'écran ET dans l'historique (retrouvé tel quel dans la requête
suivante envoyée à LM Studio).

Quelques minutes plus tard la même question est sortie propre : l'appel avait
abouti en 22 s, et un `on_tool_start` purge le préambule. Seul l'abandon SANS
outil fuyait — délai dépassé, erreur, appel écrit en texte non repêché.

Le correctif : le nœud signale l'abandon DANS le flux d'événements, à sa place
chronologique ; le routeur retire ce que ce passage-là avait streamé, et dit à
l'interface de vider son affichage.
"""
from __future__ import annotations

import inspect
import pathlib
from typing import TypedDict

import pytest

_RACINE = pathlib.Path(__file__).parent.parent.parent


# ── 1. Retirer un passage, et lui seul ─────────────────────────────────────


def test_only_the_abandoned_pass_is_removed():
    from app.agent.local_abandonne import retirer_le_passage

    ai, synthese, retire = retirer_le_passage(
        "Préambule. <function name=", "<function name=", (11, 0),
    )
    assert (ai, synthese, retire) == ("Préambule. ", "", "<function name=")


def test_nothing_streamed_means_nothing_removed():
    from app.agent.local_abandonne import retirer_le_passage

    assert retirer_le_passage("déjà là", "déjà là", (7, 7)) == ("déjà là", "déjà là", "")


def test_a_mark_older_than_a_tool_purge_does_not_break():
    """`on_tool_start` vide la synthèse : la marque peut dépasser sa longueur."""
    from app.agent.local_abandonne import retirer_le_passage

    ai, synthese, _ = retirer_le_passage("abc", "", (1, 40))
    assert (ai, synthese) == ("a", "")


# ── 2. Le signal arrive À SA PLACE dans le flux ────────────────────────────


@pytest.mark.asyncio
async def test_the_signal_lands_between_the_local_tokens_and_the_cloud_ones():
    """Tout le correctif repose sur cet ordre. Un signal lu en fin de tour (la
    file du toast) arriverait trop tard pour savoir QUELS tokens retirer."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, StateGraph

    from app.agent.local_abandonne import EVENEMENT, retirer_le_passage, signaler

    local = GenericFakeChatModel(messages=iter([AIMessage(content='<function name="web_search"><param')]))
    cloud = GenericFakeChatModel(messages=iter([AIMessage(content="Il est 8 h 06 en Californie.")]))

    class _Etat(TypedDict):
        reponse: str

    async def general(_etat):
        await local.ainvoke("quelle heure ?")     # la voie locale écrit…
        await signaler()                          # …puis elle est abandonnée
        return {"reponse": (await cloud.ainvoke("quelle heure ?")).content}

    g = StateGraph(_Etat)
    g.add_node("general", general)
    g.set_entry_point("general")
    g.add_edge("general", END)

    ai = synthese = ""
    marque = (0, 0)
    resets = 0
    async for ev in g.compile().astream_events({"reponse": ""}, version="v2"):
        if ev["event"] == "on_chat_model_start":
            marque = (len(ai), len(synthese))
        elif ev["event"] == "on_chat_model_stream" and ev["data"]["chunk"].content:
            ai += ev["data"]["chunk"].content
            synthese += ev["data"]["chunk"].content
        elif ev["event"] == "on_custom_event" and ev["name"] == EVENEMENT:
            ai, synthese, retire = retirer_le_passage(ai, synthese, marque)
            assert "<function" in retire
            resets += 1

    assert resets == 1
    assert ai == synthese == "Il est 8 h 06 en Californie."


@pytest.mark.asyncio
async def test_signalling_outside_a_graph_never_raises():
    """Les tâches planifiées et les tests appellent le nœud hors flux."""
    from app.agent.local_abandonne import signaler

    await signaler()


# ── 3. Le câblage, des trois côtés ─────────────────────────────────────────


def test_every_local_fallback_signals_the_abandonment():
    from app.agent import nodes

    annonce = inspect.getsource(nodes._annoncer_repli_slm)
    assert "await signaler()" in annonce
    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]
    assert bloc.count("await _annoncer_repli_slm(") == bloc.count("_annoncer_repli_slm(") >= 3


def test_the_chat_router_removes_the_pass_and_tells_the_client():
    src = (_RACINE / "backend/app/routers/chat.py").read_text()
    assert '"on_chat_model_start"' in src and "_marque_passage" in src
    assert '"on_custom_event"' in src and "retirer_le_passage(" in src
    assert '"type": "stream_reset"' in src


def test_the_chat_page_clears_what_it_was_showing():
    page = (_RACINE / "frontend/src/app/chat/page.tsx").read_text()
    bloc = page.split('msg.type === "stream_reset"', 1)
    assert len(bloc) == 2, "l'interface ignore stream_reset"
    assert 'setStreamingContent("")' in bloc[1][:400]
