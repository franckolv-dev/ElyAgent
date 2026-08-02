# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_no_replay_of_committing_actions.py
# @brief      Une reprise de conformité ne doit pas renvoyer ce qui est parti.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Le 02/08, Franck reçoit son briefing du matin QUATRE fois.

Mesuré dans les journaux du conteneur :

```
09:00:59   telegram_send_message      ← Ely appelle l'outil
09:02:16   telegram_send_message      ← la vérification a relancé le tour
09:02:37   telegram_send_message      ← et encore
09:04:23   livraison du planificateur ← puis le planificateur livre à son tour
```

Le planificateur n'a tourné qu'une fois. Les trois premiers envois viennent de
la boucle de conformité (#288/#289) : elle juge la réponse non conforme, relance
le tour — et le tour **rejoue l'envoi**.

👉 Une reprise peut refaire un CALCUL ; elle ne peut pas défaire un ACTE. Ce qui
est parti est parti, et le renvoyer ne corrige rien : ça duplique.

La classification existe déjà (#296) : ``effect_of("telegram_send_message")``
rend ``ENGAGEANT``, indépendamment de l'approbation — Franck a explicitement
décidé de ne PAS mettre Telegram sous garde HITL (« je ne vais pas valider à Ely
les messages qu'elle m'envoie »). Ce que l'outil EST reste séparé de ce qui
exige un accord.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _appel(nom: str, cid: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": nom, "args": {}, "id": cid}])


def _retour(cid: str, texte: str = "Message envoyé.", *, echec: bool = False):
    return ToolMessage(content=texte, tool_call_id=cid,
                       status="error" if echec else "success")


# ---------------------------------------------------------------------------
# Ce qui est déjà parti
# ---------------------------------------------------------------------------

def test_a_committing_action_that_succeeded_is_seen_as_done():
    from app.agent.replay_guard import engaging_actions_done

    messages = [
        HumanMessage(content="Prépare le daily et livre-le sur Telegram"),
        _appel("telegram_send_message", "c1"),
        _retour("c1"),
    ]

    assert engaging_actions_done(messages) == {"telegram_send_message"}


def test_a_read_only_tool_is_never_seen_as_a_committing_action():
    """`web_search` est LECTURE : le rejouer ne coûte qu'un aller-retour."""
    from app.agent.replay_guard import engaging_actions_done

    messages = [_appel("web_search", "c1"), _retour("c1", "3 résultats")]

    assert engaging_actions_done(messages) == set()


def test_a_committing_action_that_FAILED_is_not_seen_as_done():
    """⚠️ Le sens de l'erreur compte.

    Bloquer un envoi qui a échoué priverait Franck de son message — visible et
    irrattrapable dans le tour. Autoriser une reprise après un vrai échec, au
    pire, renvoie un message qui n'était jamais parti. La prudence va donc du
    côté de « pas encore fait ».
    """
    from app.agent.replay_guard import engaging_actions_done

    messages = [_appel("telegram_send_message", "c1"),
                _retour("c1", "Erreur : chat_id introuvable", echec=True)]

    assert engaging_actions_done(messages) == set()


def test_an_error_text_without_the_error_status_is_still_a_failure():
    """Les outils d'Ely rendent « Erreur : … » en texte, sans lever."""
    from app.agent.replay_guard import engaging_actions_done

    messages = [_appel("telegram_send_message", "c1"),
                _retour("c1", "Erreur : selector_not_found.")]

    assert engaging_actions_done(messages) == set()


# ---------------------------------------------------------------------------
# Quand le garde s'applique — et quand il ne doit PAS s'appliquer
# ---------------------------------------------------------------------------

def test_the_guard_only_bites_after_a_verification_bounce():
    """⚠️ Le pin qui compte le plus.

    « Envoie un mail à Paul et un à Marie » est UN tour avec DEUX envois
    légitimes. Retirer l'outil dès le premier appel casserait cette demande.
    Le garde ne vise que le REJEU imposé par la vérification, pas la boucle
    normale agent → outils → agent.
    """
    from app.agent.replay_guard import should_withhold

    envoye = [_appel("telegram_send_message", "c1"), _retour("c1")]

    assert should_withhold(envoye) == set(), (
        "sans reprise de vérification, rien n'est retiré — un tour a le droit "
        "d'envoyer deux messages"
    )


def test_after_a_verification_bounce_a_sent_message_is_withheld():
    from app.agent.replay_guard import RETRY_MARKER, should_withhold

    messages = [
        HumanMessage(content="Prépare le daily et livre-le sur Telegram"),
        _appel("telegram_send_message", "c1"),
        _retour("c1"),
        HumanMessage(content=f"{RETRY_MARKER} — la demande n'est pas encore satisfaite]"),
    ]

    assert should_withhold(messages) == {"telegram_send_message"}


def test_the_marker_is_the_one_conformity_actually_writes():
    """Deux constantes qui doivent coïncider, sinon le garde ne mord jamais.

    Épingler la PROPRIÉTÉ (« c'est le même marqueur ») plutôt que la valeur :
    changer le texte de la relance ne doit pas désarmer le garde en silence.
    """
    from app.agent import conformity
    from app.agent.replay_guard import RETRY_MARKER

    assert conformity._RETRY_MARKER == RETRY_MARKER
    assert RETRY_MARKER in conformity._RETRY_TEMPLATE


def test_a_read_only_tool_is_never_withheld_even_after_a_bounce():
    """Une reprise doit pouvoir RE-chercher : c'est tout l'intérêt."""
    from app.agent.replay_guard import RETRY_MARKER, should_withhold

    messages = [
        _appel("web_search", "c1"), _retour("c1", "3 résultats"),
        HumanMessage(content=f"{RETRY_MARKER} …]"),
    ]

    assert should_withhold(messages) == set()


# ---------------------------------------------------------------------------
# Le câblage — un garde non branché ne garde rien
# ---------------------------------------------------------------------------

def test_the_guard_is_actually_wired_into_the_binding():
    """⚠️ Le pin qui empêche ce lot d'être décoratif.

    Un module correct que personne n'appelle est exactement le défaut qu'on a
    passé la semaine à traquer : `find_tool` en filet qui se trompait une fois
    sur deux, `config_reality` qui testait la constructibilité. Le nœud `agent`
    doit appeler `should_withhold` sur les messages de l'état, au même endroit
    que les autres retraits (extension Chrome, tier C).

    ⚠️ **Ce pin épingle le MÉCANISME, pas la propriété** — il relit la source.
    C'est précisément ce qu'on s'est interdit ailleurs, et il faut le dire :
    le branchement vit au milieu d'une fonction de nœud trop grosse pour être
    exercée sans monter tout le graphe. Il tiendra donc mal à un renommage.
    La vraie preuve est ailleurs — le lot est vérifié dans le conteneur sur une
    reprise réelle. Si ce branchement est un jour extrait dans une fonction
    testable, remplacer ce pin par un vrai.
    """
    import inspect

    from app.agent import nodes

    source = inspect.getsource(nodes)
    assert "from app.agent.replay_guard import should_withhold" in source
    assert "should_withhold(state.get(\"messages\")" in source, (
        "le garde doit lire les messages de l'ÉTAT — sur une autre source, il "
        "ne verrait jamais l'envoi qui vient d'avoir lieu"
    )
