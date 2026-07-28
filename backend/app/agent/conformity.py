# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/conformity.py
# @brief      Vérifier que le résultat répond à la demande, et relancer avec
#             les écarts nommés s'il n'y répond pas.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Le chaînon qui manquait : confronter le retour à la demande.

Ce qui existait, et qui ne couvrait pas ce besoin
--------------------------------------------------
- ``completion_guard`` détecte les affirmations **non étayées par un appel
  d'outil** (« j'ai envoyé le mail » sans avoir appelé ``gmail_send``). Il ne
  regarde pas si le résultat répond au cahier des charges.
- ``mission_critic`` critique les missions autonomes — **0 appel sur 7 jours**
  au 27/07/2026.

Résultat : « convertis sans perte de mise en page, en gardant la taille, les
marges, les polices, les couleurs et les tailles de caractère » se terminait
sur ce que le modèle avait produit, sans que ces six exigences soient jamais
confrontées au résultat. Aucune relance n'était possible.

La forme, tranchée par Franck le 27/07/2026
--------------------------------------------
    « Quand elle a le retour, elle regarde si c'est ce que j'ai demandé […]
      pour que si ce n'est pas le cas, elle relance la demande auprès d'un
      LLM Cloud avec des infos complémentaires ou des paramètres différents. »

Le juge est **le modèle principal, dans le même tour** : il a déjà le contexte,
et il n'y a pas de second modèle à choisir ni à configurer.

Les trois règles qui séparent une boucle utile d'une boucle folle
------------------------------------------------------------------
1. **Conforme par défaut.** Un modèle à qui l'on demande « liste les écarts »
   en trouvera toujours. Le contrat inverse la charge de la preuve : un écart
   ne se signale que si l'utilisateur a formulé une exigence EXPLICITE qui
   n'est pas satisfaite.
2. **Échouer ouvert.** Juge en panne, verdict illisible, quota épuisé : on
   laisse passer. Une vérification cassée ne doit jamais retenir la réponse de
   l'utilisateur ni déclencher des relances payantes en boucle.
3. **Plafond de relances.** Sans lui, deux modèles se renvoient la balle sur
   une exigence qu'aucun ne sait satisfaire.

Le déclencheur est l'**exécution d'un outil**, pas un mot-clé : un tour qui n'a
rien produit n'a rien à vérifier. On ne réintroduit pas ici l'heuristique de
vocabulaire supprimée en L2 (#287).
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.helpers.message_content import content_to_text
from app.agent.state import AgentState
from app.services.llm_deadline import ainvoke_with_deadline

logger = logging.getLogger(__name__)


# Deux relances suffisent : au-delà, l'expérience des boucles de correction
# montre que le modèle tourne sur le même écart sans le résoudre. Mieux vaut
# rendre la main avec un résultat imparfait ET l'écart signalé.
MAX_CONFORMITY_RETRIES: int = 2

_CONFORME = "CONFORME"

# Préfixe des relances. Sert deux fois : à les reconnaître pour router après
# vérification, et à les SAUTER quand on cherche la demande d'origine — sans
# quoi le juge finirait par vérifier sa propre consigne.
_RETRY_MARKER = "[Vérification"

_JUDGE_PROMPT = """\
Tu vérifies qu'un travail répond à la demande qui l'a produit.

DEMANDE DE L'UTILISATEUR :
{demande}

CE QUI A ÉTÉ PRODUIT :
{resultat}

Ta seule question : l'utilisateur a-t-il formulé une exigence EXPLICITE qui \
n'est pas satisfaite ?

Règles :
- Une exigence explicite est une contrainte que l'utilisateur a ÉCRITE \
(« sans perte de mise en page », « en gardant les marges », « en anglais », \
« au format .docx », « les 12 premières »). Ce que tu aurais fait autrement \
n'est PAS un écart.
- Si tu n'es pas certain qu'une exigence n'est pas satisfaite, elle l'est.
- Ne reproche pas une limite qui a été SIGNALÉE à l'utilisateur : un résultat \
imparfait mais annoncé comme tel répond à la demande.

Réponds dans l'un de ces deux formats, et rien d'autre :

{conforme}

ou

ÉCARTS:
- <l'exigence non satisfaite, et ce qui manque pour y répondre>
- <une ligne par exigence>
"""

_RETRY_TEMPLATE = """\
[Vérification — la demande n'est pas encore satisfaite]

Ce que tu viens de produire ne répond pas à ces exigences de la demande :

{ecarts}

Reprends le travail en visant précisément ces points. Change d'approche ou de \
paramètres plutôt que de refaire à l'identique. Si l'un de ces points est \
réellement hors de portée, dis-le explicitement à l'utilisateur au lieu de le \
passer sous silence.
"""


# ──────────────────────────────────────────────────────────────────────
# Le déclencheur
# ──────────────────────────────────────────────────────────────────────


def should_verify_conformity(state: AgentState | dict) -> bool:
    """Ce tour mérite-t-il une vérification de conformité ?

    Trois conditions, toutes nécessaires :
        - le tour se termine (la dernière réponse ne porte pas de tool_calls) ;
        - un outil a réellement tourné, donc il existe un résultat à juger ;
        - le budget de relances n'est pas épuisé.

    Ne lève jamais : un état inattendu vaut « ne pas vérifier ».
    """
    try:
        messages = state.get("messages") or []
        if not messages:
            return False
        last = messages[-1]
        if not isinstance(last, AIMessage) or last.tool_calls:
            return False
        if state.get("conformity_retries", 0) >= MAX_CONFORMITY_RETRIES:
            return False
        return any(isinstance(m, ToolMessage) for m in messages)
    except Exception as exc:  # noqa: BLE001 — un garde ne fait pas tomber le tour
        logger.debug("should_verify_conformity: état inattendu (%s)", exc)
        return False


# ──────────────────────────────────────────────────────────────────────
# Le verdict
# ──────────────────────────────────────────────────────────────────────


def parse_conformity_verdict(raw: Any) -> tuple[bool, str]:
    """Lit le verdict du juge. Renvoie ``(conforme, écarts)``.

    Échoue OUVERT : tout ce qui n'est pas un constat d'écart lisible est traité
    comme conforme. Un verdict illisible qui relancerait le tour transformerait
    une panne du juge en boucle de relances payantes.

    ``raw`` peut être une liste de blocs de contenu — le tier codex rend
    ``content`` sous cette forme, piège qui a déjà coûté plusieurs incidents.
    """
    text = content_to_text(raw).strip()
    if not text:
        return True, ""
    if _CONFORME in text.upper():
        return True, ""

    marker = "ÉCARTS:"
    upper = text.upper()
    idx = upper.find(marker)
    if idx == -1:
        idx = upper.find("ECARTS:")
    if idx == -1:
        # Ni « CONFORME » ni « ÉCARTS: » — le juge n'a pas suivi le contrat.
        # On ne relance pas sur du bavardage.
        logger.info("conformité : verdict hors contrat, traité comme conforme")
        return True, ""

    gaps = text[idx + len(marker):].strip()
    if not gaps:
        return True, ""
    return False, gaps


# ──────────────────────────────────────────────────────────────────────
# Le nœud
# ──────────────────────────────────────────────────────────────────────


async def conformity_node(state: AgentState | dict) -> dict:
    """Confronte le résultat à la demande ; relance l'agent s'il y a un écart.

    Returns:
        ``{}`` (ou ``{"messages": []}``) si le tour est conforme — le graphe
        termine. Sinon un ``HumanMessage`` nommant les écarts, plus le
        compteur de relances incrémenté : le graphe repasse par ``agent``.
    """
    messages = list(state.get("messages") or [])
    demande = _last_user_request(messages)
    resultat = _produced(messages)
    if not demande or not resultat:
        return {"messages": []}

    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    if llm is None:
        logger.warning("conformité : aucun modèle disponible — tour laissé passer")
        return {"messages": []}

    prompt = _JUDGE_PROMPT.format(
        demande=demande[:4000], resultat=resultat[:8000], conforme=_CONFORME,
    )
    try:
        # ``config={"callbacks": []}`` : cet appel tourne PENDANT un tour actif.
        # Sans cette coupure, LangChain propage l'arbre de callbacks par
        # contextvars et les tokens du juge s'affichent dans la réponse de
        # l'utilisateur (bug réel du 19/07 avec le générateur tier-S).
        response = await ainvoke_with_deadline(
            llm,
            [HumanMessage(content=prompt)],
            tier="complex",
            surface="conformity",
            config={"callbacks": []},
        )
    except Exception as exc:  # noqa: BLE001 — échouer OUVERT
        logger.warning(
            "conformité : juge indisponible (%s) — tour laissé passer", exc,
        )
        return {"messages": []}

    conforme, ecarts = parse_conformity_verdict(
        getattr(response, "content", response)
    )
    if conforme:
        return {"messages": []}

    retries = int(state.get("conformity_retries", 0)) + 1
    logger.info(
        "conformité : relance %d/%d — écarts : %.200s",
        retries, MAX_CONFORMITY_RETRIES, ecarts.replace("\n", " ; "),
    )
    return {
        "messages": [HumanMessage(content=_RETRY_TEMPLATE.format(ecarts=ecarts))],
        "conformity_retries": retries,
    }


# ──────────────────────────────────────────────────────────────────────
# Extraction du contexte à juger
# ──────────────────────────────────────────────────────────────────────


def _last_user_request(messages: list) -> str:
    """La dernière VRAIE demande de l'utilisateur.

    Les relances de conformité sont elles-mêmes des ``HumanMessage`` : les
    sauter évite que le juge finisse par vérifier sa propre consigne au lieu
    de la demande d'origine.
    """
    for m in reversed(messages):
        if not isinstance(m, HumanMessage):
            continue
        text = content_to_text(m.content).strip()
        if text.startswith(_RETRY_MARKER):
            continue
        return text
    return ""


def _produced(messages: list) -> str:
    """Ce que le tour a produit : les retours d'outils + la réponse finale.

    Les retours d'outils comptent autant que le texte final — c'est là que se
    trouvent les mesures qui permettent de juger (``pdf_to_docx`` rapporte déjà
    ses caractères perdus et son calibrage, par exemple).
    """
    parts: list[str] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            parts.append(f"[résultat d'outil] {content_to_text(m.content)}")
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage):
        final = content_to_text(last.content).strip()
        if final:
            parts.append(f"[réponse finale] {final}")
    return "\n".join(parts)


def route_after_conformity(state: AgentState | dict) -> str:
    """Où va-t-on après la vérification ?

    ``"agent"`` si une relance a été posée dans la conversation, ``"end"``
    sinon. On lit l'état plutôt qu'une valeur de retour parce que LangGraph
    fusionne les mises à jour de nœuds : le routeur ne voit que l'état résultant.
    """
    messages = state.get("messages") or []
    if not messages:
        return "end"
    last = messages[-1]
    if isinstance(last, HumanMessage) and content_to_text(
        last.content
    ).lstrip().startswith(_RETRY_MARKER):
        return "agent"
    return "end"


__all__ = [
    "MAX_CONFORMITY_RETRIES",
    "conformity_node",
    "parse_conformity_verdict",
    "route_after_conformity",
    "should_verify_conformity",
]
