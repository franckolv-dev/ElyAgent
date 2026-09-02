# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/nodes.py
# @brief      LangGraph agent node definitions
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, Optional
import os
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.state import AgentState
from app.services.background_tasks import spawn
from app.services.llm_deadline import ainvoke_with_deadline
from app.services.routing_trace import note as routing_note
from app.skills.preferences_runtime import (
    appliquer as appliquer_preferences,
    disabled_tool_names,
)
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.llm_provider import get_fallback_llms
from app.services import fallback_manager as _fb
from app.services import system_prompt_cache as _spc
from app.services import frozen_memory as _frozen_mem
from app.services.intent_router import get_intent_router
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS, SecurityFilter

logger = logging.getLogger(__name__)


# ── La frontière d'envoi du prompt système (02/09/2026) ─────────────────────
#
# Filtre PII que l'APPELANT tient déjà pour ce tour. Les missions n'utilisent
# pas le registre par `conversation_id` mais une clé préfixée
# (`mission:<id>`, cf. `agent/missions/pii.py`) : sans ce canal, ce module
# ouvrirait un SECOND vault sur la même conversation, et les placeholders
# posés ici seraient irrésolubles — ou pire, résolus vers la mauvaise valeur
# — au moment de rendre le résumé à l'utilisateur.
#
# Posée par l'appelant AVANT d'invoquer le graphe ; les ContextVars sont
# copiées à la création de chaque tâche asyncio, donc elle traverse LangGraph.
FILTRE_PII_DU_TOUR: ContextVar[Optional[SecurityFilter]] = ContextVar(
    "FILTRE_PII_DU_TOUR", default=None,
)


def prompt_systeme_sortant(system: str, llm: Any, conversation_id: str) -> str:
    """Le prompt système tel qu'il a le droit de QUITTER la machine.

    L'invariant de souveraineté d'Ely ne portait que sur les MESSAGES : chaque
    surface (chat, voix, canaux, planificateur) anonymise ce que l'utilisateur
    a tapé, personne n'anonymisait le prompt système — qui porte pourtant le
    profil, les souvenirs et les contraintes, c'est-à-dire l'essentiel de ce
    qu'Ely sait de quelqu'un.

    La frontière est le RÉSEAU, pas le prompt : un modèle qui tourne sur cette
    machine reçoit le clair, parce que l'anonymiser ne protégerait rien et lui
    coûterait de la qualité (un petit modèle local raisonne mal sur
    « [EMAIL_0] »). Tout le reste passe par le filtre.

    Posée ICI plutôt qu'à la composition du prompt parce que c'est le seul
    endroit qui connaît le modèle RÉELLEMENT retenu : la voie compacte, la
    voie complète, le SLM et les replis convergent tous vers un `ainvoke`.

    Échoue FERMÉ : rien n'est rattrapé. Une anonymisation qui lève tue le
    tour, elle ne le laisse pas partir en clair.
    """
    from app.services.qwen_no_think import is_local_openai_llm

    if is_local_openai_llm(llm):
        return system
    filtre = FILTRE_PII_DU_TOUR.get()
    if filtre is None:
        from app.services.conversation_filters import get_filter

        # Sans conversation, pas de vault partagé : un filtre neuf plutôt que
        # `get_filter("")`, qui serait un vault COMMUN à tous les tours sans
        # identité — la fuite d'à côté.
        filtre = get_filter(conversation_id) if conversation_id else SecurityFilter()
    return filtre.anonymize(system, ner_detection=False)


async def _no_interactions() -> list[dict]:
    """Cheap placeholder for get_relevant_interactions on the first turn."""
    return []


# Moved to app/agent/helpers/message_sanitizer.py (refactor 2026-05-25 Phase 1.2).
from app.agent.helpers.message_sanitizer import (  # noqa: E402,F401
    _sanitize_messages_for_mistral,
)

# ------------------------------------------------------------------ #
# System prompt                                                        #
# ------------------------------------------------------------------ #
# Constants moved to app/agent/prompts.py (refactor 2026-05-25 Phase 1.1).
# Re-exported below so external consumers (learning/ab_testing,
# learning/prompt_version, test_system_prompt_size) keep working.
from app.agent.prompts import _SYSTEM_PROMPT_BASE, _SYSTEM_PROMPT_SLM  # noqa: E402,F401


# Moved to app/agent/helpers/message_sanitizer.py (refactor 2026-05-25 Phase 1.2).
from app.agent.helpers.message_sanitizer import _tool_result  # noqa: E402,F401


# Moved to app/agent/helpers/tool_history.py (refactor 2026-05-25 Phase 1.3).
from app.agent.helpers.tool_history import (  # noqa: E402,F401
    _HEAVY_FIELDS,
    _HEAVY_FIELD_THRESHOLD,
    _sanitize_tool_result_for_history,
)


# Moved to app/agent/helpers/bind_tools.py (refactor 2026-05-25 Phase 1.4).
from app.agent.helpers.bind_tools import (  # noqa: E402,F401
    _BTS_TAG,
    _bind_tools_smart,
    _classify_model_family,
    _extract_model_name,
)


# ------------------------------------------------------------------ #
# Tools that need automatic argument injection                        #
# ------------------------------------------------------------------ #
# Canonical sets live in tool_sets.py — import from there.

from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS  # noqa: E402


# ------------------------------------------------------------------ #
# Lightweight system prompt for SLM (simple tasks, no memory needed) #
# ------------------------------------------------------------------ #
# Moved to app/agent/prompts.py (refactor 2026-05-25 Phase 1.1).
# Already imported at the top of this file alongside _SYSTEM_PROMPT_BASE.


# ------------------------------------------------------------------ #
# Memory block formatter (Hermes Chantier 2 — frozen snapshot)        #
# ------------------------------------------------------------------ #


# Moved to app/agent/helpers/memory_formatting.py (refactor 2026-05-25 Phase 1.5).
from app.agent.helpers.memory_formatting import _format_memory_block  # noqa: E402,F401


# ------------------------------------------------------------------ #
# Agent node                                                           #
# ------------------------------------------------------------------ #

def _slm_real_name(llm, settings) -> str:
    """Le nom du modèle qui répond RÉELLEMENT sur la voie SLM.

    **Le défaut qu'il corrige (06/08).** `get_slm()` ne lit pas
    ``settings.slm_model`` : il rend ``get_llm_for_tier(ComplexityTier.SIMPLE)``,
    donc le tier A tel que l'utilisateur l'a configuré dans Réglages → Routage.
    Or l'étiquette ET la fenêtre de contexte étaient calculées sur
    ``SLM_MODEL`` — un réglage statique hérité du chemin Ollama, que plus rien
    ne fait correspondre au modèle servi.

    Deux consequences, la seconde pire que la premiere :

    - l'écran nommait un modèle qui n'avait pas travaillé ;
    - ``fit_messages_to_context`` cherchait la fenêtre de ce nom fantôme,
      retombait sur le défaut de 8 192 tokens, et TRONQUAIT l'historique d'un
      modèle qui en tenait bien plus. C'est la classe de défaut que
      ``config_reality`` traque depuis le 26/07 : une correspondance dont le
      repli est plausible, donc que personne ne vérifie.

    Repli sur ``settings.slm_model`` uniquement si l'introspection échoue —
    et il vaut alors « au mieux », pas « vrai ».
    """
    try:
        from app.services.llm_provider import describe_llm

        _provider, _model = describe_llm(llm)
        if _model and _model != "?":
            return str(_model)
    except Exception as exc:  # noqa: BLE001 — un nom de confort ne casse rien
        logger.debug("SLM : nom réel illisible (%s)", exc)
    # `slm_model` est VIDE par défaut depuis le 22/08 (cf. config.py) : rendre
    # une chaîne vide afficherait une étiquette blanche à l'écran, ce qui se
    # lit comme un défaut d'affichage plutôt que comme une identité inconnue.
    return settings.slm_model or "modèle inconnu"


def _slm_provider(llm) -> str:
    """Le fournisseur qui sert la voie locale. DÉCLARÉ d'abord, déduit ensuite.

    Voir `llm_provider.declared_provider_for_tier` pour le pourquoi de cet
    ordre — c'est la remarque de Franck du 21/08, et elle vaut ici autant que
    pour la chauffe.
    """
    try:
        from app.services.llm_provider import (
            declared_provider_for_tier, describe_llm,
        )

        declare = declared_provider_for_tier("simple")
        if declare:
            return declare
        provider, _model = describe_llm(llm)
        if provider and provider != "unknown":
            return str(provider)
    except Exception as exc:  # noqa: BLE001
        logger.debug("SLM : fournisseur illisible (%s)", exc)
    return "local"


def _slm_label(llm, settings) -> str:
    """L'étiquette d'usage du tour local : ``slm:<fournisseur>/<modèle>``.

    **Le défaut qu'elle corrige (21/08).** Le chemin SLM émettait ``slm:<modèle>``
    nu. Or LM Studio nomme ses modèles ``nvidia/nemotron-3-nano-4b`` : le nom
    contient déjà un ``/``, et `split_model_used` découpe sur le premier. Le
    tableau de bord attribuait donc les tours locaux à un fournisseur nommé
    « nvidia », qui n'existe pas dans la configuration.

    Le repli, lui, valait « ollama » en dur — un reste du temps où le SLM ne
    pouvait être que ça. Deux façons de nommer un fournisseur au hasard : dans
    les deux cas les chiffres avaient l'air corrects, ce qui est le pire.

    ⚠️ Les lignes d'usage écrites AVANT ce correctif portent toujours
    « nvidia » : rien ne les réécrit, et une migration de données d'analyse
    coûterait plus que le trou qu'elle comble.
    """
    return f"slm:{_slm_provider(llm)}/{_slm_real_name(llm, settings)}"


# Le tier A traite ce que le routeur a jugé SIMPLE — un score sous le seuil.
# Lui livrer le registre entier (~145 schémas d'outils, plusieurs dizaines de
# milliers de tokens) était ce qui rendait la voie rapide inutilisable : le
# 21/08, un Nemotron 4B déjà chargé en RAM dépassait 60 s sur « bonjour », donc
# repli cloud systématique. Le mécanisme se sabotait lui-même.
#
# `find_tool` reste le filet : si le modèle découvre qu'il lui faut un outil,
# il va le chercher dans le catalogue au lieu d'abandonner — c'est exactement
# ce pour quoi il existe. `report_missing_capability` évite qu'un manque se
# transforme en invention.
#
# ⚠️ MAIS DEUX OUTILS SEULEMENT ÉTAIT UNE ERREUR DE CONCEPTION (23/08).
#
# Regarde ce que le routeur envoie ICI. Les motifs qui font BAISSER le score —
# donc qui poussent vers le local — sont, dans `intent_router._SIMPLE_PATTERNS` :
# météo −15, agenda −15, mes mails −15, recherche −10, itinéraire −15,
# traduis −15, rappelle-moi −15, qr code −15, actualités −10, mes tâches −10.
#
# **Ce sont TOUS des besoins d'outils.** Et la voie locale n'en avait aucun.
# Le routeur envoyait systématiquement au modèle local exactement ce qu'il ne
# pouvait pas faire. La description de poste du tier A disait « les tâches
# simples du quotidien » ; son coffre à outils disait « rien ».
#
# Ce que ça coûtait, mesuré sur le fil du 23/08 : « trouve-moi des sites comme
# Babelio » demandait `find_tool` → un SECOND modèle local pour choisir →
# retour des noms → re-liaison → nouvel appel. Trois inférences sérialisées
# (`LOCAL_LLM_MAX_CONCURRENCY=1`) et deux tours, sur un 4B, pour une recherche
# web. Franck a vu la boucle de l'extérieur : « on a plein d'outils mais on
# dirait qu'elle ne sait pas quoi en faire ». Elle savait — le chemin pour y
# arriver était juste trop long pour elle.
#
# ⚠️ LE COÛT RÉEL, MESURÉ, PAS ESTIMÉ. Le catalogue entier pèse ~60 900 tokens
# de schémas (200 outils, ~304 chacun). Cette liste en pèse ~4 300, soit **7 %**
# — un vingtième du désastre du 21/08. Le pin `test_the_local_tier_can_serve_
# what_the_router_sends_it` tient ce budget : c'est LUI l'invariant, pas un
# nombre d'outils. Compter les outils était un raccourci ; ce qui a fait
# dépasser les 60 s, c'est le prompt processing des schémas.
#
# 👉 RÈGLE : cette liste suit `_SIMPLE_PATTERNS`. Un motif ajouté là-bas sans
# l'outil correspondant ici recrée le piège — le routeur promet une capacité
# que la voie locale n'a pas.
# ⚠️ LE SOCLE PERMANENT — trois outils, et pas un de plus.
#
# `find_tool` est la porte vers le reste. `report_missing_capability` évite
# qu'un manque devienne une invention. Et `web_search` parce qu'il répond à
# TOUTE demande ouverte — « trouve », « cherche », « quels sont », « c'est
# quoi » — sans qu'aucun mot-clé n'ait à le prévoir. Sans lui dans le socle,
# la question de Franck sur Babelio ne déclenche aucun motif et retombe sur le
# détour par `find_tool` qu'on cherche justement à supprimer.
_SLM_CORE_TOOLS: tuple[str, ...] = (
    "find_tool", "report_missing_capability", "web_search",
)

# ⚠️ LES OUTILS CONDITIONNELS, ET POURQUOI ILS LE SONT DEVENUS (24/08).
#
# Franck a regardé ce que gemma reçoit réellement dans LM Studio :
#
#   « J'hallucine… à quoi sert le dernier outil `qrcode_generate` ? Quel
#     intérêt d'envoyer un tel outil ? idem pour `maps_directions` ? »
#
# Il a raison, et c'est un défaut de MON correctif précédent. J'avais lié une
# liste FIXE de onze outils du quotidien — donc gemma recevait le générateur de
# QR codes et le calculateur d'itinéraires pour une question sur des sites de
# critiques littéraires. Sur un modèle de 4 milliards de paramètres, un outil
# hors-sujet n'est pas neutre : c'est une option de plus dans un choix qu'il
# fait mal, et du prompt processing payé pour rien.
#
# Chaque outil est donc lié SEULEMENT si la demande le réclame. Les motifs sont
# ceux de `intent_router._SIMPLE_PATTERNS` — c'est le même vocabulaire, et c'est
# volontaire : ce que le routeur reconnaît pour envoyer un tour en local doit
# être exactement ce que la voie locale sait traiter.
#
# Mesuré sur la question de Franck : 3 outils liés au lieu de 13, ~1 440 tokens
# au lieu de 4 322. Et `qrcode_generate` n'y est plus.
_SLM_CONDITIONAL_TOOLS: tuple[tuple[str, str], ...] = (
    (r"\bm[eé]t[eé]o\b|\btemp[eé]rature\b|\btemps qu.il fait\b", "weather_get"),
    (r"\bagenda\b|\bcalendrier\b|\brdv\b|\brendez[- ]?vous\b|\bplanning\b",
     "calendar_list_events"),
    (r"\bmails?\b|\be?mails?\b|\bbo[iî]te mail\b|\bcourriels?\b", "gmail_list_emails"),
    (r"\brappelle[- ]?moi\b|\bplanifie\b|\bchaque (jour|matin|semaine|lundi)\b",
     "scheduler_create_task"),
    (r"\bnotes?\b|\bm[eé]morise\b|\bnote[rz]?\b", "notes_create"),
    (r"\bt[aâ]ches?\b|\bto[- ]?do\b", "tasks_list"),
    (r"\btradui[stre]+\b|\btraduction\b", "translate_text"),
    (r"\bitin[eé]raire\b|\btrajet\b|\bcomment aller [aà]\b|\broute vers\b",
     "maps_directions"),
    (r"\bactualit[eé]s?\b|\bnews\b|\bles titres\b", "news_get_headlines"),
    (r"\bqr[- ]?code\b", "qrcode_generate"),
)

# L'union — ce que la voie locale peut atteindre sans passer par `find_tool`.
# Le pin `test_the_local_tier_can_serve_what_the_router_sends_it` la confronte
# aux intentions que le routeur envoie ici.
_SLM_TOOL_NAMES: tuple[str, ...] = _SLM_CORE_TOOLS + tuple(
    outil for _motif, outil in _SLM_CONDITIONAL_TOOLS
)


def _outils_reclames(demande: str) -> tuple[str, ...]:
    """Les outils conditionnels que CETTE demande justifie.

    Aucune inférence : ce sont des expressions régulières, sur le même
    vocabulaire que le routeur. Le coût est nul là où un sélecteur par modèle
    aurait ajouté un appel local sérialisé de plus — précisément la latence que
    la voie rapide existe pour éviter.
    """
    if not demande:
        # Sans demande (pré-construction au démarrage, appel d'API nu), on lie
        # tout : mieux vaut un peu large qu'un SLM incapable d'agir.
        return tuple(outil for _m, outil in _SLM_CONDITIONAL_TOOLS)
    return tuple(
        outil for motif, outil in _SLM_CONDITIONAL_TOOLS
        if re.search(motif, demande, re.IGNORECASE)
    )


def _slm_toolset(registry, demande: str = "") -> list:
    """Les outils liés au SLM pour CETTE demande.

    Repli sur le registre entier si aucun des noms attendus n'existe — mieux
    vaut lent que muet.
    """
    voulus = set(_SLM_CORE_TOOLS) | set(_outils_reclames(demande))
    try:
        retenus = [t for t in registry.all_tools
                   if getattr(t, "name", "") in voulus]
        if retenus:
            return retenus
        logger.warning(
            "SLM : aucun de %s dans le registre — liaison du catalogue complet, "
            "la voie locale sera lente", sorted(voulus),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SLM : sélection d'outils impossible (%s)", exc)
    return list(registry.all_tools)


def _slm_discovered_extras(registry, conversation_id: str) -> list:
    """Les outils que `find_tool` a surfacés dans CETTE conversation.

    ⚠️ LE TROU QUE ÇA BOUCHE (23/08). La voie cloud unionne déjà les
    découvertes dans sa liaison (cf. `get_discovered` plus bas dans ce
    fichier) ; la voie SLM, elle, gardait sa liaison à deux outils, figée
    dans la fermeture. `find_tool` répond pourtant « utilise-les directement
    maintenant » — une promesse que le chemin local ne tenait pas.

    Ça ne se voyait pas, et voici pourquoi : au tour suivant, `user_query`
    vaut ``messages[-1]``, donc le RETOUR de l'outil, pas la demande de
    l'utilisateur. La réponse de `find_tool` fait plus de 80 caractères,
    ce qui vaut +10 au score de complexité et repasse la barre — le tour
    repartait au cloud, où la liaison est complète. Le filet ne marchait
    que par cet accident de scoring. Raccourcir le message de `find_tool`
    l'aurait cassé sans que rien ne rougisse.

    ⚠️ ET LE CAS INVERSE EST LE PLUS IMPORTANT : quand `find_tool` ne
    trouve RIEN, sa réponse est courte, le score reste bas, et le tour
    reste local — exactement là où le modèle doit appeler
    `report_missing_capability`. Le chemin local n'est donc pas une
    curiosité théorique : c'est celui du gap réel.

    Pas de plafond sur le nombre d'ajouts, délibérément. Un plafond sur un
    `set` non ordonné écarterait des outils au hasard, en silence — la
    troncature muette que ce dépôt traque. Le garde-fou existe déjà et il
    s'annonce : si la liaison enfle au point de ralentir le modèle, le délai
    de `slm_timeout` expire et le repli local → cloud remonte à l'interface
    (21/08). Mieux vaut un repli visible qu'un écrêtage discret.
    """
    if not conversation_id:
        return []
    try:
        from app.agent.discovered_tools import get_discovered

        noms = get_discovered(conversation_id)
        if not noms:
            return []
        deja = set(_SLM_TOOL_NAMES)
        return [t for t in registry.all_tools
                if getattr(t, "name", "") in noms
                and getattr(t, "name", "") not in deja]
    except Exception as exc:  # noqa: BLE001 — un confort ne casse pas un tour
        logger.warning("SLM : découvertes non liées (%s)", exc)
        return []


def _contenu_texte(message) -> str:
    """Le texte d'un message, qu'il soit objet LangChain ou dict sérialisé."""
    brut = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(brut, list):  # contenu multi-blocs
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in brut
        )
    return brut or ""


def _index_derniere_humaine(messages) -> int:
    """L'indice du dernier message utilisateur, ou ``-1``.

    Sert uniquement à la trace : `depuis=0` au premier tour, puis 1, 2… Sans
    ce chiffre, deux notes `[routing]` identiques ne disent pas si le tour a
    avancé ou si l'utilisateur a reposé la même question.
    """
    liste = list(messages or ())
    for i in range(len(liste) - 1, -1, -1):
        m = liste[i]
        role = (
            m.get("role") or m.get("type")
            if isinstance(m, dict)
            else getattr(m, "type", "")
        )
        if role in ("human", "user"):
            return i
    return -1


def _derniere_demande_humaine(messages, defaut: str = "") -> str:
    """Ce que L'UTILISATEUR a demandé, pas ce que le dernier outil a répondu.

    ⚠️ LE DÉFAUT QUE ÇA CORRIGE (23/08), et c'est celui qui vidait la voie
    locale de son sens.

    Le routeur notait `messages[-1]`. Au premier tour c'est bien la demande ;
    dès le second, c'est le RETOUR D'OUTIL. Un résultat de `find_tool` ou de
    `web_search` est long (> 150 caractères : +20) et contient des URL
    (`_URL_RE` : +15). Le score passait donc de 55 à 90-100, et le tour
    repartait au cloud **exactement au moment où le modèle local allait se
    servir de l'outil qu'il venait de trouver**.

    Mesuré sur le fil du 23/08, conversation 26556c11 :

        [routing] slm=slm   score=55    ← la demande part en local
        [routing] slm=cloud score=100   ← le retour d'outil la fait fuir
        [routing] turn=complex …        ← six tours, 223 693 tokens

    La voie locale faisait donc le travail le moins utile — comprendre la
    demande — et cédait la main juste avant celui qui compte. Le comportement
    attendu, mot pour mot de Franck : « Gemma interroge Ely via find_tool, Ely
    renvoie le ou les outils utiles, Gemma fait la demande avec le bon outil et
    renvoie la réponse. »

    Un tour, une demande, un score : la complexité d'une requête ne change pas
    parce qu'un outil y a répondu longuement. Ce que le retour d'outil apporte,
    c'est de la MATIÈRE, pas de la difficulté.
    """
    for message in reversed(list(messages or ())):
        role = (
            message.get("role") or message.get("type")
            if isinstance(message, dict)
            else getattr(message, "type", "")
        )
        if role in ("human", "user"):
            texte = _contenu_texte(message)
            if texte:
                return texte
    return defaut


def _premier_parametre_de(registry):
    """``nom d'outil -> nom de son premier paramètre``, lu sur le schéma réel.

    Sert à lier un appel écrit à la main par le modèle — `find_tool("…")` n'a
    pas de nom de paramètre, et le deviner produirait un appel plausible et
    faux. Paresseux : le schéma n'est lu que pour l'outil effectivement
    reconnu, jamais pour les ~200 du catalogue.
    """
    def _resoudre(nom: str) -> str | None:
        try:
            for t in registry.all_tools:
                if getattr(t, "name", "") != nom:
                    continue
                schema = getattr(t, "args_schema", None)
                if schema is None:
                    return None
                js = schema.model_json_schema()
                requis = js.get("required") or []
                if requis:
                    return str(requis[0])
                props = list((js.get("properties") or {}).keys())
                return str(props[0]) if props else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("premier paramètre de %s introuvable (%s)", nom, exc)
        return None

    return _resoudre


def _annoncer_repli_slm(state, model: str, raison: str) -> None:
    """Fait remonter le repli local → cloud jusqu'à l'utilisateur, ET à la trace.

    Il n'était que journalisé. Voir `fallback_manager.note_slm_fallback`.
    Ne lève jamais : un toast raté ne coûte pas un tour.

    ⚠️ LA TRACE EST LA SECONDE MOITIÉ, ajoutée le 23/08. Le toast est éphémère :
    il vit le temps d'un tour dans l'interface, et personne ne peut le
    retrouver le lendemain. Or `usage_logs` n'enregistre que le modèle qui a
    RENDU la réponse — une tentative locale abandonnée n'y laisse rien.

    Conséquence vécue : « GPT-5.6 a répondu, est-ce gemma qui a passé la
    main ? » était une question sans réponse. Les deux scénarios — le local a
    essayé puis abandonné, le local n'a jamais été consulté — produisaient
    exactement les mêmes lignes en base. La note `[routing]` les sépare.
    """
    conv = state.get("conversation_id", "") or ""
    try:
        from app.services.fallback_manager import note_slm_fallback

        note_slm_fallback(conv, model=model, reason=raison)
    except Exception as exc:  # noqa: BLE001
        logger.debug("SLM : repli non signalé à l'interface (%s)", exc)
    try:
        routing_note(
            conv, "slm", user_id=state.get("user_id", ""),
            decision="cloud_apres_local", modele=model, raison=raison,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("SLM : repli non tracé (%s)", exc)


def create_agent_node():
    from app.skills import get_skill_registry
    from app.config import get_settings
    from app.services.llm_provider import get_active_provider, get_active_model

    settings = get_settings()
    registry = get_skill_registry()
    memory = get_memory_manager()
    intent_router = get_intent_router()

    # Pre-build SLM if enabled — cached in closure but re-bound when tools change
    _slm_with_tools = None
    _slm_base = None          # le modèle NON bindé — voir `_slm_real_name`
    _slm_version = -1
    # ⚠️ DEUXIÈME compteur, et son absence était un défaut (22/08). Le cache
    # SLM ne suivait que `registry.tools_version` : changer le modèle du tier A
    # dans Réglages → Routage ne le reconstruisait PAS, et Ely continuait de
    # servir l'ancien modèle jusqu'au prochain redémarrage.
    #
    # C'est exactement le défaut décrit vingt lignes plus bas pour le cache des
    # tiers LLM — « switching a model in the UI had no runtime effect » (audit
    # C-4, corrigé le 06/05). Le site jumeau, lui, n'avait jamais été corrigé.
    # Franck a déplacé Nemotron et Gemma entre tiers plusieurs fois le 21/08 ;
    # ses `make down && make up` ont masqué le défaut en relançant le process.
    _slm_cfg_version = -1
    # ⚠️ TROISIÈME COMPTEUR, ET C'EST UN DÉFAUT DIFFÉRENT (23/08).
    #
    # Les deux au-dessus disent QUAND reconstruire un SLM qui existe. Celui-ci
    # dit quand RETENTER une construction qui a échoué — ce que rien ne faisait.
    #
    # La reconstruction plus bas est gardée par `if _slm_with_tools is not None`.
    # Donc si `get_slm()` lève au démarrage — serveur local pas encore levé,
    # instance mal configurée, modèle absent au boot — la voie locale reste
    # morte pour TOUTE LA VIE DU PROCESS. Un `WARNING` unique part au boot,
    # défile, et plus rien ensuite : Ely répond au cloud pour tout, sans que
    # personne puisse deviner pourquoi.
    #
    # Le cas est banal en pratique : `docker compose up` démarre le backend
    # avant que LM Studio soit prêt sur la machine hôte. Il fallait un
    # redémarrage manuel, décidé sans aucun signal pour le motiver.
    #
    # Deux déclencheurs de reprise, et ils sont complémentaires : la
    # temporisation (le serveur local a pu se lever entre-temps) et le
    # changement de configuration (l'administrateur vient de désigner un autre
    # modèle — c'est un signal fort qu'il attend un effet).
    _SLM_REPRISE_S = 120.0
    _slm_echec_a: list[float] = [-1.0]   # -1 = pas d'échec ; 0 = retenter tout de suite
    if settings.slm_enabled:
        try:
            from app.services.llm_provider import get_slm
            # ⚠️ On garde une référence au modèle AVANT `bind_tools`. Celui-ci
            # rend un RunnableBinding qui n'expose pas `.model` : introspecter
            # l'objet bindé rendrait « ? ». La voie cloud fait pareil — elle
            # décrit `_base_llm`, pas `_llm_with_tools`.
            from app.services.llm_provider import get_tier_config_version
            _slm_base = get_slm()
            _slm_with_tools = _slm_base.bind_tools(_slm_toolset(registry))
            _slm_version = registry.tools_version
            _slm_cfg_version = get_tier_config_version()
            logger.info(
                "SLM pre-built: model=%s (réglage SLM_MODEL=%s), threshold=%d",
                _slm_real_name(_slm_base, settings), settings.slm_model,
                settings.slm_complexity_threshold,
            )
        except Exception as exc:
            logger.warning("SLM init failed: %s — all requests will use LLM", exc)
            _slm_echec_a[0] = 0.0   # 0 = « jamais retenté » → retente au 1er tour

    # Tier-based LLM cache: { tier_value → llm_with_tools }
    # Invalidated on EITHER:
    #   - tool registry version bump (new skill installed/upgraded)
    #   - tier config version bump (user changed routing in Settings → Routage)
    # Without the second check, switching a model in the UI had no runtime
    # effect — the cached client (e.g. Devstral) kept being served on every
    # agent_node call. (Audit C-4, fixed 2026-05-06.)
    _tier_llm_cache: dict = {}
    _tier_cache_version = [-1]   # tracks registry.tools_version
    _tier_cfg_version = [-1]     # tracks llm_provider.get_tier_config_version()

    async def agent_node(state: AgentState) -> dict:
        import time as _t
        _gt_start = _t.monotonic()
        logger.warning("⏱ TIMING[general] starting")
        nonlocal _slm_with_tools, _slm_base, _slm_version, _slm_cfg_version
        # _tier_llm_cache / _tier_cache_version are dicts/lists mutated in-place — no nonlocal needed
        messages = state["messages"]
        # P2 — posé plus bas quand la requête est complète. Initialisé ici pour
        # que le `return` reste sûr même si la branche de calcul n'est pas
        # atteinte (chemin SLM, sortie anticipée, exception).
        _ctx_breakdown: str | None = None
        # MÊME RAISON, MÊME PIÈGE, DÉCOUVERT LE 21/08. Celui-ci n'était
        # initialisé QUE dans `if response is None:` — la branche cloud — et
        # relu inconditionnellement au pied du nœud (`_fb.record_response`).
        # Tant que le SLM échouait systématiquement, la branche cloud tournait
        # toujours et la variable était toujours liée : le défaut existait
        # depuis #265 sans être atteignable. Le jour où la voie locale a enfin
        # répondu, chaque tour SLM levait `UnboundLocalError` APRÈS avoir
        # affiché sa réponse — l'utilisateur voyait le texte, puis « erreur
        # interne » l'écrasait. Une voie qu'on répare est une voie qu'on
        # emprunte pour la première fois : ce qu'elle traverse n'a jamais été
        # exécuté. Cf. le pin `test_slm_path_binds_every_local_it_reads`.
        _fb_state = None
        user_id = state.get("user_id", "")
        # Hermes Chantier 2 / 4 — conversation id needs to be available BEFORE
        # the system prompt is built (cache key) and before the fallback state
        # is created (down in the LLM path). Hoisting it here means both
        # chantiers see the same value. Empty string disables both caches
        # for this turn — acceptable for non-conversation API callers.
        _conv_id_fb = state.get("conversation_id", "") or ""
        # Defensive: LangGraph may pass messages as dicts (serialized form)
        # when a node receives state that was built outside the graph runner.
        _last = messages[-1] if messages else None
        if isinstance(_last, dict):
            user_query = _last.get("content") or ""
            if isinstance(user_query, list):  # multi-block content
                user_query = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in user_query
                )
        else:
            _c = _last.content if _last else ""
            user_query = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in _c
            ) if isinstance(_c, list) else (_c or "")

        # LA DEMANDE, distincte du dernier message. Voir
        # `_derniere_demande_humaine` : le routeur et la liaison d'outils la
        # suivent tous les deux, alors que `user_query` reste `messages[-1]`
        # pour la construction du contexte et le rappel mémoire.
        #
        # ⚠️ CALCULÉE ICI, INCONDITIONNELLEMENT, et c'est délibéré. La liguer
        # dans la branche de routage puis la relire dans la branche d'inférence
        # serait le défaut `_fb_state` de la #330, à l'identique : une variable
        # liée dans une branche et lue dans une autre ne lève que le jour où la
        # première ne s'exécute pas.
        _a_router = _derniere_demande_humaine(messages, user_query)

        # Hot-reload: clear tier cache when tool registry OR tier routing config changes
        from app.services.llm_provider import get_tier_config_version
        current_version = registry.tools_version
        current_cfg_version = get_tier_config_version()
        if (current_version != _tier_cache_version[0]
                or current_cfg_version != _tier_cfg_version[0]):
            _tier_llm_cache.clear()
            _tier_cache_version[0] = current_version
            _tier_cfg_version[0] = current_cfg_version
            logger.info(
                "Tier LLM cache invalidated (tools_v=%d, tier_cfg_v=%d)",
                current_version, current_cfg_version,
            )

        # ── Reprise après un échec de construction (23/08) ─────────────────
        # Le bloc juste en dessous ne reconstruit QUE ce qui existe déjà. Sans
        # celui-ci, un `get_slm()` qui lève au démarrage tue la voie locale
        # pour toute la vie du process — cas banal quand le backend démarre
        # avant que LM Studio soit prêt sur la machine hôte.
        if (
            settings.slm_enabled
            and _slm_with_tools is None
            and _slm_echec_a[0] >= 0.0
            and (
                _slm_echec_a[0] == 0.0
                or current_cfg_version != _slm_cfg_version
                or (_t.monotonic() - _slm_echec_a[0]) >= _SLM_REPRISE_S
            )
        ):
            try:
                from app.services.llm_provider import get_slm

                _reprise_base = get_slm()
                _slm_with_tools = _reprise_base.bind_tools(_slm_toolset(registry))
                _slm_base = _reprise_base
                _slm_version = current_version
                _slm_cfg_version = current_cfg_version
                _slm_echec_a[0] = -1.0
                logger.warning(
                    "SLM reconstruit après un échec de démarrage : %s — la voie "
                    "locale redevient disponible",
                    _slm_real_name(_slm_base, settings),
                )
            except Exception as exc:  # noqa: BLE001
                # On retentera. Le journal reste en `info` : à raison d'une
                # tentative toutes les deux minutes, un WARNING par essai
                # noierait le reste quand le serveur local est éteint pour de
                # bon — et l'absence de voie locale est déjà tracée à chaque
                # tour par la note `[routing] slm=cloud raison=slm_indisponible`.
                _slm_echec_a[0] = _t.monotonic()
                logger.info(
                    "SLM toujours indisponible (%s) — nouvelle tentative dans "
                    "%.0f s", exc, _SLM_REPRISE_S,
                )

        # Mêmes DEUX conditions que le cache des tiers, juste au-dessus : le
        # registre d'outils OU la configuration de routage. La seconde manquait
        # ici, et c'est elle qui porte le changement de modèle du tier A.
        if _slm_with_tools is not None and (
            current_version != _slm_version
            or current_cfg_version != _slm_cfg_version
        ):
            try:
                from app.services.llm_provider import get_slm
                nonlocal_base = get_slm()
                _slm_base = nonlocal_base
                _slm_with_tools = nonlocal_base.bind_tools(_slm_toolset(registry))
                _slm_version = current_version
                _slm_cfg_version = current_cfg_version
                logger.info(
                    "SLM reconstruit (tools_v=%d, tier_cfg_v=%d) : %s",
                    current_version, current_cfg_version,
                    _slm_real_name(_slm_base, settings),
                )
            except Exception as exc:  # noqa: BLE001
                # ⚠️ Le `except: pass` d'origine avalait l'échec en silence :
                # le SLM restait sur l'ancien modèle sans que rien ne le dise,
                # ce qui est précisément le défaut qu'on corrige ici.
                logger.warning(
                    "SLM non reconstruit après changement de configuration (%s) "
                    "— l'ancien modèle continue de servir", exc,
                )

        # ── Route first — avoids loading memory for SLM requests ──────────
        routing_score = 100
        model_used = "llm:tier-routed"  # updated once tier is selected below
        response = None

        from app.services.intent_router import ModelTier
        use_slm = False
        decision = None
        # Scheduled / automated runs must use the reliable cloud tier — the
        # local SLM is too weak for unattended multi-tool prompts and would
        # also bypass the named-tool binding below.
        if _slm_with_tools is not None and not state.get("automated_task"):
            # ⚠️ LA DEMANDE, PAS LE DERNIER MESSAGE. Voir
            # `_derniere_demande_humaine` : noter `messages[-1]` faisait fuir
            # le tour au cloud dès qu'un outil avait répondu — c'est-à-dire
            # juste avant que le modèle local s'en serve.
            decision = intent_router.route(_a_router, history=messages[:-1])
            routing_score = decision.score
            use_slm = (decision.tier == ModelTier.SLM)
            # C3d-4 — décision SLM-vs-cloud tracée (aspect "slm").
            routing_note(
                state.get("conversation_id", ""), "slm",
                user_id=state.get("user_id", ""),
                decision="slm" if use_slm else "cloud",
                score=decision.score,
                # Combien de messages depuis la demande notée : 0 au premier
                # tour, puis 1, 2… Rend lisible dans la trace qu'un tour long
                # continue de suivre LA MÊME demande.
                depuis=len(messages) - 1 - _index_derniere_humaine(messages),
            )
        else:
            # ⚠️ LE TROU DU 23/08 : la voie locale ABSENTE ne laissait aucune
            # trace, tour après tour.
            #
            # Cette note était à l'INTÉRIEUR du garde ci-dessus. Quand le SLM
            # n'existe pas — désactivé, construction échouée, tâche planifiée —
            # aucune ligne `[routing]` n'était émise. La conséquence était
            # exactement la question à laquelle on ne pouvait pas répondre :
            # « GPT-5.6 a répondu, est-ce que le local a essayé ? » Les logs
            # étaient muets, `usage_logs` ne portait que la ligne cloud, et
            # rien nulle part ne disait si le local avait été consulté.
            #
            # Un tour qui ne consulte pas la voie locale est une DÉCISION. Une
            # décision non tracée est indiscernable d'une panne.
            routing_note(
                state.get("conversation_id", ""), "slm",
                user_id=state.get("user_id", ""),
                decision="cloud",
                score=100,
                raison=(
                    "tache_planifiee" if state.get("automated_task")
                    else ("slm_desactive" if not settings.slm_enabled
                          else "slm_indisponible")
                ),
            )

        # Refactor 2026-05-25 Phase 4.2 — date / language / IMPORTANT note
        # builders extracted to app/agent/builders/system_prompt.py.
        from app.agent.builders.system_prompt import (
            LLM_INTROSPECTION_NOTE,
            build_personal_vocabulary_block,
            compute_date_segment,
            extract_email_block_addendum,
            fetch_user_language,
        )
        date_str, _date_segment = compute_date_segment()

        # C2-b — rappel contextuel du profil. Les clés classées « bruyantes »
        # (upcoming_events, gmail_preferences…) sont absentes du profil
        # permanent, et le commentaire de _PROFILE_NOISY_KEYS promettait
        # qu'elles resteraient récupérables « via the semantic RAG path » —
        # promesse qu'AUCUN code ne tient (user_profiles n'est lu que par
        # l'injection plafonnée et un rapport admin). Elles redeviennent ici
        # atteignables quand la question les appelle.
        #
        # Placé dans la ZONE VOLATILE, avec la date, et JAMAIS dans le
        # snapshot mémoire — celui-ci est gelé par conversation, le bloc n'y
        # servirait que la première question du fil.
        from app.services.memory_service import get_query_relevant_profile
        _recall_block = await get_query_relevant_profile(user_id, user_query)
        _volatile_segment = (
            f"\n\n{_recall_block}\n" if _recall_block else ""
        ) + _date_segment
        _user_language, _lang_directive, _lang_reminder = await fetch_user_language(user_id)
        logger.info(
            "[general] lang=%s user=%s",
            _user_language,
            (user_id[:8] + "…") if user_id else "(none)",
        )

        if use_slm:
            # ── Lightweight path: minimal prompt, no memory queries ────────
            # Fetching Qdrant memory adds ~150-300ms and is useless for simple tasks.
            # SLM path is short enough that caching is not worthwhile.
            system = _SYSTEM_PROMPT_SLM.format(date_str=date_str)
            _use_compact = False  # ensure variable is defined for downstream branches
        else:
            # ── Full path: complete prompt + memory context ────────────────
            # Decide compact-vs-full once based on the active LLM family.
            # Compact path is used for small local LLMs (LM Studio, llama.cpp
            # on localhost) and stays uncached because it's already short
            # (~430 tokens) — the cache benefit is marginal there.
            #
            # 02/09/2026 — l'aiguillage se décidait sur `get_llm()`, le LLM
            # PAR DÉFAUT, alors que l'inférence part sur `get_llm_for_tier`
            # quelques centaines de lignes plus bas. « Défaut local + tier
            # COMPLEX cloud » EST la configuration d'Ely : le prompt compact
            # (430 tokens, sans une seule des règles de conduite du socle)
            # partait donc chez zhipu / anthropic, profil en clair, pendant
            # que la voie complète — la seule que le correctif de
            # souveraineté fermait — n'était jamais empruntée.
            #
            # On interroge le modèle qui va RÉPONDRE. `classify_complexity`
            # est une fonction pure sans appel réseau, et le LLM du tier est
            # rangé sous la MÊME clé de cache que plus bas : cette résolution
            # anticipée ne construit rien deux fois.
            #
            # Limite connue : si un repli est déjà actif pour la conversation,
            # le modèle retenu plus bas sera celui du repli, pas celui du
            # tier. L'aiguillage peut donc rater la forme du prompt — mais pas
            # la souveraineté : `prompt_systeme_sortant` tranche, lui, sur le
            # modèle réellement retenu.
            from app.agent.compact_prompt import build_compact_system_prompt
            from app.services.qwen_no_think import is_local_openai_llm
            from app.services.llm_provider import (
                classify_complexity as _classify_pour_la_voie,
                get_llm_for_tier as _llm_du_tier_pour_la_voie,
            )

            try:
                _tier_pour_la_voie = _classify_pour_la_voie(user_query)
                _cle_voie = f"{_tier_pour_la_voie.value}:base"
                if _cle_voie not in _tier_llm_cache:
                    _tier_llm_cache[_cle_voie] = _llm_du_tier_pour_la_voie(
                        _tier_pour_la_voie,
                    )
                _llm_for_detect = _tier_llm_cache[_cle_voie]
            except Exception as _voie_exc:  # noqa: BLE001
                logger.warning(
                    "[voie] modèle du tier non résolu (%s) — prompt COMPLET "
                    "par défaut", _voie_exc,
                )
                _llm_for_detect = None
            _use_compact = (
                _llm_for_detect is not None
                and is_local_openai_llm(_llm_for_detect)
            )

            # Memory snapshot — cacheable per-conversation via frozen_memory.
            # On the first turn, we run the 5-way Qdrant + SQL gather; on
            # subsequent turns, the snapshot is returned from cache in O(1)
            # without re-querying Qdrant. New facts archived mid-session
            # appear in the snapshot of the NEXT conversation, not this one.
            #
            # Refactor 2026-05-25 Phase 4.1 — the business logic lives in
            # app/agent/builders/memory_snapshot.py as a pure async fn that
            # returns (snapshot_text, compact_pieces). The thin wrapper
            # below only exists to satisfy frozen_memory's `() -> str`
            # builder signature and to propagate compact_pieces via the
            # only remaining `nonlocal` in this path.
            from app.agent.builders.memory_snapshot import (
                build_memory_snapshot,
                refetch_compact_pieces,
            )

            _compact_pieces: dict | None = None

            async def _build_memory_snapshot() -> str:
                nonlocal _compact_pieces
                snapshot, pieces = await build_memory_snapshot(
                    messages=messages,
                    user_id=user_id,
                    user_query=user_query,
                    memory=memory,
                    use_compact=_use_compact,
                )
                if pieces is not None:
                    _compact_pieces = pieces
                return snapshot

            memory_snapshot = await _frozen_mem.get_or_build(
                _conv_id_fb, user_id, _build_memory_snapshot,
            )

            if _use_compact:
                # Local LLMs get a compact prompt — uncached, builds from the
                # snapshot pieces we just gathered.
                if _compact_pieces is None:
                    # Cache hit on frozen_memory means _build_memory_snapshot
                    # didn't run this turn, so _compact_pieces is empty.
                    # Re-fetch the minimal trio synchronously (rare path —
                    # only on cache hit + compact mode together).
                    _compact_pieces = await refetch_compact_pieces(
                        user_id=user_id,
                        user_query=user_query,
                        memory=memory,
                    )
                system = build_compact_system_prompt(
                    agent_name="general",
                    date_str=date_str,
                    user_ctx=_compact_pieces["user_profile"],
                    memories=_compact_pieces["memories"],
                    constraints=_compact_pieces["constraints"],
                )
                logger.info(
                    "[general] compact prompt mode active (%d chars)", len(system),
                )
            else:
                # Full path — Hermes Chantier 2 caching active.
                # Cacheable segment = lang_directive + base + IMPORTANT + snapshot.
                # Concatenated in this order so the provider's prompt cache
                # prefix can match every byte up to the dynamic date.
                # LLM_INTROSPECTION_NOTE imported from builders.system_prompt
                # at the top of agent_node.
                def _build_cacheable_prompt() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + LLM_INTROSPECTION_NOTE
                        + memory_snapshot
                    )

                cacheable_system = _spc.get_or_build(
                    _conv_id_fb, _build_cacheable_prompt,
                )
                # Final assembly: cacheable + dynamic date + lang reminder.
                # Email block + lang reminder are appended further down.
                system = cacheable_system + _volatile_segment

        # ── Sandwich tail: language reminder ──────────────────────────────
        # Front-load (primacy) was already applied INSIDE the cacheable
        # segment (full path) or via _SYSTEM_PROMPT_SLM/compact (other paths).
        # Tail-load (recency) goes here so the model honours the language
        # request even when the body drifts in the other language.
        if use_slm or _use_compact:
            # SLM/compact paths haven't applied the lang directive yet at the
            # head — apply both ends now for symmetry.
            system = _lang_directive + system + _lang_reminder
        else:
            # Full path already has the lang directive at the head (inside
            # the cacheable segment). Just append the reminder.
            system = system + _lang_reminder

        # ── Context fitting (prevent overflow) ────────────────────────────
        # NOTE: get_active_model is imported at create_agent_node() scope (line ~167).
        # Re-importing it here would shadow the closure and trigger UnboundLocalError
        # at the earlier usage line 271 (_model = get_active_model()).
        from app.services.context_manager import fit_messages_to_context

        _sanitized = _sanitize_messages_for_mistral(messages)

        # Email / placeholder addendum — refactor Phase 4.2 (builders.system_prompt).
        system += extract_email_block_addendum(_sanitized)

        # V1 temps 1 — vocabulaire personnel (onboarding). N'était injecté
        # que par sub_agents/factory.py : en faisant passer les canaux sur ce
        # chemin, on le leur aurait retiré en silence. Placé AVANT la date
        # (stable par utilisateur, donc cache-friendly), comme côté
        # spécialistes.
        _vocab_block = await build_personal_vocabulary_block(state.get("user_id", ""))
        if _vocab_block:
            system += f"\n\n{_vocab_block}\n"

        # Garde-fou EXÉCUTION AUTOMATIQUE (tâches planifiées, missions) : il
        # n'y a PAS d'humain pour répondre maintenant. Sans ça, un prompt qui
        # contient « chaque jour » / « envoie-moi » est lu comme une demande
        # de PLANIFIER → l'agent répond « à quelle heure ? » au lieu
        # d'exécuter (bug terrain 13/06 : 2 dailies restés en attente). On
        # force l'exécution directe et on interdit la re-planification (sinon
        # boucle de tâches qui se recréent).
        if state.get("automated_task"):
            system += (
                "\n\n## ⚠️ EXÉCUTION AUTOMATIQUE PROGRAMMÉE\n"
                "Cette tâche s'exécute SEULE, à heure fixe, SANS utilisateur "
                "disponible pour répondre maintenant. La récurrence "
                "(« chaque jour », l'heure d'envoi) est DÉJÀ gérée par le "
                "planificateur — ce n'est pas à toi de la configurer.\n"
                "- EXÉCUTE la demande immédiatement et jusqu'au bout, en "
                "appelant les outils nécessaires.\n"
                "- NE pose AUCUNE question et NE demande AUCUNE confirmation : "
                "personne ne la lira à temps. En cas d'ambiguïté, prends "
                "l'option par défaut la plus raisonnable et continue.\n"
                "- NE crée PAS et NE reprogramme PAS de tâche planifiée "
                "(outils scheduler_*) : elle existe déjà, la recréer ferait "
                "une boucle.\n"
                "- SURVEILLANCE/veille uniquement : si — et SEULEMENT si — ta "
                "tâche consiste à surveiller quelque chose et qu'il n'y a RIEN "
                "de nouveau ni de notable à signaler depuis la dernière fois, "
                "réponds EXACTEMENT « [SILENT] » (ce seul mot, rien d'autre) : "
                "la notification sera supprimée pour ne pas te spammer. Pour "
                "une tâche qui produit toujours un livrable (briefing, résumé, "
                "rapport quotidien), NE l'utilise JAMAIS — livre le résultat.\n"
                "- Termine en produisant directement le livrable final demandé."
            )

        # ── Inference ──────────────────────────────────────────────────────
        if use_slm:
            try:
                _slm_fitted = fit_messages_to_context(
                    messages=_sanitized,
                    system_prompt=system,
                    # Le VRAI modèle, pas `SLM_MODEL`. C'est une table de
                    # fenêtres de contexte : la nourrir d'un nom qui ne
                    # correspond à rien fait retomber sur le défaut 8 192 et
                    # tronque l'historique d'un modèle qui tenait bien plus.
                    # Exactement le défaut du 26/07 que `config_reality` traque.
                    model=_slm_real_name(_slm_base, settings),
                    reserve_for_response=1024,
                    # Ancrage du mandat : sur une tâche planifiée la consigne
                    # est messages[0], et la troncature supprime par l'avant.
                    # Sans ça, l'agent termine sans savoir ce qu'on lui
                    # demandait (prospection du 26/07 : 51 appels, 0 écriture).
                    preserve_first=bool(state.get("automated_task")),
                )
                # ── Liaison PAR DEMANDE (24/08) ────────────────────────────
                # La liaison en cache portait les onze outils du quotidien, tous
                # les tours. Franck l'a vue passer dans LM Studio : un générateur
                # de QR codes et un calculateur d'itinéraires envoyés pour une
                # question sur des sites de critiques littéraires.
                #
                # Sur un 4B, un outil hors-sujet n'est pas neutre : c'est une
                # option de plus dans un choix qu'il fait mal. On lie donc le
                # socle plus ce que la DEMANDE réclame — et le coût est un
                # `bind_tools` local, sans réseau, sur trois à cinq schémas.
                _slm_extras = _slm_discovered_extras(registry, _conv_id_fb)
                _slm_runtime = _slm_with_tools
                try:
                    # Les préférences valent AUSSI ici. Une compétence coupée
                    # dans l'interface ne doit pas revenir par la voie locale
                    # — ce serait un demi-interrupteur, pire qu'aucun.
                    _slm_outils = appliquer_preferences(
                        _slm_toolset(registry, _a_router) + _slm_extras,
                        await disabled_tool_names(user_id),
                        contexte="slm",
                    )
                    _slm_runtime = _slm_base.bind_tools(_slm_outils)
                    logger.info(
                        "SLM : %d outil(s) liés pour cette demande : %s",
                        len(_slm_outils),
                        sorted(getattr(t, "name", "?") for t in _slm_outils),
                    )
                except Exception as exc:  # noqa: BLE001
                    # On retombe sur la liaison en cache : plus large que
                    # nécessaire, mais le modèle reste capable d'agir.
                    logger.warning(
                        "SLM : liaison par demande impossible (%s) — repli sur "
                        "la liaison complète", exc,
                    )
                if _slm_extras:
                    logger.warning(
                        "[find_tool] SLM : +%d outil(s) découvert(s) lié(s) : %s",
                        len(_slm_extras),
                        sorted(t.name for t in _slm_extras),
                    )
                response = await asyncio.wait_for(
                    _slm_runtime.ainvoke(
                        # Le tier A est CONFIGURABLE : « SLM » ne veut pas dire
                        # « local ». Sa frontière d'envoi est la même que celle
                        # du chemin général (02/09/2026). Le gabarit SLM ne
                        # porte pas la mémoire, mais il porte le bloc de
                        # vocabulaire personnel et l'addendum e-mail.
                        [{"role": "system", "content": prompt_systeme_sortant(
                            system, _slm_base, _conv_id_fb,
                        )}]
                        + _slm_fitted
                    ),
                    timeout=settings.slm_timeout,
                )
                model_used = _slm_label(_slm_base, settings)
                logger.info(
                    "SLM answered (score=%d, model=%s, reason=%s)",
                    decision.score, _slm_real_name(_slm_base, settings),
                    decision.reason,
                )

                # ── L'appel d'outil écrit en TEXTE (23/08) ─────────────────
                # ⚠️ TROISIÈME FILET CÂBLÉ SUR UNE SEULE VOIE. La récupération
                # d'appels textuels existe depuis le 06/05 et vit dans la
                # branche cloud ; la voie SLM ne l'a jamais eue. Le 23/08,
                # gemma-4-E4B a répondu, littéralement :
                #
                #     find_tool("sites de critiques de livres en ligne")
                #
                # Le texte partait tel quel à l'écran. L'utilisateur lisait un
                # appel de fonction en guise de réponse, et rien ne rougissait
                # — le tour était un SUCCÈS : pas d'exception, pas de délai
                # dépassé, une réponse rendue.
                #
                # ⚠️ C'est une conséquence directe du correctif précédent. Lui
                # dire « appelle find_tool » sans lui dire « par le
                # tool-calling natif » déplace le défaut au lieu de le régler :
                # le modèle obéit, en écrivant. La consigne manquante est dans
                # `_SYSTEM_PROMPT_SLM`, mais une consigne n'est pas un verrou.
                _tc_slm = getattr(response, "tool_calls", None) or []
                if not _tc_slm:
                    _noms_reels = {t.name for t in registry.all_tools}
                    from app.agent.tool_call_recovery import (
                        looks_like_an_unexecuted_tool_call,
                        recover_tool_calls_into_response,
                    )
                    _rec = recover_tool_calls_into_response(
                        response,
                        real_tool_names=_noms_reels,
                        premier_parametre=_premier_parametre_de(registry),
                    )
                    if _rec:
                        logger.warning(
                            "[recovery] SLM — %d appel(s) récupéré(s) du texte", _rec,
                        )
                    else:
                        # Rien à récupérer, mais le texte SENT l'appel manqué.
                        # Alors la voie locale a échoué : elle a rendu une
                        # réponse qui n'en est pas une.
                        #
                        # 👉 On repasse au cloud EN L'ANNONÇANT. C'est ce que
                        # Franck a perdu en changeant de modèle : le précédent
                        # dépassait son délai et la main partait vite au cloud.
                        # Celui-ci « réussit » et boucle en local. Un échec
                        # rapide et visible vaut mieux qu'un succès apparent.
                        _contenu = getattr(response, "content", "") or ""
                        _contenu = _contenu if isinstance(_contenu, str) else str(_contenu)
                        _rate = looks_like_an_unexecuted_tool_call(_contenu, _noms_reels)
                        if _rate:
                            logger.warning(
                                "SLM : « %s(…) » écrit en texte, jamais exécuté "
                                "— repli cloud", _rate,
                            )
                            _annoncer_repli_slm(
                                state, _slm_real_name(_slm_base, settings),
                                f"appel à {_rate} écrit en texte au lieu d'être exécuté",
                            )
                            response = None
                            model_used = "llm:tier-routed"
            except asyncio.TimeoutError:
                logger.warning(
                    "SLM timeout after %.1fs (score=%d) — falling back to LLM",
                    settings.slm_timeout, decision.score,
                )
                _annoncer_repli_slm(
                    state, _slm_real_name(_slm_base, settings),
                    f"délai de {settings.slm_timeout:.0f} s dépassé",
                )
            except Exception as exc:
                logger.warning(
                    "SLM error (score=%d): %s — falling back to LLM",
                    decision.score, exc,
                )
                _annoncer_repli_slm(
                    state, _slm_real_name(_slm_base, settings), str(exc)[:160],
                )

        if response is None:
            # LLM path (or SLM fallback) — needs full system prompt if not built yet
            if use_slm:
                # SLM failed: rebuild full system prompt for LLM fallback. We
                # reuse the Chantier 2 cache machinery so the rebuilt prompt
                # follows the same cacheable/dynamic split as the primary
                # full path. This gives the SLM-fallback flow the same prompt
                # cache hit benefit on subsequent turns.
                from app.services.memory_service import get_user_context as _guc

                async def _fb_build_snapshot() -> str:
                    constraints, memories_, past_interactions, preferences, user_profile = (
                        await asyncio.gather(
                            memory.get_relevant_constraints(user_query, user_id),
                            memory.get_relevant_memories(user_query, user_id),
                            memory.get_relevant_interactions(user_query, user_id, limit=3),
                            memory.get_user_preferences(user_id),
                            _guc(user_id),
                        )
                    )
                    return _format_memory_block(
                        user_profile or "",
                        preferences or [],
                        constraints or [],
                        memories_ or [],
                        past_interactions or [],
                    )

                _fb_snapshot = await _frozen_mem.get_or_build(
                    _conv_id_fb, user_id, _fb_build_snapshot,
                )
                # Use the same IMPORTANT note as the primary path
                # (LLM_INTROSPECTION_NOTE imported from builders.system_prompt).
                # Slight content drift between primary/fallback would have broken
                # the prompt cache prefix mid-conversation — single constant
                # avoids that whole class of bug.
                def _fb_build_cacheable() -> str:
                    return (
                        _lang_directive
                        + _SYSTEM_PROMPT_BASE
                        + LLM_INTROSPECTION_NOTE
                        + _fb_snapshot
                    )

                _fb_cacheable = _spc.get_or_build(_conv_id_fb, _fb_build_cacheable)
                system = (
                    _fb_cacheable
                    + _volatile_segment
                    + _lang_reminder
                )

            # Tier routing: pick the right local/cloud model based on complexity.
            # CRITICAL PERF: the "general" node has access to ALL ~148 tools, which
            # makes bind_tools + the first inference extremely slow (the prompt grows
            # by ~30k tokens with 148 tool schemas). The supervisor already routes
            # tool-needing queries to sub-agents (workspace, infra…), so general is
            # mostly used for chitchat and quick facts that don't need tools. We only
            # bind tools when the query likely needs one (COMPLEX tier, or detected
            # tool keywords).
            from app.services.llm_provider import (
                classify_complexity, get_llm_for_tier, ComplexityTier,
                build_llm_for_provider, get_tier_config,
            )
            _tier = classify_complexity(user_query)

            # ── Hermes Chantier 4 — fallback chain bootstrap ─────────────
            # Capture (or recreate) the per-conversation FallbackState. The
            # chain comes from tier_config so the user only manages providers
            # in one place (Settings → Routage). If a previous turn already
            # switched to a fallback provider, ``_fb_state`` carries that
            # choice into this turn (sticky for the conversation).
            # _conv_id_fb is hoisted to the top of agent_node (used by Chantier 2 too).
            # ⚠️ `_fb_state` l'est AUSSI, et pas par confort : il est relu au
            # pied du nœud, que cette branche ait tourné ou non. Ne pas le
            # réinitialiser ici — et surtout ne pas « ramener » l'init dans ce
            # bloc en croyant ranger.
            if _conv_id_fb:
                _tier_cfg_for_fb = get_tier_config().get(_tier.value, {})
                _chain = list(_tier_cfg_for_fb.get("providers", []) or [])
                if _chain:
                    _fb_state = _fb.get_or_create(_conv_id_fb, _tier.value, _chain)
                    # Retry hotfix (audit Gemini §1.3) — if a fallback has been
                    # active long enough, give the primary a fresh chance. The
                    # call is idempotent and cheap : it only mutates state when
                    # the cool-down has elapsed AND a fallback is currently
                    # active. See ``fallback_manager.should_retry_primary``.
                    if _fb.should_retry_primary(_conv_id_fb):
                        _fb.reset_to_primary(_conv_id_fb, reason="cooldown_elapsed")
                    logger.info(
                        "[chantier4] conv=%s tier=%s chain=%s active_idx=%d (provider=%r)",
                        _conv_id_fb[:8], _tier.value, _chain,
                        _fb_state.current_index, _fb_state.current_provider,
                    )
                    # C3d-4 — départ de tour tracé : tier + chaîne + position.
                    routing_note(
                        _conv_id_fb, "turn",
                        user_id=state.get("user_id", ""),
                        decision=_tier.value,
                        chain_len=len(_chain),
                        active_idx=_fb_state.current_index,
                        provider=str(_fb_state.current_provider),
                    )
                else:
                    logger.info(
                        "[chantier4] conv=%s tier=%s — empty chain in tier_config, "
                        "fallback manager INACTIVE (legacy path)",
                        _conv_id_fb[:8], _tier.value,
                    )
            # Quels outils le modèle voit-il ? La règle vit désormais dans
            # ``app.agent.routing.should_bind_tools`` — hors de cette closure,
            # donc testable. Elle branche toujours les outils sur une demande
            # d'utilisateur : depuis que ``classify_complexity`` rend COMPLEX,
            # le vocabulaire employé ne décide plus rien. « Convertis ce PDF
            # en Word » n'avait aucun outil branché parce que « convertis »
            # ne figurait dans aucune liste de mots-clés.
            #
            # L'escalade « tier SIMPLE local + outils requis → MEDIUM » a été
            # retirée avec le reste : le chat ne descend plus en local, donc
            # elle ne pouvait plus se déclencher.
            from app.agent.routing import should_bind_tools

            _bind_tools_flag = should_bind_tools(
                _tier,
                has_profile=bool(state.get("toolset_profile") or ""),
                automated_task=bool(state.get("automated_task")),
                user_query=user_query,
            )
            _tier_key = _tier.value
            # Cache key differentiates with/without tools bound
            # FIX 2026-05-06 (audit H-5): apply keyword-based tool filtering
            # to avoid binding all 160 tools at every turn. Sub-agents had
            # this filter; the general agent_node did not — resulting in
            # ~15 000 tokens of tool definitions per request (99 % of the
            # prompt) and 5+ minutes of prompt processing on local LLMs.
            #
            # We cache the BASE (unbound) LLM only. Tool binding is cheap
            # and runs per-call with the filtered list — the cache key now
            # encodes only the tier identity.
            # Hermes Chantier 4 — if a fallback is already active for this
            # conversation, build the LLM from the explicit provider rather
            # than re-running the tier cascade (which would land on the
            # primary again). Skip cache because fallback state is per-
            # conversation, not per-tier.
            if _fb_state is not None and _fb_state.is_active_fallback:
                _bind_start = _t.monotonic()
                _base_llm = build_llm_for_provider(_fb_state.current_provider, _tier)
                if _base_llm is None:
                    # Provider can't be instantiated (no key, etc.) — fall
                    # back to the standard tier resolution. We do NOT advance
                    # the chain here ; that's the job of the exception handler.
                    logger.warning(
                        "[fallback] conv=%s active provider %r unbuildable, "
                        "using tier resolution as last resort",
                        _conv_id_fb, _fb_state.current_provider,
                    )
                    _base_llm = get_llm_for_tier(_tier)
                logger.warning(
                    "⏱ TIMING[general.bind_base] %.2fs — tier=%s [FALLBACK active=%r]",
                    _t.monotonic() - _bind_start, _tier_key,
                    _fb_state.current_provider,
                )
            else:
                _base_cache_key = f"{_tier_key}:base"
                if _base_cache_key not in _tier_llm_cache:
                    _bind_start = _t.monotonic()
                    _base_llm = get_llm_for_tier(_tier)
                    _tier_llm_cache[_base_cache_key] = _base_llm
                    logger.warning("⏱ TIMING[general.bind_base] %.2fs — tier=%s (tools_v=%d, cfg_v=%d)",
                        _t.monotonic() - _bind_start, _tier_key, current_version, current_cfg_version)
                _base_llm = _tier_llm_cache[_base_cache_key]

            if _bind_tools_flag:
                # ⚠️ Query de FILTRAGE des outils. En exécution automatique
                # (tâche planifiée / mission), c'est le PROMPT INITIAL — PAS
                # user_query (= messages[-1]). Au tour 2+, messages[-1] est le
                # RÉSULTAT du tool précédent : filtrer dessus jette les outils
                # encore nécessaires (mails, news, météo…) et le modèle, en
                # mode séquentiel (codex, parallel_tool_calls=False → 1 outil/
                # tour), tombe sur « aucun outil pour X » au tour suivant. Bug
                # terrain 13/06 (Daily : agenda OK au tour 1, puis mails/news/
                # météo « pas d'outil »). Un prompt en langage naturel n'est
                # pas rattrapé par l'union tools_named_in_text → il FAUT que le
                # filtre lui-même reparte du prompt complet à chaque tour.
                _filter_query = user_query
                if state.get("automated_task"):
                    from app.agent.helpers.message_content import content_to_text
                    _first_human = next(
                        (m for m in messages
                         if (isinstance(m, dict) and m.get("role") == "user")
                         or getattr(m, "type", None) == "human"),
                        None,
                    )
                    if _first_human is not None:
                        _ip = content_to_text(
                            _first_human.get("content") if isinstance(_first_human, dict)
                            else getattr(_first_human, "content", "")
                        )
                        if _ip:
                            _filter_query = _ip

                # FIX 2026-05-07 (Hermes Chantier 1): prefer the sticky
                # toolset profile from state if defined. This binds the
                # SAME ~30-tool catalog every turn for the conversation,
                # so the model can learn it as muscle memory and the
                # prompt cache prefix stays intact. Empty profile = fall
                # back to the legacy keyword filter (graceful migration).
                _profile = state.get("toolset_profile") or ""
                if _profile:
                    from app.agent.toolset_profiles import (
                        COMPACT_PROFILE,
                        resolve_profile_tools,
                    )
                    # Le catalogue complet n'a été mesuré que sur des têtes de
                    # tier COMPLEX. Mesuré le 02/08 : il pèse ~61 000 tokens de
                    # descriptions, et la tête du tier IMAGE (gemma-4-E4B en
                    # local) déclare une fenêtre de 65 536 — 93 % mangés par le
                    # seul catalogue, il ne resterait rien pour la conversation
                    # ni pour l'image. Hors COMPLEX on garde donc la liste
                    # restreinte : brancher un catalogue qu'une fenêtre ne peut
                    # pas porter, c'est livrer une régression non mesurée.
                    _profile_effectif = (
                        _profile if _tier == ComplexityTier.COMPLEX
                        else COMPACT_PROFILE
                    )
                    _filtered_tools = resolve_profile_tools(
                        _profile_effectif, registry.all_tools,
                    )
                    logger.warning(
                        "[diag.bind] tier=%s profile=%r→%r tools(%d)=%s",
                        _tier_key, _profile, _profile_effectif,
                        len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )
                else:
                    # Legacy path — no profile set (e.g. external API caller
                    # or pre-Chantier-1 conversation row).
                    from app.agent.tool_filter import filter_tools_by_query
                    _filtered_tools = filter_tools_by_query(
                        registry.all_tools,
                        _filter_query,
                        threshold=20,
                        debug_label=f"general.{_tier_key}",
                    )
                    logger.warning(
                        "[diag.bind] tier=%s query=%r tools(%d)=%s [LEGACY]",
                        _tier_key,
                        _filter_query[:80] if _filter_query else "",
                        len(_filtered_tools),
                        sorted(t.name for t in _filtered_tools),
                    )

                # Automated / scheduled tasks run a FIXED, multi-domain prompt
                # with no human to clarify with. En PLUS du filtre ci-dessus
                # (déjà reparti du prompt initial via _filter_query), on UNIONNE
                # tout outil dont le NOM EXACT apparaît dans le prompt — filet
                # pour les prompts qui nomment leurs outils (« Briefing
                # quotidien 9h » : calendar_list_events + system_list_scheduled_
                # tasks que le filtre mots-clés droppait). _filter_query vaut
                # déjà le prompt initial en mode automated → l'union reste
                # stable à chaque tour.
                if state.get("automated_task"):
                    from app.agent.tool_filter import tools_named_in_text
                    _named = tools_named_in_text(registry.all_tools, _filter_query)
                    _have = {t.name for t in _filtered_tools}
                    _extra = [t for t in _named if t.name not in _have]
                    if _extra:
                        _filtered_tools = list(_filtered_tools) + _extra
                        logger.warning(
                            "[automated_task] +%d named tool(s) bound (from initial prompt): %s",
                            len(_extra), sorted(t.name for t in _extra),
                        )

                # When the user's ELY Chrome extension is connected, hide
                # the server-side Playwright tools entirely. They live in
                # a separate, cookie-less context that always lands on
                # login pages — and the LLM tends to fall back to them
                # the second `browser_tab_*` returns less data than
                # expected. Removing them from the toolkit makes the
                # fallback impossible (belt-and-braces with the system
                # prompt rule).
                try:
                    from app.services import browser_extension_registry as _bext
                    _uid_for_bext = str(state.get("user_id") or "")
                    if _uid_for_bext and _bext.is_connected(_uid_for_bext):
                        _PLAYWRIGHT_TOOLS = {
                            "browser_navigate", "browser_screenshot",
                            "browser_get_text", "browser_search_web",
                            "browser_click", "browser_fill", "browser_close",
                        }
                        _before = len(_filtered_tools)
                        _filtered_tools = [
                            t for t in _filtered_tools if t.name not in _PLAYWRIGHT_TOOLS
                        ]
                        if len(_filtered_tools) != _before:
                            logger.warning(
                                "[diag.bind] extension connected → hiding %d Playwright tool(s); "
                                "agent now has %d tools",
                                _before - len(_filtered_tools), len(_filtered_tools),
                            )
                except Exception as _bext_err:
                    logger.debug("[diag.bind] extension-check skipped: %s", _bext_err)

                # Retire les actes ENGAGEANTS déjà accomplis quand la
                # vérification a relancé le tour. Une reprise peut refaire un
                # calcul, elle ne peut pas défaire un acte : le 02/08, Franck a
                # reçu son briefing quatre fois parce que chaque relance
                # rejouait `telegram_send_message`. Ne mord QUE sur reprise —
                # un tour a le droit d'envoyer deux mails.
                try:
                    from app.agent.replay_guard import should_withhold
                    _deja_faits = should_withhold(state.get("messages") or [])
                    if _deja_faits:
                        _avant_rejeu = len(_filtered_tools)
                        _filtered_tools = [
                            t for t in _filtered_tools if t.name not in _deja_faits
                        ]
                        logger.warning(
                            "[diag.bind] reprise — %d acte(s) engageant(s) déjà "
                            "accompli(s), retiré(s) du branchement : %s (%d → %d)",
                            len(_deja_faits), sorted(_deja_faits),
                            _avant_rejeu, len(_filtered_tools),
                        )
                except Exception as _replay_err:  # noqa: BLE001 — jamais au prix du tour
                    logger.debug("[diag.bind] garde de rejeu ignorée: %s", _replay_err)

                # Retire l'outil qui ferait DOUBLON avec la livraison du
                # planificateur. Le 01/08, Franck recevait son briefing deux
                # fois avant même les reprises : le prompt disait « livre-le
                # sur Telegram » et le canal de la tâche valait `telegram`.
                # C'est l'outil qui s'efface — le planificateur seul découpe à
                # 4096 caractères et sait à quel compte lier l'utilisateur.
                try:
                    from app.agent.replay_guard import channel_delivery_tools
                    _doublons = channel_delivery_tools(state.get("delivery_channel"))
                    if _doublons:
                        _avant_liv = len(_filtered_tools)
                        _filtered_tools = [
                            t for t in _filtered_tools if t.name not in _doublons
                        ]
                        if len(_filtered_tools) != _avant_liv:
                            logger.info(
                                "[diag.bind] canal=%s livré par le planificateur "
                                "— %d outil(s) d'envoi retiré(s) : %s",
                                state.get("delivery_channel"),
                                _avant_liv - len(_filtered_tools), sorted(_doublons),
                            )
                except Exception as _liv_err:  # noqa: BLE001 — jamais au prix du tour
                    logger.debug("[diag.bind] garde de livraison ignorée: %s", _liv_err)

                # Cache les outils réservés au tier C des tiers SIMPLE et
                # MEDIUM : un modèle qui ne saura pas s'en servir n'y gagne
                # que des tokens brûlés. La liste est VIDE aujourd'hui — le
                # point d'extension reste branché (cf. tool_sets).
                if _tier != ComplexityTier.COMPLEX:
                    from app.agent.tool_sets import TIER_C_ONLY_TOOLS
                    _before_tc = len(_filtered_tools)
                    _filtered_tools = [
                        t for t in _filtered_tools if t.name not in TIER_C_ONLY_TOOLS
                    ]
                    if len(_filtered_tools) != _before_tc:
                        logger.info(
                            "[diag.bind] tier=%s — dropped %d tier_c_only tool(s)",
                            _tier_key, _before_tc - len(_filtered_tools),
                        )

                # Sprint 4b V2 J7b.2 — bind the user's promoted python_tool
                # skills alongside the built-in toolset. They live per-user in
                # the DB (not the global registry), so this is where they enter
                # the LLM's view. No-op unless LEARNED_PYTHON_TOOLS_ENABLED is on
                # (loader returns []); a learned tool never shadows a builtin.
                # Added after all builtin filtering so it survives untouched
                # and is reused by the fallback re-binds below (same list).
                from app.services.learning.learned_tools_runtime import (
                    append_learned_tools,
                )
                _filtered_tools = await append_learned_tools(_filtered_tools, user_id)

                # ── L'interrupteur de Paramètres → Outils (24/08) ──────────
                # `GET /skills/` et `PUT /skills/{nom}` existaient, la table
                # `SkillPreference` se remplissait, `get_user_active_tools()`
                # savait lire — et personne ne l'appelait. Désactiver une
                # compétence n'avait aucun effet sur ce qui partait au modèle.
                #
                # Quatrième occurrence de ce motif ce mois-ci : une écriture
                # qui atteint la base sans atteindre le runtime (#272, #336,
                # #342). Preuve la plus parlante : `fibonacci`, un outil de
                # test, est marqué `enabled_by_default=False` depuis toujours
                # et partait quand même dans chaque prompt.
                #
                # APRÈS les outils appris, délibérément : l'utilisateur doit
                # pouvoir couper aussi ce qu'Ely s'est créé.
                _desactives = await disabled_tool_names(user_id)
                _filtered_tools = appliquer_preferences(
                    _filtered_tools, _desactives, contexte=f"tier-{_tier_key}",
                )

                # find_tool discovery — union the tools the model surfaced via
                # find_tool earlier in THIS conversation (sticky), so it can
                # actually call them. The lean profile stays cache-stable; the
                # cache re-warms once when a tool is first discovered. No-op
                # until find_tool is used. (The recurring "tool invisible" bug
                # becomes self-healing — cf Sheets/Drive #37.)
                from app.agent.discovered_tools import get_discovered
                _discovered = get_discovered(str(state.get("conversation_id") or ""))
                if _discovered:
                    _have_d = {t.name for t in _filtered_tools}
                    _extra_d = [
                        t for t in registry.all_tools
                        if t.name in _discovered and t.name not in _have_d
                    ]
                    if _extra_d:
                        _filtered_tools = list(_filtered_tools) + _extra_d
                        logger.warning(
                            "[find_tool] +%d discovered tool(s) bound: %s",
                            len(_extra_d), sorted(t.name for t in _extra_d),
                        )

                # Mini-chantier A — apply parallel_tool_calls policy by
                # model family. Permissive models (Qwen, Mistral…) and OpenAI
                # family invent downstream args (e.g. fake local_path) when
                # they emit parallel tool_calls. Forcing one-call-per-turn
                # makes the model wait for each result before chaining.
                _llm_with_tools_req = _bind_tools_smart(_base_llm, _filtered_tools)
            else:
                _llm_with_tools_req = _base_llm
            # Resolve the actual provider+model behind the tier so analytics
            # shows "lm_studio/llama-xlam-2-8b-fc-r-mlx" instead of "tier-medium".
            # Falls back gracefully to the tier label if introspection fails.
            try:
                from app.services.llm_provider import describe_llm
                _p, _m = describe_llm(_base_llm)
                model_used = f"llm:{_p}/{_m}{'+tools' if _bind_tools_flag else ''}"
            except Exception:
                model_used = f"llm:tier-{_tier_key}{'+tools' if _bind_tools_flag else ''}"

            # Le VRAI modèle, pas l'étiquette du tier : `_tier_key` vaut
            # « medium » / « complex », que la table de fenêtres ne connaît
            # pas — elle retombait donc sur 8 192 tokens pour tout le monde,
            # alors que DeepSeek v4 en offre 64 000. Le modèle est déjà résolu
            # juste au-dessus par describe_llm ; on réutilise le même parseur
            # que la ventilation plutôt que d'en écrire un second.
            from app.services.usage_instrumentation import (
                split_model_used as _split_mu,
            )
            _fitted = fit_messages_to_context(
                messages=_sanitized,
                system_prompt=system,
                model=_split_mu(model_used)[1] or _tier_key,
                reserve_for_response=1024,
                # Ancrage du mandat — cf. le commentaire du chemin SLM.
                preserve_first=bool(state.get("automated_task")),
            )
            # La frontière d'envoi (02/09/2026) : à partir d'ici, `system`
            # n'est plus ce qu'on envoie — `_systeme_envoye` l'est. Les replis
            # plus bas repartent de `_invoke_msgs`, donc ils héritent du même
            # traitement, mais chacun ré-évalue pour SON fournisseur.
            _systeme_envoye = prompt_systeme_sortant(system, _base_llm, _conv_id_fb)
            _invoke_msgs = (
                [{"role": "system", "content": _systeme_envoye}]
                + _fitted
            )
            # P2 — ventilation du contexte (port de Hermes v0.19). C'est ICI
            # que la requête est enfin complète : prompt assemblé, outils
            # bindés, messages ajustés. Mesuré en prod, certains tours pèsent
            # 230 000 tokens d'entrée sans qu'on sache d'où ils viennent ;
            # cette décomposition répond à la question sur du trafic réel.
            # Instrument passif : n'échoue jamais, ne change aucun envoi.
            try:
                from app.services.context_breakdown import (
                    LAST_CONTEXT_BREAKDOWN, compact_breakdown,
                    compute_context_breakdown,
                )
                from app.services.usage_instrumentation import (
                    split_model_used as _split_model_used,
                )
                _ctx_breakdown = compact_breakdown(
                    compute_context_breakdown(
                        # Ce qui est ENVOYÉ, pas ce qui a été composé : le
                        # tableau de bord doit ventiler la requête réelle.
                        system_prompt=_systeme_envoye,
                        tools=_filtered_tools if _bind_tools_flag else [],
                        messages=_fitted,
                        # `model_used` est toujours défini ici ; on réutilise
                        # le parseur de usage_instrumentation plutôt que d'en
                        # écrire un second qui dériverait.
                        model=_split_model_used(model_used)[1],
                    )
                )
                # La ContextVar reste posée pour les appelants qui vivent dans
                # la MÊME tâche asyncio (missions, canaux). Elle ne suffit pas
                # au caller du graphe : c'est l'état renvoyé plus bas qui
                # traverse la frontière de tâche.
                LAST_CONTEXT_BREAKDOWN.set(_ctx_breakdown)
            except Exception as _cb_exc:  # noqa: BLE001
                logger.debug("context_breakdown ignoré: %s", _cb_exc)
            try:
                _infer_t = _t.monotonic()
                from app.services.qwen_no_think import (
                    inject_no_think, is_qwen_llm, strip_no_think, strip_think_block,
                )
                # Only Qwen understands /no_think; other models would echo it.
                if is_qwen_llm(_base_llm):
                    _invoke_msgs = inject_no_think(_invoke_msgs)
                # FIX 2026-05-06 (P1 OpenClaw-style): if a recent ToolMessage
                # carries a base64 screenshot AND the model supports vision,
                # inject the image as a HumanMessage so the model can SEE it
                # rather than just read the JSON metadata.
                try:
                    from app.agent.vision_injection import maybe_inject_screenshot
                    _invoke_msgs = maybe_inject_screenshot(_invoke_msgs, _base_llm)
                except Exception as _vis_exc:
                    logger.debug("vision_injection skipped: %s", _vis_exc)
                response = await ainvoke_with_deadline(
                    _llm_with_tools_req, _invoke_msgs, tier=_tier, surface="general")
                # Strip any <think> block that slipped through
                if hasattr(response, 'content') and isinstance(response.content, str):
                    response.content = strip_think_block(response.content)
                    # Note: empirically tried 3 rounds of fixes to suppress the
                    # JSON re-encoding that cloud LLMs apply to
                    # search_past_conversations_tool output (system prompt
                    # rules, tool docstring, server-side regex filter). None
                    # held on DeepSeek/Haiku/Qwen/Mistral/Kimi — only the
                    # local Ministral 3B respects the prose format. Franck
                    # decision 2026-05-16: accept the cosmetic JSON leak,
                    # don't accumulate defensive code that may have side
                    # effects elsewhere. The functional memory recall is
                    # solid; the structural-output bias is a known LLM-side
                    # behaviour that should be addressed via product design
                    # later (e.g. dedicated UI rendering, or a bypass that
                    # ships the tool output directly without LLM reformat).

                # FIX 2026-05-06 (Option A): some cloud models (Kimi K2.x,
                # Qwen 3.6 Flash via DashScope, occasionally DeepSeek) emit
                # tool calls as TEXT inside content instead of populating
                # the structured `tool_calls` field. Without recovery, the
                # graph receives `tool_calls=[]` and stalls. Also handles
                # hallucinated tool names like `send_email` →
                # `gmail_send_email` via fuzzy matching.
                from app.agent.tool_call_recovery import (
                    recover_tool_calls_into_response,
                    detect_empty_promise,
                )
                # DIAG 2026-05-06: log raw response shape BEFORE recovery
                _raw_tc = getattr(response, "tool_calls", None) or []
                _raw_content = getattr(response, "content", "") or ""
                _raw_content_str = _raw_content if isinstance(_raw_content, str) else str(_raw_content)
                logger.warning(
                    "[diag.resp] tier=%s raw_tool_calls=%d content_len=%d content_head=%r",
                    _tier_key, len(_raw_tc), len(_raw_content_str), _raw_content_str[:200],
                )
                _recovered = recover_tool_calls_into_response(
                    response,
                    real_tool_names={t.name for t in registry.all_tools},
                )
                if _recovered:
                    logger.warning(
                        "[recovery] tier=%s — recovered %d tool_call(s) from text content",
                        _tier_key, _recovered,
                    )

                # FIX 2026-05-06 (P4): empty-promise guard — if the model
                # claims delivery ("je télécharge sur ton Drive…", "sending
                # the file now…") but produced ZERO tool_calls, re-invoke
                # with a corrective system message. Limited to ONE retry
                # per turn to avoid infinite loops if the model is stubborn.
                _post_tc = getattr(response, "tool_calls", None) or []
                _post_content = getattr(response, "content", "") or ""
                _post_content_str = _post_content if isinstance(_post_content, str) else str(_post_content)
                if not _post_tc and detect_empty_promise(_post_content_str):
                    logger.warning(
                        "[empty_promise] tier=%s — model promised delivery without "
                        "calling a tool. Content head: %r. Re-prompting once.",
                        _tier_key, _post_content_str[:200],
                    )
                    _correction_msg = {
                        "role": "system",
                        "content": (
                            "⚠️ Tu viens d'annoncer une action (téléchargement, envoi, "
                            "sauvegarde, RECHERCHE, vérification…) MAIS tu n'as appelé "
                            "AUCUN outil dans ton dernier message. Cette annonce est "
                            "vide — rien ne s'exécute, l'utilisateur ne reçoit rien.\n\n"
                            "DEUX OPTIONS :\n"
                            "1. Si tu DOIS livrer le fichier maintenant, réémets ta "
                            "réponse en appelant explicitement l'outil approprié "
                            "(gmail_send_with_local_attachment, drive_create_file, "
                            "desktop_copy_file, etc.) avec les bons paramètres.\n"
                            "2. Si tu ne peux pas (paramètre manquant), dis-le clairement "
                            "à l'utilisateur et demande-lui le paramètre manquant — sans "
                            "prétendre qu'une livraison est en cours.\n\n"
                            "NE répète PAS la phrase « en cours de téléchargement » sans "
                            "appel d'outil cette fois-ci."
                        ),
                    }
                    try:
                        _retry_msgs = list(_invoke_msgs) + [
                            {"role": "assistant", "content": _post_content_str},
                            _correction_msg,
                        ]
                        _retry_response = await ainvoke_with_deadline(
                            _llm_with_tools_req, _retry_msgs, tier=_tier, surface="general-retry")
                        _retry_tc = getattr(_retry_response, "tool_calls", None) or []
                        _retry_content = getattr(_retry_response, "content", "") or ""
                        if _retry_tc:
                            logger.warning(
                                "[empty_promise] retry produced %d tool_call(s) — "
                                "replacing original response", len(_retry_tc),
                            )
                            response = _retry_response
                        elif isinstance(_retry_content, str) and _retry_content.strip():
                            # No tool but a clearer prose without false promise — use it
                            if not detect_empty_promise(_retry_content):
                                logger.warning("[empty_promise] retry returned honest prose — using it")
                                response = _retry_response
                            else:
                                logger.warning("[empty_promise] retry STILL promises without tool — keeping original")
                    except Exception as _retry_exc:
                        logger.warning("[empty_promise] retry failed (%s)", _retry_exc)

                logger.warning("⏱ TIMING[general.infer] %.2fs — tier=%s, tool_calls=%d",
                    _t.monotonic() - _infer_t, _tier_key, len(getattr(response, 'tool_calls', []) or []))

                # ── Audit H-1 fix (2026-05-06, refined 2026-05-26): garde anti-hallu ──
                # Modèles locaux 7-14B (Qwen, Mistral, Llama small) ont
                # tendance à émettre du TEXTE en plain "je vais faire X"
                # au lieu d'un tool_call JSON, surtout sur des verbes
                # d'action explicites ("envoie", "supprime", "crée").
                # Symptôme observé en prod : Qwen 3 VL 8B refuse "envoie
                # par mail" au lieu d'appeler gmail_send_with_attachment.
                # Garde : si modèle LOCAL + 0 tool_calls + user query
                # contient un verbe d'action → fallback cloud immédiat.
                #
                # 2026-05-26 : ajout d'un log détaillé AVANT la décision,
                # suite à un faux-positif observé le 25/05 où DeepSeek-pro
                # (cloud, base_url=api.deepseek.com) a été incorrectement
                # flaggé comme local → conv stickée sur Haiku 1h+. Ce log
                # permettra de diagnostiquer la prochaine occurrence sans
                # reproduire le scénario en aveugle.
                _has_tool_calls = bool(getattr(response, 'tool_calls', None))
                from app.services.qwen_no_think import is_local_openai_llm as _is_local_oa
                _is_local = _is_local_oa(_base_llm)
                # Kill-switch (2026-05-31) : H-1 forces a cloud fallback when a
                # LOCAL model returns plain text instead of a tool_call on an
                # action query. That's the right default, but it makes
                # benchmarking a new local model painful (every tool query
                # silently escapes to DeepSeek). HALLUCINATION_GUARD_DISABLED
                # truthy = let the local response stand, no forced fallback.
                _h1_disabled = (os.getenv("HALLUCINATION_GUARD_DISABLED") or "").strip().lower() in {
                    "1", "true", "yes", "on",
                }
                _action_verbs = (
                    "envoie", "envoy", "supprime", "delete", "send",
                    "crée", "creer", "create", "écris", "ecris", "write",
                    "lance", "exécute", "execute", "run", "schedule",
                    "rappel", "remind", "ferme", "close", "ouvre", "open",
                    "télécharge", "download", "achète", "buy", "réserve",
                    "book", "réponds", "reply", "transfère", "transfer",
                    "capture", "screenshot", "photographie",
                )
                _query_has_action = any(v in user_query.lower() for v in _action_verbs)
                # 2026-06-12 — le signal le plus fort n'est pas dans la
                # QUESTION mais dans la RÉPONSE : un modèle qui écrit « je
                # vais faire une recherche web » sans tool_call doit
                # déclencher H-1 même si la question n'a aucun verbe
                # d'action (« C'est quoi Choose France 2026 ? »).
                _resp_announces = (not _has_tool_calls) and detect_empty_promise(
                    response.content if isinstance(response.content, str)
                    else str(response.content or "")
                )
                # Detailed log so any future false-positive is easy to debug
                _h1_base_url = (
                    getattr(_base_llm, "openai_api_base", None)
                    or getattr(_base_llm, "base_url", None)
                    or ""
                )
                _h1_model_name = (
                    getattr(_base_llm, "model_name", None)
                    or getattr(_base_llm, "model", None)
                    or ""
                )
                if (_query_has_action or _resp_announces) and _bind_tools_flag:
                    logger.info(
                        "[H-1.eval] tier=%s local=%s tool_calls=%d action=%s "
                        "resp_announces=%s model=%r base_url=%r",
                        _tier_key, _is_local, len(getattr(response, "tool_calls", []) or []),
                        _query_has_action, _resp_announces, _h1_model_name, _h1_base_url,
                    )
                if (
                    _is_local
                    and not _has_tool_calls
                    and (_query_has_action or _resp_announces)
                    and _bind_tools_flag
                    and not _h1_disabled
                ):
                    logger.warning(
                        "[H-1] Local LLM (tier=%s) returned PLAIN TEXT instead of "
                        "tool_call despite action verb in user query — falling "
                        "back to cloud LLM. Response preview: %r",
                        _tier_key, (response.content or "")[:120],
                    )
                    # Force-trigger the fallback path below by raising a
                    # synthetic "recoverable" exception. The existing fallback
                    # loop will iterate through get_fallback_llms() and pick
                    # the first cloud model with a working API key.
                    raise RuntimeError("h1_fallback: local LLM hallucinated plain text")
            except Exception as primary_exc:
                # Hermes Chantier 4 — classify the exception and ask the
                # FallbackManager to advance to the next provider in the
                # conversation's chain. If the exception is unrecognised
                # (genuine programmer bug), we re-raise so it surfaces.
                _reason = _fb.classify_exception(primary_exc)
                if _reason is None:
                    raise

                logger.warning(
                    "[fallback] primary LLM failed (%s/%s): %s",
                    type(primary_exc).__name__, _reason.value, primary_exc,
                )
                response = None
                # Strip any /no_think marker (Qwen-only) before trying a
                # different provider that doesn't understand it.
                _fallback_msgs = strip_no_think(_invoke_msgs)

                def _pour_le_repli(_msgs: list, _llm_cible: Any) -> list:
                    """Le prompt système du repli est celui que SON modèle a
                    le droit de recevoir (02/09/2026).

                    Sans ça, le trou le plus vicieux du chemin : la garde H-1
                    existe précisément pour envoyer chez un modèle CLOUD ce
                    qu'un modèle LOCAL vient de rater. Le prompt avait été
                    composé — et laissé en clair — pour la tête locale.
                    """
                    _rendu = list(_msgs)
                    if _rendu and isinstance(_rendu[0], dict) and _rendu[0].get("role") == "system":
                        _rendu[0] = {
                            **_rendu[0],
                            "content": prompt_systeme_sortant(
                                system, _llm_cible, _conv_id_fb,
                            ),
                        }
                    return _rendu

                # Walk forward through the chain until a provider answers or
                # the chain is exhausted. Each provider is given ONE attempt;
                # subsequent failures advance again. This loop is bounded by
                # len(chain) so it can never spin.
                if _conv_id_fb and _fb_state is not None:
                    while True:
                        # Sprint 3.7 Jalon 2 — capture the BEFORE state so the
                        # learning signal can record from→to once try_activate
                        # has advanced the chain.
                        _from_provider_before = _fb_state.current_provider
                        _new_provider_id = _fb.try_activate(_conv_id_fb, _reason)
                        if _new_provider_id:
                            try:
                                from app.services.learning import record_provider_switch
                                spawn(record_provider_switch(
                                    user_id=user_id,
                                    conversation_id=_conv_id_fb,
                                    tier_llm=_tier.value if hasattr(_tier, "value") else str(_tier),
                                    from_provider=_from_provider_before,
                                    to_provider=_new_provider_id,
                                    reason=_reason.value if hasattr(_reason, "value") else str(_reason),
                                    position_in_chain=_fb_state.current_index + 1,
                                ))
                            except Exception as _sig_exc:
                                logger.debug("provider switch signal skipped: %s", _sig_exc)
                        if not _new_provider_id:
                            logger.warning(
                                "[fallback] chain exhausted for conv=%s",
                                _conv_id_fb,
                            )
                            break
                        _new_llm = build_llm_for_provider(_new_provider_id, _tier)
                        if _new_llm is None:
                            logger.warning(
                                "[fallback] provider %r unbuildable, advancing",
                                _new_provider_id,
                            )
                            continue  # ask manager for the next one
                        try:
                            # PRESERVE the toolset profile — the cardinal sin
                            # of the old fallback loop was rebinding all 145
                            # tools, breaking the Chantier 1 contract. Here
                            # we re-bind exactly the same _filtered_tools the
                            # primary saw.
                            if _bind_tools_flag:
                                # Apply same parallel-policy as primary,
                                # auto-detecting the new provider's family.
                                _new_with_tools = _bind_tools_smart(
                                    _new_llm, _filtered_tools,
                                )
                            else:
                                _new_with_tools = _new_llm
                            response = await ainvoke_with_deadline(
                                _new_with_tools, _pour_le_repli(_fallback_msgs, _new_llm),
                                tier=_tier, surface="general-fallback")
                            logger.warning(
                                "[fallback] succeeded with %r", _new_provider_id,
                            )
                            # Keep model_used in sync with the active provider.
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(_new_llm)
                                model_used = f"llm:{_p}/{_m}+tools[fallback]"
                            except Exception:
                                model_used = f"llm:{_new_provider_id}+tools[fallback]"
                            break
                        except Exception as _next_exc:
                            _next_reason = _fb.classify_exception(_next_exc)
                            if _next_reason is None:
                                # Real bug in the new provider — re-raise.
                                raise
                            logger.warning(
                                "[fallback] %r also failed (%s): %s — advancing",
                                _new_provider_id, _next_reason.value, _next_exc,
                            )
                            _reason = _next_reason
                            continue

                # SAFETY NET (Chantier 4 V1.1) — if the per-tier chain didn't
                # produce a working response (single-provider tier, all
                # providers exhausted, instances unbuildable…), DO NOT raise
                # yet. Try the legacy global fallback list first (Gemini,
                # Anthropic, OpenRouter, Ollama installed system-wide). This
                # restores the pre-Chantier-4 robustness for users whose tier
                # config is minimal — better to silently bind 145 tools on a
                # cloud frontier than to surface "Erreur interne" to the user.
                if response is None:
                    logger.info(
                        "[fallback] tier-chain exhausted/unavailable, "
                        "trying legacy global helpers"
                    )
                    for fallback_label, fallback_llm in get_fallback_llms():
                        try:
                            # fallback_label is "anthropic/claude-…" or
                            # "gemini/gemini-2.5-flash" — extract model name
                            # for family classification.
                            _legacy_model_name = (
                                fallback_label.split("/", 1)[1]
                                if "/" in fallback_label
                                else fallback_label
                            )
                            _legacy_with_tools = (
                                _bind_tools_smart(
                                    fallback_llm, _filtered_tools,
                                    model_name=_legacy_model_name,
                                )
                                if _bind_tools_flag
                                else fallback_llm
                            )
                            response = await ainvoke_with_deadline(
                                _legacy_with_tools, _pour_le_repli(_fallback_msgs, fallback_llm),
                                tier=_tier, surface="general-legacy")
                            logger.info(
                                "[fallback] legacy succeeded with %s", fallback_label,
                            )
                            try:
                                from app.services.llm_provider import describe_llm
                                _p, _m = describe_llm(fallback_llm)
                                model_used = f"llm:{_p}/{_m}+tools[legacy_fallback]"
                            except Exception:
                                model_used = f"llm:{fallback_label}+tools[legacy_fallback]"
                            break
                        except Exception as fallback_exc:
                            logger.warning(
                                "[fallback] legacy %s also failed: %s",
                                fallback_label, fallback_exc,
                            )

                if response is None:
                    raise primary_exc

        # Hermes Chantier 4 — track this turn's response so the manager can
        # detect empty-streaks (≥3 empties → auto-fallback on the next turn).
        # We pass the current response's content + tool_calls flag.
        if _conv_id_fb and _fb_state is not None and response is not None:
            _resp_content = getattr(response, "content", "") or ""
            if isinstance(_resp_content, list):
                # Multi-block content — concatenate text chunks.
                _resp_content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in _resp_content
                )
            _has_tc = bool(getattr(response, "tool_calls", None))
            try:
                _fb.record_response(_conv_id_fb, str(_resp_content), _has_tc)
            except Exception as _rec_exc:
                logger.debug("fallback.record_response failed: %s", _rec_exc)

        # Fire-and-forget: extract facts from this exchange for user memory.
        # UNE fois par tour, pas une fois par itération : ce nœud est ré-entré
        # après chaque lot d'outils (``add_edge("tools", "agent")``), et
        # extraire à chaque passage produisait 74,5 % de tous les appels de
        # modèle sur 7 jours pour un contenu quasi identique. Le prédicat vit
        # dans memory_service, avec le second point d'appel (force_summary).
        from app.services.memory_service import maybe_spawn_fact_extraction

        maybe_spawn_fact_extraction(user_id, messages, response)

        # Hermes Chantier 9 — increment the iteration counter when the
        # response carries tool_calls (i.e. the loop will bounce back here
        # for another inference). Bare-text responses don't loop, so they
        # don't burn the budget. The counter is read by ``should_continue``
        # to detect when we're approaching the recursion limit and need
        # to force a final textual summary.
        _has_tool_calls = bool(getattr(response, "tool_calls", None))
        _next_iter = state.get("iteration_count", 0) + (1 if _has_tool_calls else 0)
        return {
            "messages": [response],
            "model_used": model_used,
            "routing_score": routing_score,
            "iteration_count": _next_iter,
            # Voyage par l'état, comme `model_used` : c'est le seul véhicule
            # qui franchit la frontière de tâche asyncio de LangGraph.
            "context_breakdown": _ctx_breakdown or "",
        }

    return agent_node


# ------------------------------------------------------------------ #
# Tool node                                                            #
# ------------------------------------------------------------------ #
# Moved to app/agent/tool_node.py (refactor 2026-05-25 Phase 3).
from app.agent.tool_node import tool_node  # noqa: E402,F401


# ------------------------------------------------------------------ #
# Router                                                               #
# ------------------------------------------------------------------ #

# Moved to app/agent/routing.py (refactor 2026-05-25 Phase 2.1).
from app.agent.routing import (  # noqa: E402,F401
    MAX_AGENT_ITERATIONS,
    should_continue,
)


# Moved to app/agent/force_summary.py (refactor 2026-05-25 Phase 2.2).
from app.agent.force_summary import force_summary_node  # noqa: E402,F401
