# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/todo_tool.py
# @brief      Le carnet d'étapes de la conversation — un seul outil qui écrit
#             et qui lit, et qui rend toujours le plan complet.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Où Ely en est dans une demande à plusieurs étapes — 02/09/2026.

LE DÉFAUT
----------
Sur « télécharge les trois factures, renomme-les, range-les dans Drive », Ely
n'avait aucun endroit où écrire son avancement. Le plan ne vivait que dans le
fil de messages, c'est-à-dire dans ce que la troncature supprime en premier
(``preserve_first`` coupe par l'avant). D'où les deux symptômes connus : des
étapes refaites, et des étapes oubliées.

LES SIX CHOIX DE CONCEPTION, ET LEUR RAISON
--------------------------------------------
1. **Un seul outil qui écrit ET qui lit.** Appelé sans argument il rend le
   plan, appelé avec une liste il la remplace. Deux outils auraient doublé le
   coût de catalogue pour un état qui tient en dix lignes.
2. **Il rend TOUJOURS le plan complet**, y compris quand il refuse. L'état
   revient donc dans le contexte par le résultat d'outil, sans qu'aucun prompt
   système n'ait à le porter — et les petits modèles lisent un tool result
   bien plus fidèlement qu'une consigne posée trente messages plus tôt.
3. **Une seule étape en cours, par construction** : ``en_cours`` est un
   numéro, pas un état par ligne. Deux étapes en cours ne sont pas
   représentables, donc pas à interdire.
4. **Toute la consigne de comportement vit dans la DESCRIPTION de l'outil**,
   pas dans le prompt système. Elle voyage ainsi dans le schéma mis en cache :
   elle est déjà payée, et elle arrive avec l'outil plutôt qu'en préambule.
5. **Remplacer la liste remet l'avancement à zéro.** Un numéro d'étape ne veut
   plus rien dire quand la liste change ; garder l'ancien curseur cocherait
   une tâche au hasard.
6. **``faites`` ENRICHIT l'avancement, il ne le remplace pas.** Relecture du
   02/09/2026 : il remplaçait, et rien ne le disait au modèle. Un modèle qui
   rapporte son avancement pas à pas — « je viens de finir la 2 » — décochait
   la 1 et la refaisait, le défaut même que cet outil existe pour supprimer.
   L'arbitrage se juge sur l'OUBLI : en remplacement, un rapport incomplet
   DÉTRUIT de l'information ; en enrichissement, il n'en détruit aucune.
   Décocher reste possible, mais demande un geste explicite : ``a_refaire``.

LES BORNES, ET POURQUOI ELLES NE SE COMPORTENT PAS PAREIL
-----------------------------------------------------------
- Une liste de plus de ``_MAX_TACHES`` entrées est **REFUSÉE**. La couper
  ferait croire au modèle qu'il suit un travail dont les dernières étapes ont
  disparu : un plan avec des trous invisibles est pire qu'un refus, auquel il
  peut réagir.
- Une entrée plus longue que ``_MAX_LONGUEUR`` est **COUPÉE**. C'est une
  étiquette ; sa fin n'apprend rien, et jeter un plan valide pour une ligne
  bavarde coûterait un tour de modèle pour rien.
- Le registre est borné en nombre de conversations, comme
  ``discovered_tools``. Une différence assumée avec lui : on réinsère la
  conversation à chaque appel, LECTURE COMPRISE, si bien que l'éviction se
  fait par RÉCENCE et non par ordre d'apparition — perdre le plan d'une
  conversation vivante parce que 500 autres se sont ouvertes serait le pire
  moment pour l'oublier. La lecture compte parce que relire son plan est
  justement un signe de vie (relecture du 02/09/2026 : seule l'écriture
  rafraîchissait, et une conversation qui consultait son plan sans le changer
  restait la première évincée).

CE QUE CE LOT NE LIVRE PAS
---------------------------
La réinjection du plan à la compaction du contexte — en ne gardant QUE les
étapes non terminées, les terminées faisant refaire du travail déjà fait.
Elle demande de toucher au nœud agent, en chantier par ailleurs.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Final

from langchain_core.tools import tool

from app.agent.tool_context import CURRENT_CONVERSATION_ID
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)

# Les marqueurs d'état, exportés : les tests les lisent plutôt que de recopier
# une chaîne, et le rendu peut changer sans les rendre faux.
MARQUEUR_A_FAIRE: Final[str] = "[ ]"
MARQUEUR_EN_COURS: Final[str] = "[>]"
MARQUEUR_FAITE: Final[str] = "[x]"

# Un plan de plus de 20 étapes n'est plus un plan : c'est une demande qu'il
# fallait découper. Au-delà, le rendu seul mangerait le contexte qu'il sert.
_MAX_TACHES: Final[int] = 20
# Une étape est une étiquette, pas une consigne. 200 caractères tiennent sur
# une ligne de rendu et suffisent à se reconnaître.
_MAX_LONGUEUR: Final[int] = 200
# Pire cas : 500 x 20 x 200 = 2 Mo. Un serveur qui tourne des mois ne doit pas
# garder le plan de chaque conversation jamais close.
_MAX_CONVERSATIONS: Final[int] = 500


@dataclass(frozen=True)
class _Plan:
    """Le plan d'UNE conversation. Immuable : on remplace, on ne modifie pas —
    un état partiellement écrit sous verrou serait un plan menteur."""

    taches: tuple[str, ...] = ()
    en_cours: int = 0                       # numéro 1..N, 0 = aucune
    faites: frozenset[int] = field(default_factory=frozenset)


_verrou = threading.Lock()
_registre: dict[str, _Plan] = {}


# Un modèle qui écrit ses étapes comme des objets (``{"id": 5, "texte": …}``)
# plutôt que des chaînes — vu en production le 03/09/2026 — se faisait refuser
# tout le plan par le schéma. On lit le champ qui porte le texte ; à défaut,
# la forme JSON de l'objet, lisible et stable.
_CLES_DE_TEXTE: Final[tuple[str, ...]] = (
    "texte", "text", "title", "titre", "tache", "task", "label", "name",
)


def _texte_de(brute: object) -> str:
    if isinstance(brute, dict):
        for cle in _CLES_DE_TEXTE:
            valeur = brute.get(cle)
            if isinstance(valeur, str):
                return valeur          # vide compris : c'est une étape vide
        return json.dumps(brute, ensure_ascii=False)
    return str(brute or "")


def _normaliser(taches: list[str | dict]) -> tuple[str, ...]:
    """Une étape par ligne, coupée, sans entrée vide.

    Les sauts de ligne sont écrasés : une étape qui s'étale sur trois lignes
    casse le rendu numéroté, qui est justement ce qui rend le plan lisible
    d'un coup d'œil.
    """
    propres: list[str] = []
    for brute in taches:
        texte = " ".join(_texte_de(brute).split())
        if texte:
            propres.append(texte[:_MAX_LONGUEUR])
    return tuple(propres)


def _rendu(plan: _Plan) -> str:
    if not plan.taches:
        return "Aucune étape notée dans cette conversation."
    lignes = [f"Plan — {len(plan.taches)} étape(s), {len(plan.faites)} faite(s) :"]
    for numero, texte in enumerate(plan.taches, start=1):
        if numero in plan.faites:
            marqueur = MARQUEUR_FAITE
        elif numero == plan.en_cours:
            marqueur = MARQUEUR_EN_COURS
        else:
            marqueur = MARQUEUR_A_FAIRE
        lignes.append(f"  {numero}. {marqueur} {texte}")
    return "\n".join(lignes)


def etapes_restantes(conversation_id: str) -> str:
    """Les étapes NON terminées du plan de cette conversation, numérotées
    comme dans le rendu complet — ou ``""`` s'il n'y a rien à rappeler.

    C'est ce que la compaction du contexte réinjecte (03/09/2026) : les
    étapes faites en sont absentes à dessein, les rappeler ferait refaire
    du travail déjà fait."""
    if not conversation_id:
        return ""
    with _verrou:
        plan = _registre.get(conversation_id)
    if plan is None or not plan.taches:
        return ""
    lignes = []
    for numero, texte in enumerate(plan.taches, start=1):
        if numero in plan.faites:
            continue
        marqueur = MARQUEUR_EN_COURS if numero == plan.en_cours else MARQUEUR_A_FAIRE
        lignes.append(f"  {numero}. {marqueur} {texte}")
    if not lignes:
        return ""
    return "[Plan de la conversation — étapes restantes]\n" + "\n".join(lignes)


def oublier(conversation_id: str) -> None:
    """Oublie le plan de cette conversation. Appelé quand une mission est
    relancée : sans ça, son premier ``session_todo`` rendait le plan de
    l'exécution précédente, étapes déjà cochées (04/09/2026)."""
    if not conversation_id:
        return
    with _verrou:
        _registre.pop(conversation_id, None)


def _refus(motif: str, plan: _Plan) -> str:
    """Un refus rend le plan INCHANGÉ avec lui : sans ça, le modèle devrait
    rappeler l'outil pour savoir ce qu'il a encore en mémoire."""
    return f"{motif}\n{_rendu(plan)}"


@register(
    domain=Domain.UNIVERSAL,
    skill_name="session_todo",
    skill_display_name="Carnet d'étapes",
    skill_description=(
        "Tenir le plan des étapes d'une demande en plusieurs temps, le temps "
        "de la conversation."
    ),
    skill_icon="🗒️",
)
@tool
async def session_todo(
    taches: list[str | dict] | None = None,
    en_cours: int | None = None,
    faites: list[int] | None = None,
    a_refaire: list[int] | None = None,
) -> str:
    """Le plan des étapes de cette conversation. Sans argument, il le relit.

    Appelle-le dès qu'une demande fait plus de deux étapes, puis à chaque
    changement d'état. Éphémère : une tâche à retrouver demain, c'est
    tasks_create.
    `taches` remplace toute la liste et remet l'avancement à zéro ; omets-la
    pour ne bouger que l'avancement. `en_cours`, `faites` et `a_refaire` sont
    des numéros (1..N, 0 = aucune) : une seule étape en cours, et rien n'est
    « fait » avant d'avoir été VÉRIFIÉ. `faites` S'AJOUTE : une étape cochée
    le reste, envoie seulement les nouvelles ; `a_refaire` décoche.
    """
    # ⚠️ Sans identifiant, tout partage un même seau. Ça n'arrive pas depuis le
    # chat ni depuis une mission, qui posent tous deux la variable ; on préfère
    # un carnet partagé à un outil muet, qui ferait conclure au modèle qu'il ne
    # sait pas tenir de liste.
    conversation = CURRENT_CONVERSATION_ID.get()
    lecture_seule = (
        taches is None and en_cours is None and faites is None and a_refaire is None
    )

    with _verrou:
        plan = _registre.get(conversation, _Plan())
        if lecture_seule:
            # Relire son plan est un signe de vie : la lecture rafraîchit donc
            # la récence elle aussi (relecture du 02/09/2026). On ne réinsère
            # que ce qui existe déjà : une conversation inconnue n'a pas à
            # occuper une place du registre pour un plan vide.
            if conversation in _registre:
                _registre[conversation] = _registre.pop(conversation)
            return _rendu(plan)

        candidat = plan
        if taches is not None:
            if len(taches) > _MAX_TACHES:
                return _refus(
                    f"Refusé : {len(taches)} entrées pour un maximum de "
                    f"{_MAX_TACHES}. Regroupe les étapes, le plan est "
                    f"inchangé.",
                    plan,
                )
            candidat = _Plan(taches=_normaliser(taches))

        total = len(candidat.taches)
        vise = candidat.en_cours if en_cours is None else int(en_cours)
        if not 0 <= vise <= total:
            return _refus(
                f"Refusé : pas d'étape n°{vise} dans un plan de {total} "
                f"étape(s). Le plan est inchangé.",
                plan,
            )
        # On valide les numéros DEMANDÉS, pas l'ensemble résultant : décocher
        # une étape qui n'existe pas passerait sinon pour un no-op silencieux,
        # alors que le modèle se trompe de plan.
        demandes = {int(n) for n in (faites or ())} | {int(n) for n in (a_refaire or ())}
        hors = sorted(n for n in demandes if not 1 <= n <= total)
        if hors:
            return _refus(
                f"Refusé : pas d'étape n°{hors[0]} dans un plan de {total} "
                f"étape(s). Le plan est inchangé.",
                plan,
            )
        # `faites` ENRICHIT au lieu de remplacer : un modèle qui ne rapporte que
        # l'étape qu'il vient de finir décochait les précédentes et les refaisait
        # (relecture du 02/09/2026). Décocher demande le geste explicite
        # `a_refaire`, si bien qu'un rapport incomplet ne détruit rien.
        cochees = set(candidat.faites) | {int(n) for n in (faites or ())}
        cochees -= {int(n) for n in (a_refaire or ())}

        candidat = _Plan(candidat.taches, vise, frozenset(cochees))
        # Réinsertion : la conversation touchée redevient la plus récente, donc
        # la dernière à être évincée (cf. docstring du module).
        _registre.pop(conversation, None)
        _registre[conversation] = candidat
        while len(_registre) > _MAX_CONVERSATIONS:
            evincee = next(iter(_registre))
            _registre.pop(evincee)
            logger.debug("session_todo : plan de %s évincé (registre plein)", evincee)

    return _rendu(candidat)
