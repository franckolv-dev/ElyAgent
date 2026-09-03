# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/playbook_usage.py
# @brief      Une procédure ne compte pas parce qu'on l'a livrée — parce qu'elle
#             a servi.
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
"""Le compteur d'usage des playbooks injectés — 02/09/2026.

Le trou, mesuré
---------------
    98 compétences apprises   dont 43 PÉRIMÉES, 13 archivées

``use_count`` n'était incrémenté que par trois chemins :

  - ``skill_view`` — **0 appel depuis toujours** (cf. ``active_skills``) ;
  - ``find_tool``, quand sa recherche remonte une procédure ;
  - l'invocation d'un ``python_tool`` (``learned_tools_runtime``).

Or depuis le 28/07 le chemin NOMINAL d'un playbook est tout autre : sa
procédure est écrite directement dans le prompt par
``active_skills.format_active_skills_block``. Une procédure chargée à chaque
conversation affichait donc ``use_count = 0``. Deux conséquences en chaîne :

  1. ``skill_curator`` la faisait passer ``active -> stale -> archived`` —
     on archivait ce qui travaillait ;
  2. ``get_active_skills_for_user`` ordonne par ``use_count desc`` : les
     procédures réellement suivies étaient triées bonnes dernières.

Pourquoi on ne compte PAS l'injection
--------------------------------------
C'était la correction évidente, et elle aurait été pire que le mal. Les 20
playbooks du prompt auraient marqué +1 par conversation : plus rien n'aurait
jamais péri, le curateur n'aurait plus eu de matière, et le chiffre n'aurait
plus rien dit de la CONSOMMATION — exactement le défaut qu'on répare. Livrer
n'est pas consommer.

Ce qu'on compte, et ce que ça vaut
-----------------------------------
UNE procédure par tour, au plus : celle qui colle le mieux à ce qui s'est
passé. Concrètement, parmi les procédures **réellement détaillées dans le
prompt**, celle dont le plus grand nombre d'outils prescrits ont été appelés
pendant le tour. À égalité, on ne compte RIEN.

⚠️ Ce n'est pas une preuve, c'est une PRÉSOMPTION, et la première version de ce
module promettait plus que ça (« la procédure a démonstrablement pesé sur ce
qui s'est passé »). Elle marquait toute procédure citant un outil appelé :
mesuré, trois procédures livrées citant toutes la recherche web voyaient leur
compteur monter pour UN seul appel de recherche. Ce n'est pas un cas limite,
c'est structurel — la sélection est re-rankée sur la question, donc les
procédures co-livrées sont précisément celles qui partagent leur outillage.

Le chiffre est donc un PLANCHER : il sous-compte (une égalité, deux procédures
suivies dans le même tour, un tour sans outil) et ne sur-compte pas. C'est le
sens qu'on veut, puisqu'il sert à décider ce qu'on archive.

Deux garde-fous de lecture, dans le même esprit :

  - la rubrique « Ne pas appliquer quand » est RETIRÉE avant rapprochement :
    un outil nommé pour dire de s'en abstenir n'est pas un usage ;
  - le rapprochement se fait sur des JETONS, pas des sous-chaînes :
    ``web_search`` ne marque pas une procédure qui ne parle que de
    ``web_search_deep``.

On lit le bloc INJECTÉ, on ne le rejoue pas
--------------------------------------------
La première version reconstruisait la sélection du prompt pour savoir quoi
compter. Or cette sélection est triée par le compteur lui-même : une procédure
sous la coupe n'était jamais livrée en entier, donc jamais comptée, donc son
compteur restait à zéro, donc elle ne remontait jamais — et le curateur
l'archivait pour inactivité. Le zéro avait l'air mérité ; il était fabriqué.

On lit donc le texte que le modèle a EU SOUS LES YEUX : le snapshot mémoire
figé de la conversation (``frozen_memory``) contient le bloc
``<learned_skills>`` tel qu'il a été injecté. Rien à reconstruire, rien à
re-trier, aucune boucle. Pas de snapshot (conversation sans identifiant,
snapshot évincé) = pas de preuve = on ne compte rien.

Ce qui reste vrai, et qu'on assume : ``use_count`` départage encore l'ordre
legacy de la sélection. Une procédure jamais livrée reste donc à zéro — mais
c'est désormais une information JUSTE (« jamais montrée, donc jamais suivie »)
et non plus un artefact de mesure. Au-delà du plafond d'injection, c'est la
PERTINENCE qui choisit (re-rank sur la question d'ouverture), pas le compteur.

Où le chiffre se voit
---------------------
``GET /api/me/learning-skills`` rend déjà ``use_count`` et ``last_used_at``, et
la page des compétences les affiche (« Utilisée N fois » / « Jamais
utilisée »). Rien à ouvrir côté routeur ni côté frontend pour le lire.

Où ça tourne
------------
En tâche de fond, après le tour (leçon de #286). Un compteur est du confort :
toute erreur est avalée, le tour n'en sait jamais rien.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select, update

from app.database import async_session
from app.models.learned_skill import LearnedSkill, SkillStatus

logger = logging.getLogger(__name__)

# En dessous, un « nom d'outil » est trop court pour être une preuve de quoi
# que ce soit — il apparaîtrait par hasard dans n'importe quelle prose.
_MIN_TOOL_NAME = 3

_JETON = re.compile(r"[a-z0-9_]+")

# La rubrique qui dit de S'ABSTENIR (cf. ``skill_from_success``). Les outils
# qu'elle nomme sont des contre-indications : les compter reviendrait à créditer
# une procédure de ce qu'elle déconseille.
_RUBRIQUE_ANTI = "ne pas appliquer quand"


def _sans_accent(texte: str) -> str:
    plie = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in plie if not unicodedata.combining(c))


def _jetons(texte: str) -> set[str]:
    """Les identifiants présents dans un texte, en minuscules.

    Les ``_`` sont gardés dans le jeton : ``web_search_deep`` est UN jeton, et
    ne peut donc pas être marqué par l'outil ``web_search``.
    """
    return set(_JETON.findall((texte or "").lower()))


def _texte_prescriptif(content: str) -> str:
    """La procédure SANS sa rubrique « Ne pas appliquer quand »."""
    gardees: list[str] = []
    dans_anti = False
    for ligne in (content or "").splitlines():
        if ligne.lstrip().startswith("#"):
            dans_anti = _RUBRIQUE_ANTI in _sans_accent(ligne)
            if dans_anti:
                continue
        if not dans_anti:
            gardees.append(ligne)
    return "\n".join(gardees)


def tools_prescribed_and_called(
    content: str, tools_called: Iterable[str],
) -> set[str]:
    """Les outils appelés pendant le tour que cette procédure PRESCRIT.

    C'est toute la matière de la décision : sa TAILLE dit à quel point la
    procédure colle au tour. Un ensemble vide veut dire « rien ne rattache ce
    tour à cette procédure ».
    """
    jetons = _jetons(_texte_prescriptif(content))
    if not jetons:
        return set()
    return {
        nom.lower() for nom in (tools_called or [])
        if nom and len(nom) >= _MIN_TOOL_NAME and nom.lower() in jetons
    }


def closest_playbook(
    playbooks: Iterable[tuple[str, str]], tools_called: Iterable[str],
) -> str | None:
    """La procédure la plus proche du tour, ou ``None`` s'il y a doute.

    ``playbooks`` : des couples ``(identifiant, procédure)``. Rend l'identifiant
    de celle dont l'ensemble « outils prescrits ET appelés » est STRICTEMENT le
    plus grand. Aucune gagnante à égalité : deux procédures que la même trace
    d'outils explique aussi bien ne se départagent pas, et en créditer une au
    hasard — ou les deux — est précisément le sur-comptage qu'on répare.

    Biais connu et assumé : à outillage partagé, une procédure qui nomme
    beaucoup d'outils l'emporte sur une plus courte. Elle décrit alors
    effectivement mieux le tour ; et le sens du compteur (sous-compter plutôt
    que gonfler) est préservé dans les deux cas.
    """
    preuves = [
        (identifiant, tools_prescribed_and_called(procedure, tools_called))
        for identifiant, procedure in playbooks
    ]
    tailles = sorted((len(p) for _id, p in preuves), reverse=True)
    if not tailles or tailles[0] == 0:
        return None
    if len(tailles) > 1 and tailles[1] == tailles[0]:
        return None
    return next(identifiant for identifiant, p in preuves if len(p) == tailles[0])


async def record_playbooks_served(
    user_id: str, tools_called: Iterable[str], prompt_block: str,
) -> list[str]:
    """Compte comme SERVIE la procédure la plus proche du tour, s'il y en a une.

    ``prompt_block`` est le texte RÉELLEMENT injecté (le snapshot figé de la
    conversation) : on n'en garde que les procédures détaillées, celles dont le
    modèle a eu la marche à suivre sous les yeux. Une procédure seulement
    NOMMÉE — hors budget de contenu — n'a rien pu servir.

    Rend la liste des identifiants comptés (zéro ou un). Ne lève jamais : un
    compteur ne casse pas un tour ; en cas de panne on rend ``[]`` et le
    curateur travaille sur des chiffres un peu vieux, ce qui est sans gravité.

    Deux exclusions découlent de la lecture du bloc, et elles ne sont pas
    cosmétiques :

      - une ``candidate`` n'est jamais injectée : elle n'a rien pu servir, et
        la compter ferait passer pour éprouvée une procédure que personne n'a
        validée ;
      - un ``python_tool`` n'est pas récité dans le bloc (il est bindé) et il
        est déjà compté à chaque invocation par ``learned_tools_runtime`` — le
        recompter ici doublerait la gate « invocations » de la graduation.
    """
    outils = [str(n) for n in (tools_called or []) if n]
    if not user_id or not outils or not prompt_block:
        return []
    try:
        from app.services.learning.active_skills import playbook_names_in_block

        noms = playbook_names_in_block(prompt_block)
        if not noms:
            return []
        async with async_session() as db:
            rows = list((await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.name.in_(noms),
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
            )).scalars().all())
            servi = closest_playbook(
                [(s.id, s.content or "") for s in rows], outils,
            )
            if servi is None:
                logger.debug(
                    "playbooks servis : %d procédure(s) livrée(s), aucune ne se "
                    "détache des outils du tour — rien compté", len(rows),
                )
                return []
            await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id == servi)
                .values(
                    use_count=LearnedSkill.use_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            logger.info(
                "playbooks servis : 1 procédure comptée sur %d livrée(s) et "
                "retrouvée(s) pour %s", len(rows), (user_id or "?")[:8],
            )
            return [servi]
    except Exception as exc:  # noqa: BLE001 — un compteur ne casse pas un tour
        logger.debug("playbook_usage : comptage abandonné (%s)", exc)
        return []


def _bloc_injecte(conversation_id: str) -> str:
    """Le snapshot mémoire figé de cette conversation, ou ``""``.

    ⚠️ Lecture DIRECTE du cache (même geste que ``routers/admin.py``). Le seul
    accès public, ``get_or_build``, CONSTRUIT en cas de défaut : appelé depuis
    un compteur, il écrirait un snapshot bâti hors du tour dans le cache de la
    conversation, et le tour suivant en hériterait. Un compteur ne doit rien
    changer à ce que le modèle verra.
    """
    if not conversation_id:
        return ""
    try:
        from app.services import frozen_memory

        entree = frozen_memory._snapshots.get(conversation_id)
        return (entree or {}).get("snapshot", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("playbook_usage : snapshot illisible (%s)", exc)
        return ""


def schedule_playbook_usage(
    user_id: str, messages: list, conversation_id: str,
) -> bool:
    """Programme le comptage après le tour. Rend True si c'est parti.

    N'attend rien : la réponse de l'utilisateur ne doit jamais payer un
    compteur (leçon de #286, où l'introspection tournait dans la boucle du
    tour).

    Trois sorties sèches, et chacune vaut « on ne sait pas, donc on ne compte
    pas » : un tour sans aucun appel d'outil (aucune trace à rapprocher), une
    conversation sans identifiant, un snapshot absent (donc aucune trace de ce
    qui a été injecté). Le bloc est lu ICI, tant que la conversation est
    vivante — la tâche de fond, elle, peut tourner après sa fermeture.
    """
    if not user_id:
        return False
    try:
        from app.services.learning.facade_detection import (
            tools_called_from_messages,
        )

        outils = tools_called_from_messages(messages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("playbook_usage : outils du tour illisibles (%s)", exc)
        return False
    if not outils:
        return False

    bloc = _bloc_injecte(conversation_id)
    if not bloc:
        logger.debug(
            "playbook_usage : aucun bloc injecté connu pour cette conversation "
            "— rien compté",
        )
        return False

    try:
        from app.services.background_tasks import spawn

        spawn(
            record_playbooks_served(user_id, outils, bloc),
            label="playbooks_servis",
            detach_context=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("playbook_usage : ordonnancement impossible (%s)", exc)
        return False
    return True


__all__ = [
    "closest_playbook",
    "record_playbooks_served",
    "schedule_playbook_usage",
    "tools_prescribed_and_called",
]
