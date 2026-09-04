# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/missions/chat_loop.py
# @brief      La mission libre est un chat sans humain : elle tourne sur la
#             boucle plate de l'agent, avec le carnet pour memoire et les
#             budgets de la mission pour bornes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La mission libre tourne sur la boucle du chat (02/09/2026).

POURQUOI CE MODULE EXISTE
-------------------------
Ely avait DEUX moteurs d'agent. Le chat est une boucle plate — agent, outils,
agent, jusqu'à la réponse — avec un budget d'itérations, un résumé forcé et
un nœud de conformité. Les missions avaient leur propre machine à états
(plan / act / eval / replan) dont le graphe SORT après chaque tour : chaque
tick devait reconstruire depuis SQL ce qu'une conversation aurait simplement
gardé. Vingt-trois lots de correctifs n'ont pas suffi à faire aboutir une
prospection basique — l'acteur rouvrait le même onglet quatre fois parce
qu'à chaque tour il avait oublié le message d'erreur du tour précédent.

Le propriétaire a tranché le 02/09/2026 : « on a essayé de faire autrement
pour atteindre l'objectif, sans jamais y arriver. Tant pis s'il faut casser
l'existant. »

CE QUE FAIT CE CHEMIN
---------------------
Un PASSAGE (un réveil de la mission) = un tour de chat automatisé :

  1. le carnet de bord est relu en tête de la consigne — c'est la mémoire de
     la mission entre deux réveils, la compaction d'Hermes posée à la
     frontière du tick ;
  2. le graphe plat tourne : le modèle enchaîne ses outils dans UN SEUL fil,
     il relit ses propres résultats sans qu'on ait à les lui redire ;
  3. chaque outil passe par ``missions.nodes.dispatch_tool`` — la passerelle
     des missions, donc le MANDAT, les disjoncteurs et le journal restent en
     vigueur ; c'est elle qui reçoit l'identité de la mission ;
  4. les budgets de la mission (itérations, tokens, échéance) mordent AU
     MILIEU du passage : l'outil est refusé et le modèle est sommé de
     conclure, il n'y a pas d'exception qui jetterait le travail fait ;
  5. l'arrêt d'urgence coupe le passage en cours, il n'attend pas sa fin ;
  6. à la sortie, le bilan du modèle est archivé au carnet, daté.

La mission se termine quand le modèle conclut. S'il lui reste du travail, il
le dit avec ``MARQUEUR_A_SUIVRE`` et le heartbeat le réveille.

CE QUI N'EST PAS TOUCHÉ
-----------------------
Les missions STRUCTURÉES (``spec_yaml``) gardent leur exécuteur : ``foreach``,
handlers ``on_error`` / ``ask_user``, reprise après réponse humaine. C'est un
contrat que l'utilisateur écrit. Le routage vit dans
``services/mission_heartbeat.py``.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agent.conformity import conformity_node, route_after_conformity
from app.agent.missions.outillage import elargir, outillage_de_la_mission
from app.agent.helpers.message_content import content_to_text
from app.agent.routing import (
    CHAT_RECURSION_LIMIT,
    MAX_AGENT_ITERATIONS,
    should_continue,
)
from app.agent.state import AgentState
from app.services import mission_service

logger = logging.getLogger(__name__)


# Le modèle le pose en fin de réponse quand il lui reste du travail. Sans lui,
# le passage vaut conclusion : c'est le défaut le moins coûteux des deux.
# Une mission finie qu'on relance brûle du budget en silence ; une mission
# inachevée qu'on clôt le DIT dans son résumé, et l'utilisateur la relance.
MARQUEUR_A_SUIVRE: str = "[MISSION_A_SUIVRE]"

# Lu comme le modèle l'écrit : accents, casse, tirets ou espaces. La leçon du
# marqueur « ÉCARTS : » (02/09/2026) — un contrat de protocole se reconnaît à
# une espace près, sinon il n'existe pas.
_MARQUE = re.compile(r"\[\s*MISSION[\s_-]*[AÀÂ][\s_-]*SUIVRE\s*\]", re.IGNORECASE)

_STATUTS_VIVANTS: frozenset[str] = frozenset({"running", "planning"})

# Le profil d'outils du passage — « default » vaut TOUT LE CATALOGUE au tier
# COMPLEX (cf. app/agent/toolset_profiles.py), et une mission tourne toujours
# sur COMPLEX. Hors COMPLEX, le nœud retombe de lui-même sur `compact` : la
# fenêtre du modèle local ne porte pas les ~61 000 tokens de descriptions.
# « mission » = le même catalogue complet, moins les outils d'auto-diagnostic
# (journaux, santé, configuration des modèles) : une mission qui les a sous la
# main s'en sert pour s'ausculter au lieu de travailler (03/09/2026).
_PROFIL_OUTILS: str = "mission"

# Ce qu'un outil refusé pour cause de budget renvoie au modèle. Un refus MUET
# le ferait réessayer ; nommé, il conclut.
_CONSIGNE_BUDGET = (
    "Action non exécutée : {raison}. N'appelle plus AUCUN outil. Réponds "
    "maintenant en texte : ce que tu as fait dans ce passage, l'état courant "
    "et ce qui reste à faire."
)

# Combien de caractères du bilan d'un passage sont archivés au carnet. Le
# carnet est relu en tête du passage suivant : trop long, il mange le contexte
# du modèle ; trop court, il perd l'état.
_BILAN_MAX: int = 1500


# ── Interruption ─────────────────────────────────────────────────────────────


class MissionInterrompue(RuntimeError):
    """La mission n'est plus en cours pendant le passage (arrêt d'urgence,
    pause). Levée par le nœud d'outils, rattrapée par le passage : le travail
    déjà fait est conservé, plus aucune action n'est jouée."""


# ── Budgets ──────────────────────────────────────────────────────────────────


def _tokens_des_messages(messages: Any) -> int:
    """Ce que le passage a réellement consommé, lu sur les messages du modèle.

    Les compteurs de la mission ne sont écrits qu'à la fin du passage ; ici on
    lit la consommation EN COURS, sinon le budget de tokens ne mordrait jamais
    à l'intérieur d'un passage — exactement le trou que ce chantier ferme
    pour les itérations."""
    total = 0
    caracteres = 0
    for m in messages or ():
        meta = getattr(m, "usage_metadata", None) or {}
        try:
            total += int(meta.get("total_tokens") or 0)
        except (TypeError, ValueError, AttributeError):
            pass
        contenu = getattr(m, "content", "")
        caracteres += len(contenu if isinstance(contenu, str) else str(contenu or ""))
    if total:
        return total
    # Repli quand le fournisseur ne renvoie AUCUN `usage_metadata` — LM Studio
    # en flux, et le tier COMPLEX est configurable sur une tête locale, donc
    # le cas n'est pas théorique. Sans lui la fonction rend 0 : le passage
    # n'ajoute rien à `Mission.tokens_used`, qui reste à zéro pour toujours,
    # et la clause tokens du budget ne peut plus jamais mordre (02/09/2026).
    # Même heuristique des 4 caractères par jeton que le chemin historique
    # (`missions/nodes.py`, `_log_mission_llm_usage`). Elle SOUS-ESTIME —
    # elle ne voit ni le prompt système ni les schémas d'outils : elle dit
    # « il s'est passé quelque chose », pas « voilà combien ».
    return max(1, caracteres // 4) if caracteres else 0


class _Budgets:
    """Photo des budgets au début du passage, plus ce que le passage dépense.

    On ne relit pas la base à chaque appel d'outil : les compteurs persistés
    sont écrits par ce passage lui-même, la photo + le compte local disent la
    même chose sans une requête par action."""

    def __init__(self, mission: Any) -> None:
        self.iterations_restantes = max(
            0, int(mission.budget_iterations or 0) - int(mission.iterations_used or 0)
        )
        self.tokens_restants = max(
            0, int(mission.budget_tokens or 0) - int(mission.tokens_used or 0)
        )
        echeance = getattr(mission, "deadline", None)
        if echeance is not None and echeance.tzinfo is None:
            # SQLite rend des datetimes naïfs — les comparer à un aware lève
            # TypeError et ferait échouer la mission sur une cause inventée.
            echeance = echeance.replace(tzinfo=timezone.utc)
        self.echeance = echeance
        self.actions = 0

    def refus(self, tokens_du_passage: int) -> Optional[str]:
        """La raison de refuser l'action suivante, ou ``None``."""
        if self.actions >= self.iterations_restantes:
            return (
                f"budget d'itérations de la mission épuisé "
                f"({self.actions}/{self.iterations_restantes} pour ce passage)"
            )
        if self.tokens_restants and tokens_du_passage >= self.tokens_restants:
            return (
                f"budget de tokens de la mission épuisé "
                f"({tokens_du_passage}/{self.tokens_restants})"
            )
        if self.echeance is not None and datetime.now(timezone.utc) > self.echeance:
            return f"échéance de la mission dépassée ({self.echeance.isoformat()})"
        return None


def _catalogue_du_profil() -> list:
    """Le périmètre d'une mission : le profil `mission` (tout le catalogue
    moins le diagnostic). La sélection par familles s'y applique."""
    from app.agent.toolset_profiles import resolve_profile_tools
    from app.skills import get_skill_registry

    return resolve_profile_tools(_PROFIL_OUTILS, get_skill_registry().all_tools)


# ── Le nœud d'outils de la mission ───────────────────────────────────────────


async def _statut(mission_id: str) -> str:
    m = await mission_service.get_mission(mission_id)
    return getattr(m, "status", "") or ""


async def _tracer(
    mission_id: str, nom: str, args: dict, sortie: str, ok: bool,
) -> None:
    """Une ligne ``mission_steps`` par action — la piste d'audit de l'UI, et
    le compteur d'itérations de la mission (``add_step`` n'incrémente que sur
    la phase ``act``). Best-effort : une trace perdue ne tue pas un passage."""
    try:
        await mission_service.add_step(
            mission_id, phase="act",
            tool_name=nom, tool_input=args, tool_output=sortie,
            success=ok, model_used="chat_loop",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mission %s : trace de %s non écrite (%s)", mission_id, nom, exc)


def _agent_qui_se_photographie(dernier_etat: Optional[dict] = None):
    """Le nœud ``agent`` du chat, qui recopie au passage ce qu'il vient de
    produire dans le carnet de secours du COÛT.

    ⚠️ 02/09/2026 — POURQUOI CE NŒUD EXISTE. Le carnet de secours n'était
    d'abord posé que dans le nœud ``tools``, qui photographie l'état AVANT de
    lancer les outils. Il ne portait donc jamais le tour d'agent qui suit le
    DERNIER appel d'outil — et ce tour-là est le plus cher. Mesuré :
    agent(appel d'outil, 110 tk) → tools → agent(réponse, 5 200 tk) → verify
    rend « ÉCARTS : … » → l'agent repart et prend un 429. ``tokens_used``
    valait 110 pour 5 310 tokens réellement facturés : 2 % attribués.

    Le chemin n'a rien d'exotique — c'est la boucle de conformité, la raison
    d'être de ce module. Le nœud enveloppe donc ``create_agent_node()`` et
    ajoute sa propre sortie à la photo : ``agent_node`` rend bien ``messages``
    et ``model_used`` dans son état.
    """
    # Import tardif, comme pour `dispatch_tool` : c'est ce qui laisse un
    # double de test remplacer `create_agent_node` avant la construction.
    from app.agent.nodes import create_agent_node

    _inner = create_agent_node()

    async def _agent(state: AgentState) -> dict:
        sortie = await _inner(state)
        if dernier_etat is not None:
            dernier_etat["messages"] = (
                list(state.get("messages") or ())
                + list((sortie or {}).get("messages") or ())
            )
            modele = (sortie or {}).get("model_used") or state.get("model_used")
            if modele:
                dernier_etat["model_used"] = modele
        return sortie

    return _agent


def _noeud_outils(
    mission_id: str, goal: str, budgets: _Budgets, journal: list[dict],
    dernier_etat: Optional[dict] = None,
):
    """Le nœud ``tools`` du passage.

    Il ne réimplémente PAS l'exécution : il délègue à
    ``missions.nodes.dispatch_tool``, la passerelle des missions, qui porte le
    gate du mandat, les disjoncteurs, le journal de bord et le filtre PII.
    L'import est fait à l'appel pour que le double de test soit vu.

    ``dernier_etat`` est le carnet de secours du COÛT (02/09/2026) : quand
    ``ainvoke`` lève — un 429 au tour suivant — le passage ne récupère AUCUN
    état, donc zéro token et un fournisseur « unknown ». Ce nœud, lui, a déjà
    vu l'état du tour précédent : messages porteurs d'``usage_metadata`` ET
    ``model_used``. On le recopie au passage, il ne coûte rien."""

    async def _outils(state: AgentState) -> dict:
        from app.agent.missions.nodes import dispatch_tool
        from app.agent.missions.pii import mission_filter

        if dernier_etat is not None:
            dernier_etat["messages"] = list(state.get("messages") or ())
            if state.get("model_used"):
                dernier_etat["model_used"] = state["model_used"]

        dernier = state["messages"][-1]
        user_id = state.get("user_id", "") or ""
        sorties: list[ToolMessage] = []
        mise_a_jour: dict = {}
        for appel in getattr(dernier, "tool_calls", None) or ():
            nom = appel.get("name") or ""
            args = appel.get("args") or {}
            cid = appel.get("id") or ""

            # L'arrêt d'urgence doit couper le passage EN COURS. Un passage
            # peut durer plusieurs minutes : attendre sa fin ferait d'un
            # bouton « Arrêter » une promesse à retardement.
            if await _statut(mission_id) not in _STATUTS_VIVANTS:
                raise MissionInterrompue(mission_id)

            raison = budgets.refus(_tokens_des_messages(state.get("messages")))
            if raison:
                logger.info("Mission %s : %s refusé — %s", mission_id, nom, raison)
                journal.append({"tool": nom, "ok": False, "refus": raison})
                sorties.append(ToolMessage(
                    content=_CONSIGNE_BUDGET.format(raison=raison),
                    tool_call_id=cid, name=nom,
                ))
                continue

            texte, ok = await dispatch_tool(
                nom, args, cid, user_id, user_request=goal, mission_id=mission_id,
            )
            budgets.actions += 1
            journal.append({"tool": nom, "ok": bool(ok)})
            # La base vit dans le monde RÉEL : la trace garde la valeur en
            # clair. C'est le message rendu AU MODÈLE qui est ré-anonymisé —
            # `dispatch_tool` rend du clair à dessein (`anonymize_results=
            # False`), parce que le chemin historique anonymisait à SA
            # frontière LLM. Ici la frontière, c'est ce nœud.
            await _tracer(mission_id, nom, args, str(texte), bool(ok))
            sorties.append(ToolMessage(
                content=mission_filter(mission_id).anonymize(
                    str(texte), ner_detection=False,
                ),
                tool_call_id=cid, name=nom,
            ))
            # `find_tool` est le filet de la sélection par familles : ce
            # qu'il découvre entre, avec sa famille, pour le reste de la
            # mission — et le tour suivant le voit déjà branché.
            if nom == "find_tool" and ok and state.get("mission_tools"):
                from app.agent.discovered_tools import get_discovered

                elargis = elargir(
                    mission_id, sorted(get_discovered(mission_id)), _catalogue_du_profil(),
                )
                if elargis:
                    mise_a_jour["mission_tools"] = elargis
        return {"messages": sorties, **mise_a_jour}

    return _outils


# ── Le graphe ────────────────────────────────────────────────────────────────


def build_mission_chat_graph(
    mission_id: str, goal: str, budgets: _Budgets, journal: list[dict],
    dernier_etat: Optional[dict] = None,
):
    """La topologie du chat, avec le nœud d'outils des missions.

    Les trois autres nœuds sont ceux du chat, importés tels quels : c'est tout
    l'intérêt du chantier — la mission n'a plus de moteur à elle. Le nœud de
    conformité reste : il confronte le résultat à la demande et relance avec
    les écarts nommés, ce qu'aucun tick de mission ne savait faire."""
    from app.agent.nodes import force_summary_node

    g = StateGraph(AgentState)
    g.add_node("agent", _agent_qui_se_photographie(dernier_etat))
    g.add_node("tools", _noeud_outils(
        mission_id, goal, budgets, journal, dernier_etat,
    ))
    g.add_node("force_summary", force_summary_node)
    g.add_node("verify", conformity_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "force_summary": "force_summary",
        "verify": "verify",
        "end": END,
    })
    g.add_conditional_edges("verify", route_after_conformity, {
        "agent": "agent", "end": END,
    })
    g.add_edge("tools", "agent")
    g.add_edge("force_summary", END)
    return g.compile()


# ── Carnet : la mémoire entre deux réveils ───────────────────────────────────


def _bloc_carnet(mission_id: str) -> str:
    """Le carnet formaté pour la tête de la consigne, chaîne vide s'il manque."""
    try:
        from app.services.mission_workspace import carnet_context_block

        return carnet_context_block(mission_id) or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mission %s : carnet illisible (%s)", mission_id, exc)
        return ""


def _preparer_carnet(mission: Any) -> None:
    """Crée le carnet s'il manque (idempotent).

    Le carnet n'est plus réservé aux missions sous mandat : c'est la mémoire
    de TOUTE mission qui tourne sur cette boucle. Sans lui, un passage qui
    reprend refait ce qui est déjà fait — le défaut mesuré le 28/08/2026, où
    la même recherche a été rejouée trois fois."""
    try:
        from app.services.mission_workspace import init_carnet

        mandat = None
        if getattr(mission, "mandate_json", None):
            try:
                from app.services.mission_spec import mandate_from_json

                mandat = mandate_from_json(mission.mandate_json)
            except Exception as exc:  # noqa: BLE001 — carnet sans le détail du mandat
                logger.debug("Mandat illisible pour le carnet : %s", exc)
        init_carnet(mission.id, mission.title or "", mission.goal or "", mandat)
    except Exception as exc:  # noqa: BLE001 — un disque plein ne tue pas une mission
        logger.warning("Mission %s : carnet indisponible (%s)", mission.id, exc)


# Les outils dont le RÉSULTAT est un état du monde à ne pas recréer : leur
# extrait survit toujours dans le carnet, même loin dans la trace. Le
# 03/09/2026, une reprise qui ne connaissait que des noms d'outils a recréé
# le tableur deux fois et conclu « historique inchangé » après l'avoir mis à
# jour.
_OUTILS_CREATEURS: tuple[str, ...] = ("_create", "_update", "_append", "_upload", "_write", "_send")
_EXTRAIT_MAX = 110


def _extraits_de_trace(steps: Any, *, recents: int = 15, maxi: int = 2500) -> str:
    """Les actions déjà jouées, avec un extrait de leur RÉSULTAT.

    Toutes les actions des outils créateurs (ce qui existe désormais), plus
    les ``recents`` dernières actions quelles qu'elles soient (où en était la
    lecture). Une ligne par action, coupée, le tout borné à ``maxi``
    caractères — c'est un rappel, pas une trace."""
    actes = [s for s in steps if getattr(s, "phase", "") == "act" and getattr(s, "tool_name", None)]
    if not actes:
        return ""
    retenus: list[int] = []
    for i, s in enumerate(actes):
        nom = str(s.tool_name)
        if i >= len(actes) - recents or any(m in nom for m in _OUTILS_CREATEURS):
            retenus.append(i)
    lignes: list[str] = []
    for i in retenus:
        s = actes[i]
        sortie = " ".join(str(getattr(s, "tool_output", "") or "").split())
        if len(sortie) > _EXTRAIT_MAX:
            sortie = sortie[:_EXTRAIT_MAX] + "…"
        lignes.append(f"- {s.tool_name} {'✓' if getattr(s, 'success', True) else '✗'} : {sortie}")
    texte = "\n".join(lignes)
    if len(texte) > maxi:
        texte = texte[: maxi - 1].rstrip() + "…"
    return texte


async def _amorcer_depuis_la_trace(mission_id: str) -> None:
    """Le jour du basculement, des missions tournent déjà sur l'ancien moteur.

    Leur carnet est vide — il n'était rempli que sous mandat actif — mais leur
    trace ne l'est pas. Sans cette amorce, le premier passage sur la boucle du
    chat repart du seul objectif et REFAIT ce qui est déjà fait : le dossier
    Drive recréé, le tableur recréé. C'est le défaut même que ce chantier
    corrige, qu'on réintroduirait à la migration.

    Écrit une seule fois : dès qu'un passage a été consigné, le carnet fait
    foi. Best-effort — une trace illisible ne bloque pas la mission.
    """
    try:
        from app.services.mission_workspace import carnet_append_section, read_carnet

        if "**Passage " in (read_carnet(mission_id) or ""):
            return
        steps = await mission_service.list_steps(mission_id)
        extraits = _extraits_de_trace(steps)
        if not extraits:
            return
        carnet_append_section(
            mission_id, "Passages",
            "**Passage 0 (reprise)** — actions déjà jouées, avec ce qu'elles "
            "ont rendu (ce qui a été créé existe : ne le recrée pas, relis-le) :\n"
            f"{extraits}\n"
            "Vérifie ce qui existe déjà avant de le refaire.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mission %s : amorce du carnet impossible (%s)", mission_id, exc)


def _numero_du_passage(mission_id: str) -> int:
    try:
        from app.services.mission_workspace import read_carnet

        return (read_carnet(mission_id) or "").count("**Passage ") + 1
    except Exception:  # noqa: BLE001
        return 1


def _ecrire_le_carnet(
    mission_id: str, journal: list[dict], bilan: str, a_suivre: bool,
    incident: Optional[str] = None,
) -> None:
    """La compaction du passage, en une ligne datée.

    « Actions accomplies au passé, état courant, ce qui bloque » : les actions
    viennent du journal (elles sont des FAITS), l'état et les blocages du
    bilan du modèle, à qui la consigne demande précisément ces trois choses.
    Aucun appel LLM de plus — le modèle a déjà écrit ce résumé pour finir.

    ``incident`` nomme la panne quand le passage a été coupé au milieu : la
    ligne existe QUAND MÊME, parce que les actions déjà jouées sont des faits
    et que le réveil suivant les rejouerait sans elle (02/09/2026)."""
    actions = ", ".join(
        f"{e['tool']} {'✓' if e.get('ok') else '✗'}" for e in journal
    ) or "aucune action"
    plat = " ".join((bilan or "").split())[:_BILAN_MAX] or "(pas de bilan écrit)"
    suite = (
        f" — INTERROMPU ({incident})" if incident
        else (" — À SUIVRE" if a_suivre else " — mission conclue")
    )
    try:
        from app.services.mission_workspace import carnet_append_section

        carnet_append_section(
            mission_id, "Passages",
            f"**Passage {_numero_du_passage(mission_id)}**{suite} — "
            f"actions : {actions}. Bilan : {plat}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mission %s : passage non consigné au carnet (%s)", mission_id, exc)


# ── Le prompt système : la frontière que ce module doit tenir ────────────────


async def _amorcer_la_memoire(
    mission_id: str, user_id: str, requete: str, filtre: Any,
) -> None:
    """Poser l'instantané mémoire DÉJÀ ANONYMISÉ, avant que le modèle le voie.

    Le prompt système n'est pas composé ici : ``agent_node`` le monte, et il
    y colle ``build_memory_snapshot`` — profil utilisateur, préférences,
    contraintes, souvenirs, interactions passées — qu'il envoie AU MODÈLE EN
    CLAIR. Rien de ce chemin ne passe par ``mission_filter``, alors que le
    tier COMPLEX est cloud par défaut (``zhipu``, ``anthropic``, ``gemini``).
    L'ancien chemin ne pouvait pas avoir ce trou : ``act_node`` composait son
    propre ``SystemMessage`` (gabarit fixe + plan + goal) et anonymisait tout.

    On ne touche pas ``agent_node`` : on lui SERT l'instantané. Il le lit par
    ``frozen_memory.get_or_build(conversation_id, …)``, et la conversation
    d'un passage EST la mission — on le pose donc d'avance, déjà anonymisé,
    et le constructeur en clair ne tourne jamais.

    Reposé à CHAQUE passage, et non une fois pour toutes : les placeholders
    doivent être ceux du filtre COURANT. Un instantané gelé la veille en
    porterait d'obsolètes, que le filtre d'aujourd'hui dé-anonymiserait vers
    la mauvaise valeur.

    Échoue FERMÉ sur la CONSTRUCTION : sans instantané utilisable on en pose
    un VIDE plutôt que d'en laisser bâtir un. Sur la POSE, non : la ligne du
    bas journalise et continue (02/09/2026). Ce n'est plus une fuite depuis
    que ``nodes.prompt_systeme_sortant`` tient la frontière d'ENVOI — un
    instantané non posé coûte du contexte et un rebuild, pas un secret. Ce
    module reste le chemin NORMAL : il fige les placeholders du filtre
    COURANT et garde le cache de prompt cohérent d'un passage à l'autre.

    ⚠️ CE QUI ÉTAIT OUVERT, et qui est fermé depuis le 02/09/2026 dans
    ``nodes.py`` : ``get_query_relevant_profile`` (rappel contextuel du
    profil), ``build_personal_vocabulary_block`` et la voie ``compact`` sont
    ajoutés au prompt HORS de tout cache. Ils partaient en clair, sur ce
    chemin comme sur le chat. ``prompt_systeme_sortant`` les rattrape à
    l'envoi, avec le filtre de CETTE mission — que ``run_mission_chat_passage``
    lui sert par ``nodes.FILTRE_PII_DU_TOUR``. Cette pose n'est pas un détail
    de plomberie : sans elle il ouvre un SECOND vault sur la même mission, et
    le MÊME ``[EMAIL_0]`` désigne alors deux personnes différentes dans le
    même prompt (mesuré le 02/09).
    """
    bloc = ""
    try:
        from app.agent.builders.memory_snapshot import build_memory_snapshot
        from app.services.memory_manager import get_memory_manager

        # `messages=[]` : un passage ouvre un fil neuf, et `agent_node`
        # sauterait de toute façon la reprise des interactions passées au
        # premier tour d'une conversation.
        instantane, _ = await build_memory_snapshot(
            messages=[], user_id=user_id, user_query=requete,
            memory=get_memory_manager(), use_compact=False,
        )
        bloc = filtre.anonymize(instantane or "", ner_detection=False)
    except Exception as exc:  # noqa: BLE001 — on pose du vide, pas du clair
        logger.warning(
            "Mission %s : instantané mémoire illisible (%s) — le prompt "
            "système partira sans mémoire", mission_id, exc,
        )
    try:
        from app.services import frozen_memory, system_prompt_cache

        frozen_memory.preseed(mission_id, bloc)
        # Le segment cacheable du prompt EMBARQUE l'instantané : un reste du
        # passage précédent porterait les placeholders d'un autre filtre.
        system_prompt_cache.invalidate(mission_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Mission %s : instantané mémoire NON posé (%s) — le prompt "
            "système va partir en clair", mission_id, exc,
        )


# ── La consigne du passage ───────────────────────────────────────────────────


def _consigne(goal: str, carnet: str) -> str:
    bloc = f"\n\n{carnet}\n" if carnet else "\n"
    return (
        "Tu exécutes une MISSION autonome. Personne n'est devant l'écran : "
        "tu agis, tu ne demandes pas.\n\n"
        f"── OBJECTIF DE LA MISSION ──\n{goal}\n"
        f"{bloc}"
        "\n── COMMENT TERMINER CE PASSAGE ──\n"
        "Enchaîne les outils dont tu as besoin, puis termine par une réponse "
        "en texte qui dit TROIS choses : ce que tu as FAIT dans ce passage "
        "(au passé, avec les noms et les valeurs), l'ÉTAT courant du "
        "livrable, et ce qui BLOQUE ou reste à faire. Ce texte est archivé "
        "dans le carnet ci-dessus et relu au prochain réveil : ce que tu n'y "
        "écris pas est perdu.\n"
        "S'il te reste du travail que tu ne peux pas finir maintenant, "
        f"termine ta réponse par {MARQUEUR_A_SUIVRE} — la mission sera "
        "réveillée pour continuer. Sinon la mission est close sur ta "
        "réponse.\n"
        "N'utilise JAMAIS « [SILENT] » : une mission rend toujours compte."
    )


# ── Lecture de la sortie ─────────────────────────────────────────────────────


def _dernier_texte(messages: Any) -> str:
    for m in reversed(list(messages or ())):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            texte = content_to_text(m.content).strip()
            if texte:
                return texte
    return ""


def _demande_un_autre_passage(texte: str) -> bool:
    return bool(_MARQUE.search(texte or ""))


def _sans_marqueur(texte: str) -> str:
    """Le marqueur est un signal de protocole : il ne doit apparaître ni dans
    le résumé livré à l'utilisateur ni dans le carnet."""
    return _MARQUE.sub("", texte or "").strip()


# ── Le coût du passage ───────────────────────────────────────────────────────


async def _journaliser_le_cout(
    mission_id: str, user_id: str, resultat: dict, depart: float,
) -> None:
    """Une ligne ``usage_logs`` par passage (02/09/2026).

    Sans elle, le coût LLM des missions n'existe NULLE PART : ni au tableau
    de bord, ni pour le garde-fou de budget quotidien que ``_process_one_mission``
    s'applique à lui-même juste avant d'appeler ce chemin. C'est le défaut
    que « Pre-launch fix #13 » avait déjà corrigé pour l'ancien moteur, et
    qu'un nouvel appelant réintroduit s'il ne journalise pas.

    Pourquoi pas ``_log_mission_llm_usage`` : son contrat exige l'OBJET LLM
    (il en tire fournisseur et modèle), que la boucle du chat ne voit jamais
    — le modèle est résolu à l'intérieur d'``agent_node``. ``record_turn_usage``
    lit ce que l'ÉTAT rapporte (``model_used`` + ``usage_metadata`` de chaque
    message) : c'est déjà le chemin des canaux et du planificateur, qui sont
    dans exactement la même situation.

    Sans ÉTAT, pas de ligne (02/09/2026). Un passage tué avant le premier
    retour du modèle n'a rien à déclarer : ``record_turn_usage`` écrivait
    quand même ``0 in / 0 out / provider='unknown' / model='unknown'``. Ce
    n'est pas une mesure à zéro, c'est une absence de mesure — et la
    ventilation par fournisseur du tableau de bord se remplissait de lignes
    « unknown ». L'état de secours du nœud d'outils couvre l'autre cas, celui
    qui a VRAIMENT dépensé avant de mourir.
    """
    if not (resultat or {}).get("messages"):
        logger.info(
            "Mission %s : passage sans état — aucune ligne d'usage à écrire",
            mission_id,
        )
        return
    try:
        from app.services.usage_instrumentation import record_turn_usage

        await record_turn_usage(
            user_id=user_id,
            # La mission tient lieu de conversation, ici comme dans l'état.
            conversation_id=mission_id,
            channel="mission",
            result=resultat,
            started_at=depart,
            toolset_profile=_PROFIL_OUTILS,
            automated_task=True,
        )
    except Exception as exc:  # noqa: BLE001 — l'analytique ne casse pas un passage
        logger.warning("Mission %s : coût non journalisé (%s)", mission_id, exc)


# ── Le passage ───────────────────────────────────────────────────────────────


async def run_mission_chat_passage(
    mission_id: str, user_id: str, goal: str,
) -> dict:
    """UN réveil de la mission, joué sur la boucle du chat.

    Rend le même contrat que le graphe historique pour que le heartbeat n'ait
    rien à savoir du chemin pris : ``done`` + ``final_summary`` clôturent la
    mission, ``failed`` + ``failure_reason`` la font échouer, le reste
    programme le réveil suivant."""
    mission = await mission_service.get_mission(mission_id)
    if mission is None:
        return {"done": False, "failed": True, "failure_reason": "mission introuvable"}
    if (mission.status or "") not in _STATUTS_VIVANTS:
        # Pause ou arrêt d'urgence entre le dispatch et ici : on ne démarre pas.
        return {"done": False, "failed": False, "interrupted": True}

    try:
        await mission_service.mark_running(mission_id)
    except ValueError:
        pass  # déjà `running` — la transition n'est pas rejouable

    budgets = _Budgets(mission)
    journal: list[dict] = []
    # Frontière de souveraineté — invariant du chemin missions : la base et
    # l'utilisateur vivent dans le monde RÉEL, seul le LLM vit dans le monde
    # des placeholders. Le nœud agent du chat n'anonymise pas de lui-même
    # (côté planificateur c'est l'appelant qui le fait) : c'est donc au
    # passage de tenir la frontière, à l'entrée comme à la sortie.
    from app.agent.missions.pii import deanonymize_any, mission_filter

    filtre = mission_filter(mission_id)
    _preparer_carnet(mission)
    # Les familles d'outils de la mission : choisies au premier passage,
    # relues ensuite — après le carnet, pour que la ligne « Outils » s'y
    # inscrive sous le squelette.
    outils_mission = await outillage_de_la_mission(
        mission_id, goal, _catalogue_du_profil(),
    )
    await _amorcer_depuis_la_trace(mission_id)
    # AVANT la consigne : le prompt système d'`agent_node` est l'autre moitié
    # de ce qui part au modèle, et c'est la moitié que ce module doit servir
    # lui-même pour qu'elle soit anonymisée.
    await _amorcer_la_memoire(mission_id, user_id, goal, filtre)
    consigne = filtre.anonymize(
        _consigne(goal, _bloc_carnet(mission_id)), ner_detection=False,
    )
    # L'état du dernier tour VU, pour le cas où `ainvoke` lève : le nœud
    # d'outils le recopie ici, le passage y retombe pour le coût.
    dernier_etat: dict = {}
    graphe = build_mission_chat_graph(
        mission_id, goal, budgets, journal, dernier_etat,
    )

    interrompu = False
    # Ce qui a tué le passage EN COURS, s'il a été tué. Le carnet doit être
    # écrit AUSSI sur ce chemin : `_process_one_mission` REPORTE le tick sur
    # une panne passagère (429, timeout, 504) au lieu de tuer la mission —
    # elle se réveille donc, et sans cette ligne elle rejouerait les actions
    # déjà faites, le défaut même que ce module existe pour corriger.
    plantage: Optional[BaseException] = None
    resultat: dict = {}
    depart = time.monotonic()
    # ── La frontière de souveraineté du prompt SYSTÈME (02/09/2026) ─────────
    #
    # `nodes.prompt_systeme_sortant` anonymise ce qui part vers un modèle non
    # local. Il lui faut le filtre de CETTE mission : sans cette pose, il se
    # rabattait sur `get_filter(conversation_id)` — un SECOND vault à côté de
    # `mission_filter()`, qui est `get_filter("mission:<id>")`.
    #
    # Mesuré sur un passage réel le 02/09 : `[EMAIL_0]` valait
    # « nom@domaine.tld » dans le vault d'ombre et l'adresse de Franck dans
    # celui de la mission. Le modèle lit les DEUX dans le même prompt, et
    # `deanonymize_any` — qui n'interroge que le filtre de la mission —
    # résout le placeholder d'ombre vers la MAUVAISE valeur, au carnet comme
    # dans le résumé rendu à l'utilisateur. Un `gmail_send_email(to=
    # "[EMAIL_0]")` partait au mauvais destinataire.
    #
    # Les ContextVars sont copiées à la création de chaque tâche asyncio :
    # posée ici, elle traverse LangGraph jusqu'au nœud agent.
    from app.agent.nodes import FILTRE_PII_DU_TOUR

    jeton_pii = FILTRE_PII_DU_TOUR.set(filtre)
    try:
        resultat = await graphe.ainvoke(
            {
                "messages": [HumanMessage(content=consigne)],
                "user_id": user_id,
                # La mission tient lieu de conversation — même convention que
                # `dispatch_tool`, qui pose déjà `CURRENT_CONVERSATION_ID` sur
                # l'identité de la mission.
                "conversation_id": mission_id,
                "automated_task": True,
                # Une mission tourne sur COMPLEX, jamais sur le tier image ni
                # sur une tête locale (#369 pour l'ancien moteur ; ici depuis
                # le 03/09/2026 — deux appels à 195 s et 227 s sur le Gemma
                # local pendant « test2 »).
                "tier_pin": "complex",
                # Le profil COLLANT du chat, valeur « tout le catalogue »
                # (#323). Sans lui, le nœud retombe sur le filtre de
                # mots-clés — celui qui ne connaît ni « convertis » ni
                # « transforme », et qui laissait 119 outils sur 206
                # injoignables. Une mission ne peut pas se permettre de
                # découvrir en cours de route qu'elle n'a pas l'outil : elle
                # n'a personne à qui le dire.
                "toolset_profile": _PROFIL_OUTILS,
                "mission_tools": list(outils_mission or ()),
                "iteration_count": 0,
                "conformity_retries": 0,
                "conformity_gap_count": 0,
            },
            config={"recursion_limit": CHAT_RECURSION_LIMIT},
        )
    except MissionInterrompue:
        logger.info("Mission %s : passage interrompu (mission plus en cours)", mission_id)
        interrompu = True
    except asyncio.CancelledError:
        # 02/09/2026 — `CancelledError` dérive de `BaseException` depuis
        # Python 3.8 : le `except Exception` ci-dessous NE LA VOIT PAS. Le
        # heartbeat joue les passages en tâche de fond, et la boucle annule
        # les tâches en vol à l'arrêt du processus : un `docker compose up -d`
        # pendant un passage laissait le carnet muet sur des actions DÉJÀ
        # jouées, et le réveil suivant les rejouait — le défaut même que ce
        # module existe pour fermer.
        #
        # On écrit (l'écriture est synchrone, elle n'attend rien) puis on
        # RELÈVE : une annulation avalée ferait mentir l'annulation.
        logger.warning(
            "Mission %s : passage ANNULÉ — %d action(s) déjà jouée(s)",
            mission_id, len(journal),
        )
        _ecrire_le_carnet(mission_id, journal, "", True, incident="annulé")
        raise
    except Exception as exc:  # noqa: BLE001 — on consigne, puis on relève
        logger.warning(
            "Mission %s : passage coupé par %s: %s — %d action(s) déjà jouée(s)",
            mission_id, type(exc).__name__, exc, len(journal),
        )
        plantage = exc
    finally:
        FILTRE_PII_DU_TOUR.reset(jeton_pii)

    # Un passage tué en vol ne rend AUCUN état : on retombe sur le dernier vu
    # par le nœud d'outils, qui porte les `usage_metadata` déjà facturés et
    # le `model_used` du tour précédent. Sans ça, un 429 au second tour
    # effaçait le coût du premier — et la clause tokens du budget avec.
    etat = resultat or dernier_etat
    tokens = _tokens_des_messages(etat.get("messages"))
    if tokens:
        await mission_service.add_tokens_used(mission_id, tokens)
    await _journaliser_le_cout(mission_id, user_id, etat, depart)

    # Le BILAN, lui, ne vient QUE d'un passage qui a rendu son état : le
    # dernier texte d'un tour intermédiaire n'est pas une conclusion.
    messages = resultat.get("messages") or []

    texte = deanonymize_any(filtre, _dernier_texte(messages))
    bilan = _sans_marqueur(texte)

    if plantage is not None:
        _ecrire_le_carnet(
            mission_id, journal, bilan, True,
            incident=f"{type(plantage).__name__}: {plantage}"[:200],
        )
        # On RELÈVE : c'est l'exception qui dit au heartbeat s'il doit
        # reporter le tick (`_est_passagere`) ou faire échouer la mission.
        # L'avaler transformerait un 429 en passage silencieusement vide.
        raise plantage

    if interrompu:
        _ecrire_le_carnet(mission_id, journal, bilan or "passage interrompu", True)
        return {"done": False, "failed": False, "interrupted": True,
                "actions": len(journal)}

    # Un passage tronqué par le budget d'itérations du chat n'a pas conclu :
    # il a été coupé. On le réveille plutôt que de prendre son résumé forcé
    # pour une fin de mission.
    tronque = int(resultat.get("iteration_count") or 0) >= MAX_AGENT_ITERATIONS
    a_suivre = tronque or _demande_un_autre_passage(texte)
    _ecrire_le_carnet(mission_id, journal, bilan, a_suivre)

    logger.info(
        "Mission %s : passage terminé — %d action(s), %d tokens, à suivre=%s",
        mission_id, len(journal), tokens, a_suivre,
    )
    return {
        "done": not a_suivre,
        # `complete_mission` exige un résumé : un modèle qui conclut sans un
        # mot laisserait la mission tourner en boucle au heartbeat.
        "final_summary": (bilan or "Mission terminée sans texte de conclusion.")
        if not a_suivre else bilan or None,
        "failed": False,
        "failure_reason": None,
        "actions": len(journal),
    }


__all__ = [
    "MARQUEUR_A_SUIVRE",
    "MissionInterrompue",
    "build_mission_chat_graph",
    "run_mission_chat_passage",
]
