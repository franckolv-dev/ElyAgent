# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/skill_from_success.py
# @brief      Une compétence naît d'un SUCCÈS constaté — pas d'un manque supposé.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
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
import unicodedata

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.helpers.message_content import content_to_text
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)
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

Écris un playbook réutilisable, au format exact ci-dessous et RIEN d'autre. \
Les CINQ rubriques sont obligatoires : un document qui en oublie une part à la \
validation humaine marqué comme incomplet.

---
name: <identifiant-en-kebab-case, 3 à 6 mots>
description: <une phrase : à quoi sert cette procédure>
---

## Quand l'appliquer
<les conditions de déclenchement, concrètes>

## Ne pas appliquer quand
<les cas voisins où cette procédure ferait du dégât ou perdrait du temps>

## Procédure
1. <étape, en nommant les outils exacts et leurs paramètres décisifs>
2. <…>

## Pièges
<ce qui t'a fait trébucher cette fois-ci, et comment on le repère>

## Terminé quand
<le critère qui dit que c'est fini — de préférence une mesure>

Règles :
- Écris pour un modèle qui exécutera, pas pour un humain qui lira.
- La leçon est dans la CORRECTION, pas dans la tâche : sans elle, tu écrirais \
« fais le travail », ce qui ne vaut rien.
- N'invente aucun outil ni paramètre qui n'apparaît pas ci-dessus.
- Reste sous 30 lignes.
"""

# Les cinq choses que le produit promet à qui relit une procédure : quand
# l'employer, quand s'abstenir, les étapes, les pièges, et le critère de fin.
#
# ⚠️ Pourquoi c'est CONTRÔLÉ et pas seulement demandé (02/09/2026) :
# ``parse_playbook_response`` ne valide que le frontmatter (name +
# description). Un document réduit à « ## Procédure — fais le travail »
# entrait donc au catalogue avec la même apparence qu'une vraie procédure.
# Personne ne le promouvait, et il finissait périmé — une des fabriques des
# 43 compétences périmées sur 98.
#
# Le contrôle AVERTIT, il ne jette pas : voir ``draft_skill_from_success``.
# L'appel de modèle est déjà payé quand on le lit, et l'humain qui valide est
# mieux placé qu'une liste de titres pour dire si le document vaut quelque
# chose — à condition qu'on lui dise ce qui manque.
REQUIRED_SECTIONS = (
    "Quand l'appliquer",
    "Ne pas appliquer quand",
    "Procédure",
    "Pièges",
    "Terminé quand",
)


# ──────────────────────────────────────────────────────────────────────
# Le déclencheur
# ──────────────────────────────────────────────────────────────────────


def _sans_ornement(texte: str) -> str:
    """Minuscules, sans accent, apostrophe droite — pour comparer des titres.

    Un modèle qui écrit « ## PROCEDURE » ou « ## Termine quand » a bien écrit
    la rubrique : recaler son document là-dessus serait de la pédanterie
    d'encodage, et on jetterait des procédures valides.
    """
    plie = unicodedata.normalize("NFKD", (texte or "").lower().replace("’", "'"))
    return "".join(c for c in plie if not unicodedata.combining(c))


def playbook_section_titles(body: str) -> list[str]:
    """Les titres de rubrique du document, TELS QU'ÉCRITS.

    Sert à dire ce qu'on a lu quand il manque une rubrique : « il manque
    Pièges » sans montrer les titres reçus ne permet pas de distinguer une
    dérive de formulation d'un document réellement amputé.
    """
    return [
        ligne.lstrip("#").strip()
        for ligne in (body or "").splitlines()
        if ligne.lstrip().startswith("#")
    ]


# Les verrous qui font d'une procédure un CUL-DE-SAC : elle nomme un outil
# d'auto-diagnostic ET en fait un préalable au travail. Sept procédures de ce
# type, écrites entre le 09/08 et le 31/08/2026, ont paralysé la mission
# « Prospection Market-Comm » du 04/09 — 5 M de tokens, rien d'écrit, statut
# `BLOQUE_CONFIG_TIER`. Leur étape 4 reconnaissait qu'aucun outil ne rendait
# la métadonnée exigée ; leur étape 5 interdisait alors tout appel métier.
_VERROUS_DE_DIAGNOSTIC: tuple[str, ...] = (
    "avant tout outil",
    "avant tout appel",
    "avant toute mutation",
    "avant toute recherche",
    "n'appeler aucun",
    "n'appelle aucun",
    "ne pas appeler",
    "ne poursuis pas",
    "ne pas poursuivre",
    "bloque_config",
    # Le verrou du 04/09 dans sa forme la plus douce : la procédure de
    # prospection écrite le soir même ne disait pas « n'appelle aucun
    # outil », elle disait « ne pas appliquer si le routage primaire exigé
    # n'est pas certifiable ». Même cul-de-sac : rien ne rend cette preuve.
    "certifiable",
    "certifier le routage",
    "tier primaire",
)


def exige_un_auto_diagnostic(body: str) -> bool:
    """Cette procédure conditionne-t-elle le TRAVAIL à un auto-diagnostic ?

    Deux conditions, toutes les deux nécessaires : elle nomme un outil de
    diagnostic (journaux, santé, fournisseurs de modèles) ET elle en fait un
    préalable ou un motif de refus. Citer `system_get_logs` pour répondre à
    « pourquoi ma tâche a échoué » reste une procédure de chat légitime : on
    refuse le VERROU, pas le mot.
    """
    from app.agent.toolset_profiles import outils_exclus_du_profil

    texte = (body or "").lower().replace("\u2019", "'")
    diagnostics = outils_exclus_du_profil("mission")
    if not any(outil in texte for outil in diagnostics):
        return False
    return any(verrou in texte for verrou in _VERROUS_DE_DIAGNOSTIC)


def missing_playbook_sections(body: str) -> list[str]:
    """Les rubriques obligatoires que ce document ne porte pas.

    On lit les LIGNES DE TITRE, pas le corps : « je n'ai pas trouvé de piège »
    au milieu d'un paragraphe ne vaut pas une rubrique « Pièges ».
    """
    titres = [_sans_ornement(t) for t in playbook_section_titles(body)]
    return [
        rubrique for rubrique in REQUIRED_SECTIONS
        if not any(_sans_ornement(rubrique) in titre for titre in titres)
    ]


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

    # Une rubrique manquante AVERTIT, elle ne jette plus (02/09/2026).
    #
    # La version précédente refusait tout le document. Or l'appel de modèle a
    # DÉJÀ été passé et facturé : une simple dérive de formulation (« ## Écueils »
    # au lieu de « ## Pièges ») brûlait un appel par tour sans jamais produire
    # de candidat, et aucune surface ne le montrait — une porte muette est plus
    # coûteuse que le demi-document qu'elle prétend écarter.
    #
    # La vraie porte est ailleurs et n'a pas bougé : le document sort en
    # CANDIDATE, un humain le lit avant qu'il n'entre au catalogue. On lui dit
    # donc ce qui manque, dans la raison qu'il a sous les yeux — pas seulement
    # dans un journal.
    # Une mission ne s'ausculte pas (#378) — elle ne peut pas davantage
    # l'APPRENDRE. Une procédure qui met un auto-diagnostic en préalable du
    # travail ne devient jamais candidate : son verdict ne dépend de rien
    # qu'un outil rende, donc elle bloque pour toujours.
    if exige_un_auto_diagnostic(parsed["body"]):
        logger.warning(
            "skill_from_success : procédure %r REFUSÉE — elle conditionne le "
            "travail à un auto-diagnostic (journaux, santé, fournisseurs). "
            "Une mission ne s'ausculte pas.",
            parsed["name"],
        )
        return None

    manquantes = missing_playbook_sections(parsed["body"])
    raison = (
        "Tirée d'un succès vérifié : la demande n'était pas satisfaite au "
        "premier essai, et la reprise a fonctionné. La procédure décrit ce "
        "qui a comblé l'écart."
    )
    if manquantes:
        titres = playbook_section_titles(parsed["body"])
        logger.warning(
            "skill_from_success : rubriques manquantes (%s) — proposé quand "
            "même. Titres lus : %s",
            ", ".join(manquantes), " | ".join(titres) or "aucun",
        )
        raison += (
            " ⚠️ Document incomplet : il manque " + ", ".join(manquantes)
            + ". Rubriques réellement écrites : "
            + (", ".join(titres) if titres else "aucune") + "."
        )

    return LearnedSkill(
        user_id=user_id,
        name=parsed["name"],
        description=parsed["description"],
        content=parsed["body"],
        frontmatter_json=json.dumps(parsed["frontmatter"], ensure_ascii=False),
        status=SkillStatus.CANDIDATE,
        source=SkillSource.AUTO_GENERATED,
        # Déclaré, jamais laissé au DEFAULT de la colonne : la voie document
        # produit du Markdown, jamais du code, et ça doit se lire sur la ligne
        # avant même qu'elle touche la base.
        content_format=SkillContentFormat.MARKDOWN_PLAYBOOK,
        iteration_count=1,
        rationale=raison,
    )


__all__ = [
    "REQUIRED_SECTIONS",
    "build_success_skill_prompt",
    "draft_skill_from_success",
    "exige_un_auto_diagnostic",
    "missing_playbook_sections",
    "playbook_section_titles",
    "should_propose_skill_from_success",
]
