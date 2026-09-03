# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/auto_tool_generation.py
# @brief      C4-2 — le déclencheur : capacité manquante consignée → rédaction
#             AUTOMATIQUE d'une procédure (défaut), ou d'un outil candidate
#             quand la fabrique est ouverte.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
# =============================================================================
"""Le vrai « auto » de bout en bout (backlog #57, câblé en C4-2).

Depuis juin, la chaîne existait SANS déclencheur : gap consigné → bouton
admin « Générer un outil » → candidate → validation → binding. Ce module la
déclenche tout seul quand `find_tool` consigne une capacité réellement
absente — la vision validée : *« elle crée, me le soumet, je valide, elle
peut l'utiliser »*.

Garde-fous (dans l'ordre) :
  1. Une tentative max PAR GAP et PAR BOOT (``_attempted_cases`` in-process) —
     un gap re-consigné (dédup) ne re-brûle pas du tier-S en boucle.
  2. Pré-check sémantique anti-doublon : si le catalogue contient déjà un
     outil correspondant (trou de binding, leçon Drive/Sheets), on ne génère
     PAS — find_tool amont l'aurait trouvé, mais ce chemin sert aussi
     l'endpoint admin qui n'a pas cette garde.
  3. Drapeau ``auto_tool_generation_enabled`` : il gèle la FABRIQUE, il
     n'éteint pas l'apprentissage (voir ci-dessous).
  4. La sortie est TOUJOURS ``candidate`` (jamais auto-promue) : la
     validation humaine reste le verrou avant tout binding (arbitrage 19/07).

⚠️ LE DRAPEAU GÈLE LA FABRIQUE, IL NE REND PAS LA BOUCLE MUETTE (02/09/2026)
-----------------------------------------------------------------------------
Il sortait par ``return None`` en PREMIÈRE ligne, avant l'aiguillage : le
manque restait consigné dans « Capacités manquantes » et personne n'écrivait
la procédure qui l'aurait comblé. Éteindre la fabrique revenait donc à
éteindre aussi la voie document — exactement le même défaut que la branche
morte corrigée le 24/08, un cran plus haut.

La mesure de cinq mois qui motive le gel (audit 02/09) :

    98 compétences apprises — dont 43 PÉRIMÉES, 13 archivées, 3 graduées
    49 correctifs proposés  — 28 appliqués, TOUS sur des prompts planifiés
     0 exécution d'outil en bac à sable, jamais

La fabrique gelée, une capacité manquante devient une PROCÉDURE. Le code de
la fabrique reste en place, dormant derrière son drapeau : rouvrir le
drapeau rebranche le chemin outil à l'identique.

Best-effort intégral : aucune exception ne remonte au tour utilisateur.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Une tentative par gap et par boot — reset au restart (volontaire : un
# redémarrage offre une seconde chance aux générations échouées).
_attempted_cases: set[int] = set()


def reset_attempts() -> None:
    """Tests uniquement — repart d'un état vierge."""
    _attempted_cases.clear()


async def maybe_generate_for_gap(
    case_id: int, capability: str, user_id: str, *, skip_precheck: bool = False,
) -> dict | None:
    """Comble un gap consigné — par une PROCÉDURE, ou par un outil candidate
    quand la fabrique est ouverte ET que la demande exige une action. Jamais
    levant.

    Retourne le résumé de rédaction ou de génération (dict), ``None`` quand
    une garde a court-circuité (déjà tenté, outil existant, entrées
    invalides). ``skip_precheck=True`` quand la pertinence a DÉJÀ été jugée
    par le modèle (report_missing_capability) — le pré-check lexical n'a pas
    de droit de veto sur ce jugement.
    """
    try:
        from app.config import get_settings

        if not case_id or not capability or not user_id:
            return None
        if case_id in _attempted_cases:
            logger.debug("auto_tool_gen: gap #%s déjà tenté ce boot — skip", case_id)
            return None
        _attempted_cases.add(case_id)

        # 2. Pré-check sémantique : existe-t-il DÉJÀ un outil pour ça ?
        if not skip_precheck:
            from app.skills.builtin.find_tool_skill import (
                capability_has_existing_tool,
            )

            # V0-4 : `user_id` étend le pré-check aux outils DÉJÀ FABRIQUÉS
            # pour cet utilisateur (candidates non promues, archivés,
            # rejetés) — la source invisible qui produisait 5 générations du
            # même outil en 32 minutes (audit §3.2).
            existing = await capability_has_existing_tool(capability, user_id=user_id)
            if existing:
                logger.info(
                    "auto_tool_gen: gap #%s « %.60s » couvert par l'outil "
                    "existant %r — pas de génération (trou de binding, pas de "
                    "capacité absente)",
                    case_id, capability, existing,
                )
                return None

        # 3. LA FABRIQUE EST-ELLE OUVERTE ? (gel du 02/09/2026)
        #
        # Le drapeau ne coupe plus la boucle : il retire l'issue « outil » de
        # l'aiguillage. Une fabrique gelée ne rend pas la question « outil ou
        # compétence ? » plus intéressante — quelle que soit la réponse, seule
        # la procédure peut sortir. On ne paie donc PAS le juge : c'était un
        # appel de modèle dont le verdict ne changeait plus rien.
        # ⚠️ UN DRAPEAU ILLISIBLE VAUT « GELÉE » (02/09/2026, 3e relecture).
        #
        # Cette lecture vivait dans le `try` général : quand elle levait, on
        # sortait par `return None` — alors que `find_tool` venait d'annoncer
        # « une procédure est en cours de rédaction » (lui lit le drapeau
        # défensivement, et illisible y vaut déjà « gelée »). Le `case_id`
        # était en plus déjà brûlé dans `_attempted_cases` : plus aucune
        # reprise possible dans ce boot. Rien n'était écrit, rien ne pouvait
        # plus l'être, et le message avait promis le contraire. Les deux
        # lectures doivent tomber du même côté.
        try:
            fabrique_ouverte = bool(get_settings().auto_tool_generation_enabled)
        except Exception as exc:  # noqa: BLE001 — un drapeau illisible ne coupe rien
            logger.warning(
                "auto_tool_gen: drapeau de fabrique illisible (%s) — gap #%s "
                "traité comme fabrique GELÉE", exc, case_id,
            )
            fabrique_ouverte = False

        if not fabrique_ouverte:
            from app.services.learning.skill_creator import draft_playbook_for_gap

            resultat = await draft_playbook_for_gap(case_id, user_id)
            logger.info(
                "auto_tool_gen: fabrique gelée — gap #%s « %.60s » traité en "
                "PROCÉDURE : %s", case_id, capability, resultat.get("status"),
            )
            return resultat

        # L'AIGUILLAGE — OUTIL ou COMPÉTENCE ? — règle de Franck du 29/07/2026.
        #
        #     « Soit la demande peut être réglée par un modèle et dans ce cas
        #       ce n'est pas un outil qu'il faut mais une skill ; soit elle
        #       nécessite une ou plusieurs ACTIONS et là il faut un outil. »
        #
        # Les gardes ci-dessus ne répondaient qu'à « existe-t-il DÉJÀ un
        # outil ? ». Aucune ne demandait s'il en fallait un — d'où des outils
        # fabriqués pour ce qu'un modèle règle en une phrase, puis jamais
        # utilisés. Le jugement part sur le niveau S (modèle LOCAL, coût nul)
        # et cette fonction tourne déjà en tâche de fond.
        from app.services.learning.tool_or_skill import needs_a_tool

        # `user_id` transmis pour que l'appel soit RATTACHABLE : sans lui, la
        # ligne d'usage n'est pas écrivable (clé étrangère) et ce chemin
        # redeviendrait invisible.
        if not await needs_a_tool(capability, user_id=user_id):
            # ⚠️ CETTE BRANCHE NE MENAIT NULLE PART (corrigé le 24/08).
            #
            # Le juge tranchait bien, et on faisait `return None` : le manque
            # restait consigné dans « Capacités manquantes » et personne
            # n'écrivait la procédure qui l'aurait comblé. La moitié « outil »
            # de l'aiguillage était branchée, la moitié « compétence » non.
            #
            # C'est le modèle d'Hermes appliqué ici : une capacité nouvelle
            # devient un DOCUMENT (`markdown_playbook`, format `SKILL.md`), pas
            # un outil. Un playbook coûte des caractères de prompt, plafonnés ;
            # un outil coûte un schéma JSON à chaque tour, pour toujours. C'est
            # la différence entre une croissance bornée et une croissance
            # linéaire — la crainte de Franck, et sa réponse.
            from app.services.learning.skill_creator import draft_playbook_for_gap

            resultat = await draft_playbook_for_gap(case_id, user_id)
            logger.info(
                "auto_tool_gen: gap #%s « %.60s » relève d'une COMPÉTENCE — "
                "playbook : %s", case_id, capability, resultat.get("status"),
            )
            return resultat

        logger.info(
            "auto_tool_gen: génération candidate pour gap #%s « %.80s »",
            case_id, capability,
        )
        from app.services.learning.tool_creator import generate_and_persist_tool

        summary = await generate_and_persist_tool(
            task_description=capability,
            user_id=user_id,
            from_failure_case_ids=[case_id],
        )
        if summary.get("status") == "created":
            from app.services.learning.candidate_notify import notify_candidate

            await notify_candidate(summary.get("tool_name", "?"), capability)
            # NB : notify est best-effort et avale ses erreurs — ne pas
            # affirmer « envoyée » ici (le succès réel est loggé par _push).
            logger.info(
                "auto_tool_gen: candidate %r créée pour gap #%s (notification demandée)",
                summary.get("tool_name"), case_id,
            )
        else:
            # Pas de notification d'échec (bruit) — le gap reste ouvert dans
            # « Capacités manquantes », l'admin garde le bouton manuel.
            logger.info(
                "auto_tool_gen: génération non aboutie pour gap #%s (status=%s)",
                case_id, summary.get("status"),
            )
        return summary
    except Exception as exc:  # noqa: BLE001 — ne casse jamais le tour
        logger.warning("auto_tool_gen: échec silencieux pour gap #%s: %s", case_id, exc)
        return None
