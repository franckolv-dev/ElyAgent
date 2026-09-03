# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_or_skill.py
# @brief      Faut-il un OUTIL, ou une compétence suffit-elle ?
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""La règle posée par Franck le 29/07/2026.

    « Soit la demande peut être réglée par un modèle local ou cloud, et dans
      ce cas ce n'est pas un outil qu'il faut développer mais plutôt une
      skill ; soit la demande ne peut pas être réglée par un modèle (car cela
      nécessite une ou plusieurs actions) et là il faut créer un outil. »

Ce qui déclenchait la génération avant ce lot
-----------------------------------------------
``find_tool`` ne trouve rien → un gap est consigné → **on génère un outil**.
Les gardes existantes portaient toutes sur « existe-t-il DÉJÀ un outil ? »
(flag global, gap déjà tenté ce boot, pré-check sémantique). Aucune ne posait
la question de Franck : **faut-il un outil du tout ?**

D'où des outils fabriqués pour ce qu'un modèle règle en une phrase — résumer,
traduire, reformuler — puis jamais utilisés.

Le critère, opérationnel
-------------------------
**La capacité touche-t-elle quelque chose HORS du modèle ?** Un fichier, une
API, un service, la machine. C'est le même axe que l'EFFET de
``app.agent.tool_nature`` : produire du texte n'est pas agir.

⚠️ Ce n'est PAS un critère de difficulté. Traduire un contrat juridique est
difficile et reste une compétence ; poster un message d'une ligne est trivial
et demande un outil.

⚠️ On échoue en NE générant PAS
---------------------------------
À l'inverse de la boucle de conformité — qui laisse passer en cas de doute
pour ne jamais retenir une réponse — ici le doute ne fabrique rien.

Rien n'est perdu : le gap reste consigné dans « Capacités manquantes » avec son
bouton manuel, donc l'utilisateur garde la main. Générer à tort coûte un outil
mort de plus, et c'est précisément ce que ce lot supprime.

⚠️ L'ARBITRAGE PENCHE VERS LE DOCUMENT (02/09/2026)
-----------------------------------------------------
La mesure de cinq mois : 98 compétences apprises, 43 périmées, 3 graduées.
Deux réglages du critère, tirés de là :

1. **Le prompt** dit désormais qu'un outil ne se justifie que si AUCUNE
   procédure écrite ne peut décrire la marche à suivre avec les outils
   existants. Composer des outils déjà là, c'est une procédure ; il ne faut
   un outil que pour une action qu'aucun outil existant n'atteint.

2. **La lecture du verdict** était « OUTIL est-il quelque part dans la
   réponse ? ». Un juge hésitant — « OUTIL ou COMPETENCE, difficile à dire »
   — fabriquait donc un outil, parce que le mot y figurait et qu'il était
   testé en premier. Le contrat demande UN mot : seul un verdict qui s'y
   tient, et qui ne mentionne pas l'autre issue, fabrique.
"""
from __future__ import annotations

import logging
import unicodedata

from langchain_core.messages import HumanMessage

from app.agent.helpers.message_content import content_to_text

logger = logging.getLogger(__name__)

_OUTIL = "OUTIL"
_COMPETENCE = "COMPETENCE"

_PROMPT = """\
Une capacité manque à une assistante personnelle. Décide de ce qu'il faut en
faire, en répondant à UNE seule question.

CAPACITÉ : {capability}

LA QUESTION : cette capacité demande-t-elle une ACTION sur quelque chose
d'extérieur au modèle — un fichier, une API, un service en ligne, la machine,
un compte, un envoi ? Ou bien un modèle de langage peut-il la fournir
entièrement en produisant du texte ?

Ce n'est PAS une question de difficulté. Traduire un contrat juridique est
difficile et reste du texte. Poster un message d'une ligne est trivial et
demande une action.

Ce n'est PAS non plus une question de longueur : si la marche à suivre peut
s'ÉCRIRE sous forme de procédure — des étapes numérotées, en s'appuyant sur
les outils dont l'assistante dispose déjà — alors c'est une COMPETENCE, même
si la procédure compte dix étapes. Un OUTIL ne se justifie que pour une
action qu'aucune procédure ne peut décrire, parce qu'aucun outil existant ne
l'atteint.

Réponds par un seul mot, sans rien d'autre, et par COMPETENCE si tu hésites :

  OUTIL        une action hors de portée de toute procédure écrite
  COMPETENCE   un modèle la fournit en produisant du texte, ou une procédure
               la décrit avec les outils existants
"""


async def needs_a_tool(capability: str, *, user_id: str = "", **_: object) -> bool:
    """Cette capacité justifie-t-elle de FABRIQUER un outil ?

    Le jugement est confié au niveau S — donc au modèle **local** en tête de
    chaîne, qui ne coûte rien et tourne en tâche de fond : cette décision ne
    doit jamais ralentir le tour de l'utilisateur.

    Ne lève jamais, et **rend ``False`` dès qu'il y a un doute** : verdict
    illisible, aucun modèle disponible, appel en erreur. Le gap reste consigné
    et l'utilisateur garde le bouton manuel — alors qu'un outil fabriqué à tort
    reste, lui, définitivement.
    """
    texte = (capability or "").strip()
    if not texte:
        return False

    try:
        from app.services.learning.tier_s import get_tier_s_llm

        llm, pick = await get_tier_s_llm()
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("outil-ou-compétence : niveau S indisponible (%s)", exc)
        return False
    if llm is None or pick == "none":
        logger.info(
            "outil-ou-compétence : aucun modèle au niveau S — « %.60s » laissé "
            "en capacité manquante plutôt que fabriqué à l'aveugle", texte,
        )
        return False

    try:
        # ``config={"callbacks": []}`` : la génération tourne en tâche de fond
        # mais hérite du contexte du tour si on ne coupe pas — les tokens du
        # juge s'afficheraient dans la réponse de l'utilisateur (bug du 19/07).
        from app.services.llm_deadline import ainvoke_with_deadline

        response = await ainvoke_with_deadline(
            llm, [HumanMessage(content=_PROMPT.format(capability=texte[:500]))],
            tier="skill", surface="tool-or-skill", config={"callbacks": []},
        )
    except Exception as exc:  # noqa: BLE001 — le doute ne fabrique rien
        logger.warning(
            "outil-ou-compétence : jugement indisponible (%s) — « %.60s » non "
            "fabriquée", exc, texte,
        )
        return False

    # Ce jugement VISE le modèle local en tête de chaîne, gratuit. Mais
    # `get_tier_s_llm` descend la chaîne quand ce local est indisponible, et
    # le rang suivant est facturé : « conçu pour être gratuit » n'est pas
    # « gratuit ». Sans cette ligne, ce chemin dépensait sans laisser de
    # trace — le défaut diagnostiqué le 05/08 sur le tier `complex`.
    # `log_response_usage` ne fait rien si le fournisseur n'a rien remonté.
    try:
        from app.services.analytics_service import log_response_usage

        await log_response_usage(
            user_id, response, provider=pick, model=str(pick),
            channel="background", skill_used="tool_or_skill",
        )
    except Exception as exc:  # noqa: BLE001 — consigner ne bloque jamais
        logger.debug("outil-ou-compétence : usage non consigné (%s)", exc)

    verdict = _sans_accent(
        content_to_text(getattr(response, "content", response))
    ).strip().upper()
    # Le contrat demande UN mot. On lit donc le PREMIER, et on refuse dès que
    # l'autre issue est mentionnée : « OUTIL ou COMPETENCE » est une hésitation
    # déguisée, et l'hésitation ne fabrique pas (réglage 02/09/2026). Les
    # accents sont retirés avant comparaison — « COMPÉTENCE » ne contient pas
    # « COMPETENCE », et ce verdict-là partait dans la branche « hors contrat ».
    mots = verdict.replace("*", " ").replace(".", " ").split()
    premier = mots[0].strip(",:;!-") if mots else ""
    if premier == _OUTIL and _COMPETENCE not in verdict:
        logger.info("outil-ou-compétence : « %.60s » → OUTIL (action requise)", texte)
        return True
    if _COMPETENCE in verdict:
        logger.info(
            "outil-ou-compétence : « %.60s » → COMPÉTENCE — pas de génération, "
            "une procédure ou un modèle suffit", texte,
        )
        return False

    # Ni l'un ni l'autre, ou un OUTIL noyé dans une phrase : le juge n'a pas
    # suivi le contrat. On ne fabrique pas sur du bavardage.
    logger.info(
        "outil-ou-compétence : verdict hors contrat (%.40s) — « %.60s » non "
        "fabriquée", verdict, texte,
    )
    return False


def _sans_accent(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )


__all__ = ["needs_a_tool"]
