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
from app.services.analytics_service import log_response_usage
from app.services.llm_deadline import ainvoke_with_deadline

logger = logging.getLogger(__name__)


# Ce n'est PLUS le régulateur, c'est un garde-fou d'emballement (28/07/2026).
#
# La version livrée en #288 plafonnait à 2 reprises — un chiffre posé SANS
# mesure, alors que la boucle n'avait jamais tourné en production. Il traitait
# de la même façon une tâche qui progresse (6 exigences non satisfaites → 2 →
# 1) et une qui tourne en rond (les mêmes 3 écarts à chaque reprise) : la
# première méritait de continuer, la seconde devait s'arrêter tout de suite.
#
# C'est désormais le PROGRÈS qui décide (``is_making_progress``). Ce plafond ne
# sert plus qu'à borner un emballement pathologique, d'où une valeur haute.
MAX_CONFORMITY_RETRIES: int = 5

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

_REPORT_PROMPT = """\
Tu as travaillé sur cette demande sans pouvoir la satisfaire entièrement, et \
tu n'as plus de reprise disponible.

DEMANDE :
{demande}

TA RÉPONSE ACTUELLE :
{reponse}

CE QUI N'EST PAS SATISFAIT :
{ecarts}

Réécris ta réponse à l'utilisateur. Garde ce que tu as réellement produit, \
puis dis-lui clairement, sans détour et sans t'excuser, ce qui n'a pas pu être \
obtenu. Termine par UNE piste concrète et actionnable — ce qu'il peut fournir, \
reformuler ou accepter comme contrainte pour que ça aboutisse.

N'invente aucun résultat. Ne promets aucune action future. Réponds uniquement \
par le texte destiné à l'utilisateur.
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
# Le progrès — ce qui décide vraiment de continuer ou d'arrêter
# ──────────────────────────────────────────────────────────────────────


def count_gaps(gaps: str) -> int:
    """Combien d'exigences non satisfaites dans ce verdict ?

    Une puce = un écart. Un verdict rédigé en prose, sans puce, compte pour
    **un** écart : il en signale au moins un, et on ne gonfle pas le compte
    avec le nombre de lignes de rédaction — sinon une reformulation plus
    bavarde passerait pour une régression.
    """
    text = (gaps or "").strip()
    if not text:
        return 0
    bullets = [
        ln for ln in text.splitlines()
        if ln.strip().startswith(("-", "•", "*"))
    ]
    return len(bullets) if bullets else 1


def is_making_progress(*, new_count: int, previous_count: int) -> bool:
    """La reprise précédente a-t-elle fait reculer la liste des écarts ?

    ``previous_count == 0`` signifie « pas encore de tour de référence » : la
    première vérification a toujours droit à sa reprise.

    Un compte identique n'est pas un progrès : le modèle rend la même liste,
    la reprise suivante rendra la même. Un compte en hausse non plus — la
    reprise a empiré les choses, insister n'a aucune raison d'aider.
    """
    if previous_count <= 0:
        return True
    return new_count < previous_count


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

    # Le coût de la boucle doit être visible au tableau de bord, sinon on ne
    # peut pas arbitrer s'il vaut ce qu'il rapporte. Même geste que
    # ``memory_extraction`` : une ligne d'usage, best-effort.
    try:
        await log_response_usage(
            state.get("user_id", ""), response,
            skill_used="conformity_check",
            conversation_id=state.get("conversation_id", "") or None,
        )
    except Exception as exc:  # noqa: BLE001 — la journalisation est un confort
        logger.debug("conformité : usage non journalisé (%s)", exc)

    conforme, ecarts = parse_conformity_verdict(
        getattr(response, "content", response)
    )
    if conforme:
        # Le chemin nominal était MUET : impossible de distinguer « jugé
        # conforme » de « la vérification n'a jamais tourné ». Constaté le
        # 28/07 sur la première conversion réelle — tout le tour était dans
        # les journaux SAUF la vérification.
        logger.info(
            "conformité : CONFORME après %d reprise(s) — tour rendu tel quel",
            int(state.get("conformity_retries", 0)),
        )
        # Conforme APRÈS une reprise = il s'est passé quelque chose de
        # transférable, et on sait quoi : l'écart qui a été comblé. C'est le
        # déclencheur qui manquait au funnel des compétences (66 apprises pour
        # 16 usages). Tourne en tâche de fond, après le tour — jamais dans la
        # boucle de réponse de l'utilisateur (leçon de #286).
        _maybe_learn_from_success(
            state.get("user_id", ""),
            messages,
            retries=int(state.get("conformity_retries", 0)),
        )
        return {"messages": []}

    # Le progrès décide, pas le compteur.
    n = count_gaps(ecarts)
    previous = int(state.get("conformity_gap_count", 0))
    retries = int(state.get("conformity_retries", 0))

    if (
        is_making_progress(new_count=n, previous_count=previous)
        and retries < MAX_CONFORMITY_RETRIES
    ):
        logger.info(
            "conformité : relance %d — %d écart(s), %d au tour précédent : %.200s",
            retries + 1, n, previous, ecarts.replace("\n", " ; "),
        )
        return {
            "messages": [HumanMessage(content=_RETRY_TEMPLATE.format(ecarts=ecarts))],
            "conformity_retries": retries + 1,
            "conformity_gap_count": n,
        }

    # On s'arrête — soit ça n'avance plus, soit le garde-fou a parlé.
    raison = (
        "plafond de sécurité atteint" if retries >= MAX_CONFORMITY_RETRIES
        else f"aucun progrès ({n} écart(s), {previous} au tour précédent)"
    )
    logger.info("conformité : arrêt — %s. Écarts : %.200s", raison, ecarts.replace("\n", " ; "))

    # Avant d'abandonner : DEMANDER AUX AUTRES (lot 2, 28/07/2026). Ely a
    # plusieurs modèles configurés dans son tier `complex` et ne s'en servait
    # qu'en cas de PANNE — jamais quand le résultat était mauvais.
    #
    # ⚠️ L'ordre compte : escalader D'ABORD, rapporter ensuite. L'inverse
    # ferait payer un appel de rédaction pour un texte aussitôt remplacé.
    escalade = await _try_escalation(state, messages, ecarts, n, previous)
    if escalade is not None:
        return escalade

    # Rien de mieux à offrir : l'utilisateur doit SAVOIR ce qui n'a pas pu être
    # fait. Rendre un résultat incomplet en silence est précisément ce que
    # cette boucle existe pour supprimer.
    return await _report_remaining_gaps(messages, llm, ecarts)


# Ce qu'on ajoute à la réponse retenue. La provenance n'est pas un détail : sans
# elle, Franck ne peut ni arbitrer sa configuration de modèles ni la corriger —
# c'est exactement ce qui lui a manqué pendant les cinq essais de conversion.
#
# ⚠️ « sans outils » y figure depuis #319 et n'est pas décoratif. Le panel est
# en lecture seule par construction ; tant que la note ne le disait pas, une
# réponse qui butait sur une action se lisait comme un constat d'impuissance
# d'Ely — alors qu'elle venait d'un relais purement textuel.
_ESCALATION_NOTE = (
    "\n\n---\n*Cette réponse vient de **{model}**, interrogé **sans outils** : "
    "les exigences n'étaient toujours pas satisfaites après reprise, alors {n} "
    "modèles ont été interrogés et la meilleure réponse retenue.{cout}*"
)


async def _try_escalation(state, messages: list, ecarts: str,
                          new_count: int, previous_count: int) -> dict | None:
    """Demande à plusieurs modèles, et substitue la meilleure réponse.

    Returns:
        ``None`` si l'escalade n'a rien à offrir — panel indisponible, un seul
        modèle, plafond de budget atteint. L'appelant retombe alors sur le
        constat d'écarts. **Échouer OUVERT** : une amélioration qui tombe ne
        doit jamais coûter le résultat déjà obtenu.
    """
    from app.agent.escalation import should_escalate

    if not should_escalate(new_count=new_count, previous_count=previous_count):
        return None
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return None

    try:
        from app.agent import escalation

        result = await escalation.escalate_to_panel(
            demande=_last_user_request(messages),
            produit=_produced(messages),
            ecarts=ecarts,
            user_id=state.get("user_id", ""),
            conversation_id=state.get("conversation_id", "") or "",
        )
    except Exception as exc:  # noqa: BLE001 — échouer OUVERT
        logger.warning("conformité : escalade indisponible (%s)", exc)
        return None

    if result is None or not result.answer.strip():
        return None

    # Un coût nul (modèle au forfait) ne s'affiche pas : l'annoncer à chaque
    # fois apprendrait à ne plus le lire.
    cout = f" Coût : {result.cost_usd:.2f} $." if result.cost_usd > 0 else ""
    texte = result.answer + _ESCALATION_NOTE.format(
        model=result.model, n=result.models_asked, cout=cout,
    )
    logger.info(
        "conformité : escalade retenue — %r sur %d modèle(s), %.4f $",
        result.model, result.models_asked, result.cost_usd,
    )
    # Même id ⇒ substitution par `add_messages`, pas empilement.
    return {"messages": [AIMessage(content=texte, id=last.id)]}


async def _report_remaining_gaps(messages: list, llm: Any, ecarts: str) -> dict:
    """Réécrit la réponse finale pour y dire ce qui manque, et proposer une piste.

    Le message rendu porte **le même ``id``** que la réponse finale : LangGraph
    le SUBSTITUE au lieu de l'empiler, donc l'utilisateur voit une seule
    réponse — complétée, pas doublée.

    Échoue OUVERT : si l'appel tombe, on rend la réponse d'origine telle quelle
    plutôt que de retenir le tour.
    """
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return {"messages": []}

    prompt = _REPORT_PROMPT.format(
        demande=_last_user_request(messages)[:2000],
        reponse=content_to_text(last.content)[:4000],
        ecarts=ecarts[:2000],
    )
    try:
        response = await ainvoke_with_deadline(
            llm,
            [HumanMessage(content=prompt)],
            tier="complex",
            surface="conformity-report",
            config={"callbacks": []},
        )
    except Exception as exc:  # noqa: BLE001 — échouer OUVERT
        logger.warning(
            "conformité : rapport indisponible (%s) — réponse rendue telle quelle",
            exc,
        )
        return {"messages": []}

    texte = content_to_text(getattr(response, "content", response)).strip()
    if not texte:
        return {"messages": []}
    # Même id ⇒ substitution par ``add_messages``, pas empilement.
    return {"messages": [AIMessage(content=texte, id=last.id)]}


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


def _maybe_learn_from_success(user_id: str, messages: list, *, retries: int) -> bool:
    """Propose une compétence quand le tour a réussi APRÈS reprise.

    Ne lève jamais et n'attend rien : la rédaction part en tâche de fond, la
    réponse de l'utilisateur ne l'attend pas.

    Returns:
        True si une rédaction a été lancée.
    """
    from app.services.learning.skill_from_success import (
        should_propose_skill_from_success,
    )

    if not user_id or not should_propose_skill_from_success(
        conforme=True, retries=retries
    ):
        return False

    async def _draft() -> None:
        try:
            from app.services.learning.skill_from_success import (
                draft_skill_from_success,
            )

            skill = await draft_skill_from_success(user_id, list(messages))
            if skill is None:
                return
            from app.database import async_session

            async with async_session() as db:
                db.add(skill)
                await db.commit()
            logger.info(
                "compétence proposée depuis un succès vérifié : %r (à valider)",
                skill.name,
            )
        except Exception as exc:  # noqa: BLE001 — corvée de fond
            logger.info("skill_from_success : proposition abandonnée (%s)", exc)

    try:
        from app.services.background_tasks import spawn

        spawn(_draft(), label="skill_from_success", detach_context=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("skill_from_success : ordonnancement impossible (%s)", exc)
        return False
    return True


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
    "count_gaps",
    "is_making_progress",
    "parse_conformity_verdict",
    "route_after_conformity",
    "should_verify_conformity",
]
