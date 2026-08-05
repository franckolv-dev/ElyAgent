# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_from_success.py
# @brief      Une compétence naît d'un SUCCÈS constaté — pas d'un manque supposé.
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
"""Le déclencheur qui manquait au funnel des compétences.

Le constat, mesuré le 28/07/2026
---------------------------------
``skill_creator`` savait déjà rédiger un playbook et le poser en ``CANDIDATE``.
Ce qui lui manquait, c'est **quand** le faire : il était alimenté par des cas
d'échec clusterisés, un déclencheur qui ne partait quasiment jamais.

    66 compétences apprises  ->  16 usages cumulés
    tier_s.tool_generator    ->  86 appels en 7 jours (3× les demandes de Franck)

On produisait beaucoup, au mauvais moment, à partir du mauvais signal.

Le déclencheur retenu
---------------------
**Un tour jugé CONFORME alors qu'il a fallu au moins une reprise** — le signal
que produit désormais ``app.agent.conformity`` (#288/#289).

    1re approche  ->  ne répondait pas à la demande
    reprise       ->  a fonctionné
    => il s'est passé quelque chose de transférable, ET on sait quoi :
       l'écart qui a été comblé

Un tour conforme du premier coup n'apprend rien : le modèle savait déjà. Un
tour arrêté sur des écarts n'apprend rien de fiable : on ignore ce qui aurait
marché, et écrire une procédure depuis un échec revient à graver une
supposition.

C'est la forme d'Hermes — ``background_review.py`` rejoue le tour APRÈS coup et
demande « faut-il enregistrer une skill ? ».

Qui rédige
----------
**Le modèle principal, celui qui vient de réussir.** Un SKILL.md est une
consigne écrite POUR un modèle frontière ; le mieux placé pour l'écrire est
celui qui l'exécutera. Faire rédiger par un petit modèle local puis « optimiser »
par le tier C remettrait le petit modèle en amont de la tâche la plus
structurante — l'inversion supprimée en #287.

Où ça tourne
------------
En **tâche de fond, après le tour** (leçon de #286 : ce qui n'appartient pas à
la réponse de l'utilisateur ne doit pas tourner dans sa boucle). L'appel coupe
ses callbacks, sinon ses tokens s'affichent dans le chat.

Le résultat est un ``CANDIDATE`` : il passe par la validation humaine existante,
jamais activé d'office.
"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.helpers.message_content import content_to_text
from app.models.learned_skill import LearnedSkill, SkillSource, SkillStatus
from app.services.llm_deadline import ainvoke_with_deadline

logger = logging.getLogger(__name__)

# Marqueur des relances posées par ``app.agent.conformity`` — c'est lui qui
# permet de retrouver CE QUI A DÛ ÊTRE CORRIGÉ, la vraie leçon du tour.
_RETRY_MARKER = "[Vérification"

_PROMPT = """\
Tu viens de réussir une tâche, mais pas du premier coup. Écris la procédure \
que tu aurais aimé avoir AVANT de commencer.

CE QUE L'UTILISATEUR DEMANDAIT :
{demande}

CE QUI A DÛ ÊTRE CORRIGÉ EN COURS DE ROUTE :
{ecarts}

CE QUI A FINALEMENT FONCTIONNÉ :
{resultat}

Outils réellement appelés : {outils}

Écris un playbook réutilisable, au format exact ci-dessous et RIEN d'autre :

---
name: <identifiant-en-kebab-case, 3 à 6 mots>
description: <une phrase : à quoi sert cette procédure>
---

## Quand l'appliquer
<les conditions de déclenchement, concrètes. Dis aussi quand NE PAS l'appliquer.>

## Procédure
1. <étape, en nommant les outils exacts et leurs paramètres décisifs>
2. <…>

## Vérifier
<comment savoir que le résultat est bon — de préférence une mesure>

Règles :
- Écris pour un modèle qui exécutera, pas pour un humain qui lira.
- La leçon est dans la CORRECTION, pas dans la tâche : sans elle, tu écrirais \
« fais le travail », ce qui ne vaut rien.
- N'invente aucun outil ni paramètre qui n'apparaît pas ci-dessus.
- Reste sous 25 lignes.
"""


# ──────────────────────────────────────────────────────────────────────
# Le déclencheur
# ──────────────────────────────────────────────────────────────────────


def should_propose_skill_from_success(*, conforme: bool, retries: int) -> bool:
    """Ce tour mérite-t-il qu'on en tire une compétence ?

    Oui uniquement s'il a fini CONFORME **après au moins une reprise**. Voir le
    docstring du module pour pourquoi les deux autres cas n'apprennent rien.
    """
    return bool(conforme) and int(retries or 0) > 0


# ──────────────────────────────────────────────────────────────────────
# Ce qu'on demande au modèle
# ──────────────────────────────────────────────────────────────────────


def build_success_skill_prompt(messages: list) -> str:
    """Assemble la demande, les écarts corrigés, et ce qui a marché.

    Rend ``""`` quand la conversation ne permet pas de reconstituer l'histoire
    — l'appelant s'abstient alors, plutôt que de faire écrire une procédure
    dans le vide.
    """
    if not messages:
        return ""

    demande = ""
    ecarts: list[str] = []
    outils: list[str] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            text = content_to_text(m.content).strip()
            if text.startswith(_RETRY_MARKER):
                ecarts.append(text)
            elif not demande:
                demande = text
        elif isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                name = tc.get("name") if isinstance(tc, dict) else None
                if name and name not in outils:
                    outils.append(name)

    if not demande:
        return ""

    resultat_parts = [
        content_to_text(m.content)
        for m in messages[-3:]
        if isinstance(m, (AIMessage, ToolMessage)) and content_to_text(m.content).strip()
    ]
    return _PROMPT.format(
        demande=demande[:2000],
        ecarts=("\n".join(ecarts)[:2000] or "(aucun écart enregistré)"),
        resultat=("\n".join(resultat_parts)[:2000] or "(pas de résultat capturé)"),
        outils=(", ".join(outils) or "aucun"),
    )


# ──────────────────────────────────────────────────────────────────────
# La rédaction
# ──────────────────────────────────────────────────────────────────────


async def draft_skill_from_success(user_id: str, messages: list) -> LearnedSkill | None:
    """Fait rédiger un playbook par le modèle principal, en ``CANDIDATE``.

    Ne lève jamais et ne commite rien : la ligne est rendue à l'appelant, qui
    décide de la persister. ``None`` dès que quoi que ce soit ne va pas — mieux
    vaut aucune compétence qu'une compétence bancale dans le catalogue.
    """
    if not user_id:
        return None
    prompt = build_success_skill_prompt(messages)
    if not prompt:
        return None

    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    if llm is None:
        logger.debug("skill_from_success : aucun modèle disponible")
        return None

    try:
        # ``config={"callbacks": []}`` : tourne en tâche de fond pendant que le
        # chat peut être actif. Sans cette coupure, les tokens de la rédaction
        # s'affichent dans la réponse de l'utilisateur (bug réel du 19/07).
        response = await ainvoke_with_deadline(
            llm,
            [HumanMessage(content=prompt)],
            tier="complex",
            surface="skill-from-success",
            config={"callbacks": []},
        )
    except Exception as exc:  # noqa: BLE001 — corvée de fond, jamais bloquante
        logger.info("skill_from_success : rédaction abandonnée (%s)", exc)
        return None

    # Consigné AVANT le parsing : une réponse inexploitable a quand même été
    # facturée, et sortir sans rien écrire la rendrait gratuite dans les
    # chiffres. C'est ce chemin-là — celui qui échoue — qui disparaissait le
    # plus sûrement des mesures.
    try:
        from app.services.analytics_service import log_response_usage
        from app.services.llm_provider import describe_llm

        _provider, _model = describe_llm(llm)
        await log_response_usage(
            user_id, response, provider=_provider, model=_model,
            channel="background", skill_used="skill_from_success",
        )
    except Exception as exc:  # noqa: BLE001 — consigner ne bloque jamais
        logger.debug("skill_from_success : usage non consigné (%s)", exc)

    from app.services.learning.skill_creator import parse_playbook_response

    parsed = parse_playbook_response(
        content_to_text(getattr(response, "content", response))
    )
    if not parsed:
        logger.info("skill_from_success : réponse non exploitable, rien enregistré")
        return None

    return LearnedSkill(
        user_id=user_id,
        name=parsed["name"],
        description=parsed["description"],
        content=parsed["body"],
        frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
        status=SkillStatus.CANDIDATE,
        source=SkillSource.AUTO_GENERATED,
        iteration_count=1,
        rationale=(
            "Tirée d'un succès vérifié : la demande n'était pas satisfaite au "
            "premier essai, et la reprise a fonctionné. La procédure décrit ce "
            "qui a comblé l'écart."
        ),
    )


__all__ = [
    "build_success_skill_prompt",
    "draft_skill_from_success",
    "should_propose_skill_from_success",
]
