# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_mission_mandate_survives_truncation.py
# @brief      La consigne d'une tâche planifiée ne doit pas être la première
#             chose supprimée quand le contexte déborde.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de l'ancrage du mandat de mission.

**Le mécanisme, lu dans le code.** ``scheduler.py`` passe la consigne d'une
tâche planifiée comme un simple ``HumanMessage`` — donc ``messages[0]``. Et
``fit_messages_to_context`` annonce sa stratégie :

    « Strategy: keep the newest messages and drop from the front. »

La consigne est donc **structurellement la première chose supprimée** dès que
la boucle d'outils fait déborder le contexte. Sur une tâche longue, l'agent
finit son travail sans savoir ce qu'on lui avait demandé.

**L'observation.** Run manuel de la tâche de prospection le 26/07 : 51 appels
d'outils, cinq entreprises trouvées avec pagination et sources — et **zéro
écriture**, alors que la consigne exigeait d'écrire après chaque entreprise.
Ely a livré une « veille » générique : le comportement de quelqu'un qui a
oublié la commande.

**Pourquoi aucune réécriture de consigne ne pouvait corriger ça.** Le texte
est supprimé quoi qu'il dise. Les onze « cette étape est obligatoire » de la
consigne d'origine ne pouvaient pas fonctionner : ils disparaissaient avant
d'être utiles.

**Le choix retenu.** Préserver ``messages[0]`` plutôt que déplacer la consigne
dans le prompt système : le prompt système a un plafond testé (15 000 car.) et
une zone volatile soignée pour le cache ; y injecter une consigne de mission
de plusieurs milliers de caractères casserait les deux. L'ancrage se fait donc
là où le problème est — dans la troncature.

Run with:  cd backend && python -m pytest tests/test_mission_mandate_survives_truncation.py -v
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_MANDATE = (
    "Mission de prospection. Écris CHAQUE entreprise dans le RTF avant de "
    "chercher la suivante. Ne termine jamais sans avoir écrit."
)


def _long_loop(n: int = 60) -> list:
    """Une boucle d'outils réaliste : des résultats volumineux qui chassent
    les messages anciens."""
    out: list = [HumanMessage(content=_MANDATE)]
    for i in range(n):
        out.append(AIMessage(content=f"Je cherche l'entreprise {i}."))
        out.append(HumanMessage(content=f"resultat de recherche {i} — " + "x" * 4000))
    return out


def _has_mandate(messages: list) -> bool:
    return any("Mission de prospection" in str(getattr(m, "content", "")) for m in messages)


# --------------------------------------------------- le défaut, reproduit

def test_without_anchoring_the_mandate_is_dropped():
    """Documente le comportement par défaut — celui qui a fait échouer la
    prospection. Ce test doit rester vert : hors mission, tronquer par
    l'avant est le bon choix."""
    from app.services.context_manager import fit_messages_to_context

    kept = fit_messages_to_context(
        _long_loop(), system_prompt="Tu es Ely.", model="deepseek-chat",
    )

    assert len(kept) < len(_long_loop())
    assert not _has_mandate(kept), (
        "si le mandat survivait déjà, ce lot n'aurait pas lieu d'être"
    )


# ------------------------------------------------------------ l'ancrage

def test_the_mandate_survives_when_anchored():
    """LE test du lot."""
    from app.services.context_manager import fit_messages_to_context

    kept = fit_messages_to_context(
        _long_loop(), system_prompt="Tu es Ely.", model="deepseek-chat",
        preserve_first=True,
    )

    assert _has_mandate(kept), (
        "le mandat a encore été supprimé : la tâche finira sans savoir ce "
        "qu'on lui demandait"
    )
    assert "Mission de prospection" in str(kept[0].content), (
        "le mandat doit rester en TÊTE — une consigne au milieu d'une boucle "
        "d'outils se lit comme un résultat, pas comme un ordre"
    )


def test_anchoring_still_respects_the_budget():
    """L'ancrage ne doit pas rendre la troncature inopérante : on garde le
    mandat, on continue de jeter le reste."""
    from app.services.context_manager import fit_messages_to_context

    msgs = _long_loop()
    kept = fit_messages_to_context(
        msgs, system_prompt="Tu es Ely.", model="deepseek-chat", preserve_first=True,
    )

    assert len(kept) < len(msgs), "rien n'a été tronqué — le budget est ignoré"


def test_anchoring_never_creates_an_orphan_tool_message():
    """Garde-fou provider : un message `tool` dont l'appel a disparu fait
    rejeter la requête entière par DeepSeek et consorts (bug d'audit
    2026-05-15). L'ancrage ne doit pas réintroduire ce cas."""
    from app.services.context_manager import fit_messages_to_context

    msgs: list = [HumanMessage(content=_MANDATE)]
    for i in range(60):
        msgs.append(AIMessage(content="", tool_calls=[
            {"name": "web_search", "args": {"q": str(i)}, "id": f"c{i}"},
        ]))
        msgs.append(ToolMessage(content="resultat " + "y" * 4000, tool_call_id=f"c{i}"))

    kept = fit_messages_to_context(
        msgs, system_prompt="Tu es Ely.", model="deepseek-chat", preserve_first=True,
    )

    assert not isinstance(kept[1], ToolMessage), (
        "le message qui suit le mandat est un résultat d'outil orphelin — "
        "le fournisseur rejettera la requête"
    )


def test_a_short_conversation_is_untouched():
    """Pas d'effet de bord quand rien ne déborde."""
    from app.services.context_manager import fit_messages_to_context

    msgs = [HumanMessage(content=_MANDATE), AIMessage(content="Entendu.")]
    kept = fit_messages_to_context(
        msgs, system_prompt="Tu es Ely.", model="deepseek-chat", preserve_first=True,
    )

    assert len(kept) == 2


# -------------------------------------------- le câblage sur les tâches

def test_the_agent_node_anchors_for_automated_tasks():
    """L'ancrage ne sert à rien s'il n'est jamais demandé. Les tâches
    planifiées le signalent déjà par ``automated_task`` dans l'état."""
    from pathlib import Path

    src = Path("app/agent/nodes.py").read_text(encoding="utf-8")

    assert "preserve_first=" in src, "nodes.py ne demande jamais l'ancrage"
    assert "automated_task" in src


def test_the_scheduler_still_sends_the_mandate_first():
    """L'ancrage préserve ``messages[0]`` : si le planificateur cessait d'y
    mettre la consigne, il préserverait autre chose en silence."""
    from pathlib import Path

    src = Path("app/services/scheduler.py").read_text(encoding="utf-8")

    assert '"messages": [HumanMessage(' in src
