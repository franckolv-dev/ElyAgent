# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/transparency.py
# @brief      Ce qu'Ely a le droit de faire, et ce qui quitte la machine.
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
"""Deux surfaces de transparence — audit du 02/09/2026.

Ely applique déjà les deux garanties ; aucune des deux ne se VOYAIT.

``GET /api/me/transparency/contract`` — le contrat visible
    « Qu'est-ce qu'Ely a le droit de faire, là, maintenant, pour moi ? »
    La donnée existait, éparpillée sur quatre modules : la nature des outils
    (``agent/tool_nature``), le régime d'approbation que la passerelle
    appliquerait (``capability_manifest``, la source que
    ``tool_gateway._decide_hitl`` consulte vraiment), la préférence de
    l'utilisateur (``services/hitl_preferences``), ce qui est annulable
    (``capability_manifest`` + ``compensation_registry``) et les mandats de
    mission actifs. Quatre pages à ouvrir pour une question, donc une
    question que personne ne posait.

``GET /api/me/transparency/egress`` — le registre de sortie
    « Aujourd'hui, qu'est-ce qui est sorti de ma machine, et vers qui ? »

⚠️ CE QUE CE MODULE NE DIT PAS, ET POURQUOI IL LE DIT
------------------------------------------------------
Ely masque la PII avant les appels de modèle des chemins de CONVERSATION.
``usage_logs`` ne garde AUCUNE trace du fait qu'une valeur ait été
effectivement remplacée pendant un tour : le coffre de substitution vit dans
le ``SecurityFilter`` de la conversation, il n'est jamais persisté (c'est
d'ailleurs voulu — le journaliser reviendrait à écrire la PII à côté de son
masque).

La page annonce donc la RÈGLE, les chemins où elle est VÉRIFIÉE, ceux qui y
échappent, et déclare la mesure absente. Un compteur « 12 données masquées »
inventé ici détruirait la seule chose qu'une page de transparence apporte.
Le dépôt a exactement cette discipline ailleurs : un coût estimé s'affiche
comme estimé.

⚠️ RÈGLE DE CE FICHIER (relecture du 02/09/2026, second tour)
--------------------------------------------------------------
Une page de transparence qui affirme plus que ce que le code tient est PIRE
que pas de page : elle rassure à tort. Chaque champ rendu ici doit donc être
dérivé de la source que le RUNTIME consulte — jamais d'une liste voisine qui
« dit la même chose ». Cinq écarts avaient été mesurés par ce seul chemin :
un régime d'approbation lu dans la mauvaise table, un filtre de mandats sur
un statut inexistant, un booléen de masquage codé en dur, un compte
d'annulables muet sur son drapeau, et deux échantillons sans leur plafond.

⚠️ BORNES
---------
``usage_logs`` fait 11 280 lignes en production et ne fait que grossir. Toute
lecture est filtrée sur ``user_id`` ET sur une fenêtre de dates plafonnée
(``_MAX_WINDOW_DAYS``), et ventilée PAR DATE — leçon écrite du projet. Les
compteurs d'outils, eux, se lisent en mémoire : ``TOOL_NATURE`` est une
constante, pas une table.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────
# Page 1 — le contrat visible
# ─────────────────────────────────────────────────────────────────────────

# Une famille sous ce seuil n'en est pas une : 21 préfixes ne portent qu'un
# seul outil (``ssh_``, ``telegram_``, ``weather_``…). Leur faire une carte
# chacun noierait les vraies familles — Gmail en porte 22, le navigateur 23.
# Ils sont regroupés sous « divers », et RESTENT listés nommément : le but
# est de grouper pour lire, jamais de cacher.
_FAMILLE_MIN = 2
_FAMILLE_DIVERS = "divers"


def _famille(tool_name: str) -> str:
    """Le préfixe avant le premier ``_`` — c'est ainsi que le catalogue est
    nommé (``gmail_*``, ``drive_*``, ``browser_tab_*``)."""
    return tool_name.split("_", 1)[0] if "_" in tool_name else tool_name


def _familles_reelles() -> dict[str, str]:
    """Nom d'outil → famille d'affichage, les singletons repliés sur « divers »."""
    from app.agent.tool_nature import TOOL_NATURE

    tailles = Counter(_famille(name) for name in TOOL_NATURE)
    return {
        name: (
            _famille(name)
            if tailles[_famille(name)] >= _FAMILLE_MIN
            else _FAMILLE_DIVERS
        )
        for name in TOOL_NATURE
    }


def _approbation(tool_name: str) -> str:
    """Le régime que LA PASSERELLE appliquerait — pas celui qu'on aimerait.

    ⚠️ CE QUE ÇA CORRIGE (relecture du 02/09/2026). Cette fonction dérivait
    « accord systématique » de ``tool_nature.ALREADY_GUARDED``, l'union de
    ``LOCKED_HITL_TOOLS`` et ``ALWAYS_CRITICAL_TOOLS``. Or
    ``tool_gateway._decide_hitl`` ne consulte NI cette union NI l'effet
    ``ENGAGEANT`` de la table : depuis que ``trust_substrate_enabled`` vaut
    True par défaut, sa décision de base est ``manifest_requires_hitl``,
    c'est-à-dire le MANIFESTE de capacité. Mesuré sur le catalogue complet :
    **12 outils** s'affichaient « la garde les retient quoi qu'il arrive »
    (``notes_delete``, ``sheets_delete_rows``, ``mcp_connect``,
    ``trainer_start``, ``save_constraint``…) alors que le manifeste les laisse
    en ``risk_based`` — une confirmation qui dépend des arguments, pas une
    garantie. Sur une page de transparence, promettre une garde qui n'existe
    pas est le défaut le plus cher : l'utilisateur agit en confiance.

    Trois régimes, ceux du manifeste, parce que ce sont ceux qui s'appliquent :

      ``always``     confirmation quels que soient les arguments ;
      ``risk_based`` confirmation SI l'analyse de risque le dit
                     (``security_filter.is_critical`` sur la description de
                     l'appel) — donc elle arrive parfois, et on ne promet pas
                     qu'elle arrive toujours ;
      ``never``      lecture sûre, jamais de confirmation.

    ⚠️ ``tool_nature.APPROVAL_WAIVED`` n'entre plus ici. C'est une décision
    ÉCRITE (les dix dispenses du 28/07) que le runtime n'applique pas :
    ``requires_approval`` n'est appelée nulle part dans ``app/``. L'afficher
    comme un régime laissait croire à une politique appliquée. Les dispenses
    réellement exécutées par la passerelle sont ailleurs, cf.
    ``_dispenses_d_instance``.
    """
    from app.services.capability_manifest import get_manifest

    return get_manifest(tool_name).approval.value


def _dispenses_d_instance() -> dict[str, dict[str, Any]]:
    """Les contournements de la garde CODÉS EN DUR dans la passerelle.

    « Accord systématique » n'est jamais absolu, et une aide qui dit « la
    garde les retient quoi qu'il arrive » ment sur trois mécanismes (audit du
    02/09/2026) :

    1. la préférence de l'utilisateur, qui dispense AUSSI les outils dangereux
       depuis le 19/06/2026 — la page la montre déjà, colonne par colonne
       (``user_preference`` / ``waivable``) ;
    2. l'auto-approbation des mails adressés à SOI-MÊME
       (``tool_gateway._SELF_MAIL_TOOLS``) : trois outils d'envoi perdent leur
       confirmation quand le destinataire est une adresse de l'utilisateur ;
    3. les outils MCP qui se gardent eux-mêmes
       (``tool_gateway._MCP_SELF_GATING_TOOLS``) : la passerelle y pose
       ``needs_hitl = False`` SANS condition, y compris pour ``mcp_connect``
       qui est pourtant dans ``LOCKED_HITL_TOOLS``.

    Les deux dernières sont des dispenses d'instance, même codées en dur : la
    page doit les nommer à côté du régime, sinon elle promet une garde que
    l'utilisateur n'a pas. On DÉRIVE des ensembles de la passerelle plutôt que
    de les recopier — une liste recopiée dérive en silence.

    ⚠️ Non listée ici parce qu'elle n'est ni permanente ni par outil :
    l'approbation « pour cette tâche » (``services/task_approvals``), éphémère
    et limitée aux outils dispensables (``is_hitl_waivable``), déjà rendue par
    la colonne ``waivable``.
    """
    from app.services.tool_gateway import (
        _MCP_SELF_GATING_TOOLS,
        _SELF_MAIL_TOOLS,
    )

    dispenses: dict[str, dict[str, Any]] = {
        nom: {
            "reason": "l'outil MCP se garde lui-meme (ACL par utilisateur + "
                      "confirmation interne) — la passerelle ne redemande rien",
            "conditional": False,
        }
        for nom in _MCP_SELF_GATING_TOOLS
    }
    for nom in _SELF_MAIL_TOOLS:
        dispenses[nom] = {
            "reason": "envoi a SA PROPRE adresse : la confirmation saute quand "
                      "le destinataire est l'utilisateur (digest de 6 h)",
            "conditional": True,
        }
    return dispenses


def _compensation(tool_name: str) -> str | None:
    """Le nom de la compensation SI elle est réellement exécutable.

    Le manifeste ne porte qu'une référence ; c'est le registre qui décide si
    elle se rejoue. Annoncer « annulable » sur une référence orpheline serait
    la pire promesse de cette page.
    """
    from app.services.capability_manifest import get_manifest
    from app.services.compensation_registry import get_compensation

    try:
        ref = get_manifest(tool_name).compensation
    except Exception as exc:  # noqa: BLE001 — une page ne casse pas pour un manifeste
        logger.debug("manifeste illisible pour %s : %s", tool_name, exc)
        return None
    return ref if get_compensation(ref) is not None else None


async def _preferences_utilisateur(user_id: str) -> dict[str, bool]:
    """Les préférences HITL écrites par CET utilisateur : outil → confirmation.

    Bornée par construction — une ligne par outil et par utilisateur
    (contrainte d'unicité ``uq_hitl_pref_user_tool``), donc au plus la taille
    du catalogue.
    """
    from app.models.hitl_preference import HitlPreference

    async with async_session() as db:
        rows = await db.execute(
            select(HitlPreference.tool_name, HitlPreference.requires_confirmation)
            .where(HitlPreference.user_id == user_id)
        )
        return {r.tool_name: bool(r.requires_confirmation) for r in rows.all()}


async def _mandats_actifs(user_id: str) -> list[dict[str, Any]]:
    """Les mandats des missions non terminées de l'utilisateur.

    Un mandat est le grant déclaratif le plus large qu'Ely puisse recevoir :
    il nomme les outils autorisés sans confirmation par tick. C'est donc la
    première chose que « ce qu'Ely a le droit de faire MAINTENANT » doit
    montrer — et la raison pour laquelle la page ne se résume pas à la table.

    ⚠️ CE QUE ÇA CORRIGE (relecture du 02/09/2026). Le filtre énumérait
    ``("completed", "failed", "cancelled")`` à la main. ``cancelled`` N'EXISTE
    PAS dans ``MISSION_STATUSES`` ; le statut d'une mission tuée par
    l'utilisateur est ``aborted``, et il n'était pas exclu. La page annonçait
    donc, sous « mandats actifs », un pouvoir que l'utilisateur avait lui-même
    révoqué. On lit désormais la constante — une liste recopiée à la main
    diverge le jour où un statut s'ajoute, et ici la divergence RASSURE À
    TORT.
    """
    from app.models.mission import MISSION_TERMINAL_STATUSES, Mission
    from app.services.mission_spec import mandate_from_json

    async with async_session() as db:
        rows = await db.execute(
            select(Mission)
            .where(
                Mission.user_id == user_id,
                Mission.mandate_json.isnot(None),
                Mission.status.notin_(sorted(MISSION_TERMINAL_STATUSES)),
            )
            .order_by(Mission.created_at.desc())
            .limit(20)
        )
        missions = rows.scalars().all()

    out: list[dict[str, Any]] = []
    for m in missions:
        try:
            mandate = mandate_from_json(m.mandate_json or "")
        except Exception as exc:  # noqa: BLE001 — un mandat illisible se signale
            logger.warning("mandat illisible sur la mission %s : %s", m.id, exc)
            out.append({
                "mission_id": m.id, "title": m.title, "status": m.status,
                "autonomy_state": m.autonomy_state, "unreadable": True,
                "tools_allow": [], "autonomy": None, "on_unforeseen": None,
                "llm_tier": None, "budgets": {},
            })
            continue
        out.append({
            "mission_id": m.id,
            "title": m.title,
            "status": m.status,
            "autonomy_state": m.autonomy_state,
            "unreadable": False,
            "autonomy": mandate.autonomy,
            "on_unforeseen": mandate.on_unforeseen,
            "llm_tier": mandate.llm_tier,
            "tools_allow": list(mandate.tools_allow),
            "budgets": {
                "daily_tool_actions_notify": mandate.budgets.daily_tool_actions_notify,
                "daily_llm_calls_notify": mandate.budgets.daily_llm_calls_notify,
            },
        })
    return out


@router.get("/api/me/transparency/contract")
async def visible_contract(current_user: User = Depends(get_current_user)) -> dict:
    """Le contrat, groupé par famille, compté avant d'être détaillé.

    211 lignes brutes ne répondent pas à « qu'a-t-elle le droit de faire » —
    c'est un annuaire. Le résumé vient donc en premier, le détail derrière.

    Le périmètre est ``TOOL_NATURE`` (l'inventaire), mais le RÉGIME vient du
    manifeste (ce que la passerelle applique) : recopier un compteur ici le
    ferait dériver en silence le jour où un outil s'ajoute.
    """
    from app.agent.tool_nature import TOOL_NATURE, unguarded_engaging_tools
    from app.config import get_settings
    from app.services.hitl_preferences import is_hitl_waivable

    prefs = await _preferences_utilisateur(str(current_user.id))
    familles_de = _familles_reelles()
    dispenses_instance = _dispenses_d_instance()

    par_famille: dict[str, list[dict[str, Any]]] = defaultdict(list)
    effets = Counter()
    regimes = Counter()
    annulables = 0
    arbitres = 0
    non_dispensables = 0
    dispenses_utilisateur = 0
    rearmes_utilisateur = 0
    dispenses_neutralisees: list[str] = []

    for name, nature in TOOL_NATURE.items():
        regime = _approbation(name)
        dispense = dispenses_instance.get(name)
        waivable = is_hitl_waivable(name)
        compensation = _compensation(name)
        pref = prefs.get(name)

        # Une dispense écrite en base ne vaut que si l'outil est dispensable :
        # ``user_requires_hitl`` neutralise les autres SANS migration, donc la
        # ligne survit en base tout en ne s'appliquant plus. Le taire ferait
        # croire l'utilisateur découvert alors qu'il est protégé.
        preference = None if pref is None else ("rearmed" if pref else "waived")
        preference_effective = preference is not None and (waivable or pref)
        if preference == "waived":
            if waivable:
                dispenses_utilisateur += 1
            else:
                dispenses_neutralisees.append(name)
        elif preference == "rearmed":
            rearmes_utilisateur += 1

        effets[nature.effect] += 1
        regimes[regime] += 1
        annulables += 1 if compensation else 0
        arbitres += 1 if nature.arbitrates else 0
        non_dispensables += 0 if waivable else 1

        par_famille[familles_de[name]].append({
            "name": name,
            "effect": nature.effect,
            "arbitrates": nature.arbitrates,
            "approval": regime,
            # Nommé à côté du régime : « accord systématique » n'est jamais
            # absolu tant qu'une dispense codée en dur le coupe.
            "waiver_reason": None if dispense is None else dispense["reason"],
            "waiver_conditional": bool(dispense and dispense["conditional"]),
            "waivable": waivable,
            "revertible": compensation is not None,
            "compensation": compensation,
            "user_preference": preference,
            "user_preference_effective": preference_effective,
        })

    familles = [
        {
            "family": nom,
            "tools": len(items),
            "by_effect": dict(Counter(i["effect"] for i in items)),
            "approval_always": sum(1 for i in items if i["approval"] == "always"),
            "items": sorted(items, key=lambda i: i["name"]),
        }
        # « divers » ferme la marche : c'est le fourre-tout, pas une famille.
        for nom, items in sorted(
            par_famille.items(),
            key=lambda kv: (kv[0] == _FAMILLE_DIVERS, -len(kv[1]), kv[0]),
        )
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "tools": len(TOOL_NATURE),
            "by_effect": dict(effets),
            "approval_always": regimes["always"],
            "approval_risk_based": regimes["risk_based"],
            "approval_never": regimes["never"],
            "approval_waived_by_instance": sum(
                1 for n in TOOL_NATURE if n in dispenses_instance
            ),
            "arbitrating": arbitres,
            "revertible": annulables,
            # ⚠️ Le compte des annulables N'EST PAS un compte d'annulables
            # (relecture du 02/09/2026). ``reversible_journal_enabled`` est
            # OFF par défaut : drapeau éteint, ``tool_gateway`` n'appelle
            # jamais ``record_reversible``, donc RIEN n'est enregistré et
            # rien n'est réellement annulable. Le compte reste (il dit ce
            # qui EST outillé), le drapeau l'accompagne pour que la page
            # puisse dire « annulables en principe, mais rien n'est
            # enregistré sur cette instance ».
            "revertible_journal_enabled": bool(
                getattr(get_settings(), "reversible_journal_enabled", False)
            ),
            "never_waivable": non_dispensables,
            "waived_by_user": dispenses_utilisateur,
            "rearmed_by_user": rearmes_utilisateur,
            "neutralized_user_waivers": sorted(dispenses_neutralisees),
            # Doit rester vide : ce qu'elle rapporterait serait une régression,
            # pas un état de fait (cf. tool_nature, lot 3).
            #
            # ⚠️ Ce champ mesure la POLITIQUE ÉCRITE (tool_nature : garde
            # déclarée ∪ dispenses écrites), pas le régime que la passerelle
            # applique — lequel vit dans ``approval`` ci-dessus. Les deux
            # répondent à deux questions différentes et ne doivent pas être
            # lus l'un pour l'autre : « aucun acte engageant n'a été oublié
            # au classement » n'est pas « tous sont confirmés à l'exécution ».
            "unguarded_engaging": unguarded_engaging_tools(),
        },
        # Les dispenses que la PASSERELLE exécute, pas celles qui sont
        # seulement écrites : ``tool_nature.APPROVAL_WAIVED`` remplissait ce
        # champ alors que ``requires_approval`` n'est appelée nulle part dans
        # ``app/``. Une dispense affichée mais non appliquée est une fausse
        # déclaration dans les deux sens.
        "instance_waivers": [
            {"tool": nom, "reason": d["reason"], "conditional": d["conditional"]}
            for nom, d in sorted(dispenses_instance.items())
        ],
        "families": familles,
        "mandates": await _mandats_actifs(str(current_user.id)),
    }


# ─────────────────────────────────────────────────────────────────────────
# Page 2 — le registre de sortie
# ─────────────────────────────────────────────────────────────────────────

# Fenêtre plafonnée : au-delà d'un trimestre, la page cesse de répondre à
# « aujourd'hui, qu'est-ce qui est sorti » et redevient de l'analytique.
_MAX_WINDOW_DAYS = 92
_DEFAULT_WINDOW_DAYS = 7

# Les fournisseurs servis PAR LA MACHINE. Étiquettes écrites par
# ``usage_instrumentation.split_model_used`` et ``llm_provider._provider_and_model``.
#
# ⚠️ Le critère n'est PAS le coût nul : ``gpt-5.6-terra`` coûte 0 au tarif
# déclaré (forfait ChatGPT) et sort pourtant chez OpenAI. Confondre les deux
# ferait afficher « resté sur la machine » sur un appel parti dans le nuage —
# exactement le mensonge que cette page existe pour empêcher.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"lm_studio", "ollama"})

# Un fournisseur non renseigné n'est pas un fournisseur local : il est
# INCONNU, et se compte à part. Le ranger en local par défaut flatterait le
# chiffre qu'on cherche justement à mesurer.
_UNKNOWN_PROVIDERS: frozenset[str] = frozenset({"", "unknown"})

# Plafond d'échantillon pour la ventilation du contexte : elle vit en JSON
# dans la colonne, donc elle se parse en Python. On lit les tours les plus
# récents et on DIT sur combien on porte.
_COMPOSITION_SAMPLE = 200

# Assez pour lire, trop peu pour faire une liste à défiler sans fin.
_TOP_PURPOSES = 12


def _kind(provider: str | None) -> str:
    """local | cloud | unknown — trois réponses, jamais deux."""
    name = (provider or "").strip().lower()
    if name in _UNKNOWN_PROVIDERS:
        return "unknown"
    return "local" if name in _LOCAL_PROVIDERS else "cloud"


async def _composition(user_id: str, since: datetime) -> dict[str, Any]:
    """De quoi est fait ce qui est parti dans le nuage, sur un échantillon.

    ``context_breakdown`` (migration 0025) est NULL quand le tour n'avait rien
    à ventiler — « une colonne vide vaut mieux qu'un JSON vide qui donnerait
    l'illusion d'une mesure ». On compte donc les appels réellement
    échantillonnés et on le rend, pour qu'un pourcentage tiré de trois tours
    ne passe pas pour la vérité de la fenêtre.

    ⚠️ CE QUE ÇA CORRIGE (relecture du 02/09/2026). Le plafond était appliqué
    AVANT le filtre « nuage » : sur une instance qui tourne surtout en local,
    les 200 tours les plus récents pouvaient être locaux, ``sampled_calls``
    tombait à 0 et la page imprimait une phrase catégorique sur ce qui sort
    alors que des appels nuage ventilés existaient bel et bien dans la
    fenêtre. Le critère descend donc DANS la requête — le plafond porte
    maintenant sur ce qu'on veut compter.

    ``NOT IN`` exclut naturellement les lignes à ``provider`` NULL (une
    comparaison à NULL n'est jamais vraie), ce qui est exactement le
    comportement de ``_kind`` : un fournisseur non renseigné est INCONNU, il
    ne se compte pas comme sorti. Le test Python reste en aval : deux
    formulations du même critère qui divergeraient se verraient là.
    """
    from app.models.usage_log import UsageLog

    hors_nuage = sorted(_LOCAL_PROVIDERS | _UNKNOWN_PROVIDERS)
    async with async_session() as db:
        rows = await db.execute(
            select(UsageLog.context_breakdown, UsageLog.provider)
            .where(
                UsageLog.user_id == user_id,
                UsageLog.timestamp >= since,
                UsageLog.context_breakdown.isnot(None),
                func.lower(func.trim(UsageLog.provider)).notin_(hors_nuage),
            )
            .order_by(UsageLog.timestamp.desc())
            .limit(_COMPOSITION_SAMPLE)
        )
        echantillon = rows.all()

    parts: Counter[str] = Counter()
    retenus = 0
    for breakdown, provider in echantillon:
        if _kind(provider) != "cloud":
            continue
        try:
            payload = json.loads(breakdown)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        retenus += 1
        for key, value in payload.items():
            # `total` et `pct` sont des méta, pas des catégories.
            if key in ("total", "pct") or not isinstance(value, (int, float)):
                continue
            parts[key] += int(value)

    total = sum(parts.values())
    return {
        "sampled_calls": retenus,
        "sample_cap": _COMPOSITION_SAMPLE,
        "categories": [
            {
                "key": key,
                "tokens": tokens,
                "share": round(tokens / total * 100, 1) if total else 0.0,
            }
            for key, tokens in parts.most_common()
        ],
    }


# Les chemins où l'anonymisation avant appel de modèle est VÉRIFIABLE : un
# ``SecurityFilter.anonymize`` se lit sur chacun, à la frontière du modèle.
#
# ⚠️ Cette liste ne dit pas « partout ». Elle dit « ici », et ``_MASQUAGE_ABSENT``
# dit « pas là ». C'est la différence entre une page de transparence et une
# affiche.
_MASQUAGE_APPLIQUE: tuple[tuple[str, str], ...] = (
    ("chat", "routers/chat.py — message courant et historique relus"),
    ("voix", "routers/voice.py — idem, corrigé le 10/06/2026"),
    ("missions", "agent/missions/pii.py — anonymize_messages à chaque appel"),
    ("planificateur", "services/scheduler.py — le prompt de la tâche"),
    ("resultats d'outils", "services/tool_gateway.py — re-anonymises avant retour au modele"),
)

# ⚠️ CE QUE ÇA CORRIGE (relecture du 02/09/2026). Le champ était un booléen
# codé en dur à True : « le masquage est appliqué avant TOUT appel de modèle ».
# Deux chemins envoient du texte BRUT, tous deux vérifiés en relisant le code :
#   - la génération du titre d'une conversation
#     (``routers/chat._generate_conversation_title``) passe ``user_text`` et
#     ``assistant_text`` tels quels dans son prompt ;
#   - la corvée de consolidation de fin de conversation
#     (``routers/chat._consolidate_conversation_memory``) relit les 30 derniers
#     ``Message.content`` en base et les concatène dans trois prompts.
# Les deux visent le tier MAINTENANCE, souvent local — mais « souvent » n'est
# pas « toujours », et c'est justement la question à laquelle cette page
# répond. HORS PÉRIMÈTRE de ce lot : on ne code pas leur anonymisation ici, on
# arrête de prétendre qu'elle existe. Suite à instruire séparément.
_MASQUAGE_ABSENT: tuple[dict[str, str], ...] = (
    {
        "path": "routers/chat._generate_conversation_title",
        "what": "le titre d'une conversation est genere a partir du texte BRUT "
                "du premier echange",
    },
    {
        "path": "routers/chat._consolidate_conversation_memory",
        "what": "la consolidation de fin de conversation relit les messages en "
                "base et les envoie BRUTS (resume, faits, preferences)",
    },
)


def _masquage() -> dict[str, Any]:
    """La règle appliquée avant l'envoi — et l'aveu de ce qui y échappe."""
    from app.services.security_filter import _PATTERNS

    try:
        from app.services.pii_ner import pii_ner_enabled

        ner = bool(pii_ner_enabled())
    except Exception as exc:  # noqa: BLE001 — l'ignorance se déclare, elle ne plante pas
        logger.debug("état du NER indisponible : %s", exc)
        ner = False

    return {
        "applied_on": [{"path": nom, "what": detail}
                       for nom, detail in _MASQUAGE_APPLIQUE],
        "not_applied_on": [dict(entry) for entry in _MASQUAGE_ABSENT],
        "regex_categories": sorted(_PATTERNS),
        "ner_enabled": ner,
        # ⚠️ LE point d'honnêteté de cette page : rien en base ne dit qu'une
        # valeur a été remplacée pendant CE tour. Le coffre de substitution
        # vit dans le SecurityFilter de la conversation et n'est jamais
        # persisté — le journaliser écrirait la PII à côté de son masque.
        "substitutions_measured": False,
    }


@router.get("/api/me/transparency/egress")
async def egress_registry(
    days: int = Query(
        _DEFAULT_WINDOW_DAYS,
        ge=1,
        le=_MAX_WINDOW_DAYS,
        description="Fenêtre en jours. Plafonnée — la table ne fait que grossir.",
    ),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ce qui est sorti de la machine sur la fenêtre, et vers qui.

    Quatre agrégations, toutes filtrées sur ``user_id`` ET ``timestamp`` (dans
    cet ordre — c'est l'index ``ix_usage_logs_user_timestamp``), plus un
    échantillon pour la composition. Aucune ne balaie l'historique.
    """
    from app.models.usage_log import UsageLog

    user_id = str(current_user.id)
    aujourdhui = datetime.now(timezone.utc).date()
    premier_jour = aujourdhui - timedelta(days=days - 1)
    # ⚠️ La borne est le PREMIER INSTANT du premier jour affiché, pas « il y a
    # N fois 24 heures ». Une borne glissante attrape la fin de la veille : ces
    # appels entraient dans les totaux sans avoir de barre où se poser, et le
    # total contredisait la frise. Sur une page de transparence, deux chiffres
    # qui se contredisent coûtent plus cher que le chiffre manquant.
    since = datetime.combine(premier_jour, time.min, tzinfo=timezone.utc)
    borne = (UsageLog.user_id == user_id, UsageLog.timestamp >= since)

    async with async_session() as db:
        par_jour = (await db.execute(
            select(
                func.date(UsageLog.timestamp).label("day"),
                UsageLog.provider,
                func.count(UsageLog.id).label("calls"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("tin"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("tout"),
            ).where(*borne).group_by("day", UsageLog.provider)
        )).all()

        par_destination = (await db.execute(
            select(
                UsageLog.provider,
                UsageLog.model,
                func.count(UsageLog.id).label("calls"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("tin"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("tout"),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0).label("cost"),
            ).where(*borne).group_by(UsageLog.provider, UsageLog.model)
        )).all()

        par_usage = (await db.execute(
            select(
                UsageLog.skill_used,
                func.count(UsageLog.id).label("calls"),
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("tin"),
            ).where(*borne).group_by(UsageLog.skill_used)
            .order_by(func.count(UsageLog.id).desc()).limit(_TOP_PURPOSES)
        )).all()

        par_canal = (await db.execute(
            select(UsageLog.channel, func.count(UsageLog.id).label("calls"))
            .where(*borne).group_by(UsageLog.channel)
            .order_by(func.count(UsageLog.id).desc())
        )).all()

    # ── Ventilation par DATE, avec les jours vides remplis ───────────────
    # Un jour sans appel est une information ; l'omettre laisserait croire à
    # une frise continue là où il y a un trou.
    jours: dict[str, dict[str, int]] = {
        (premier_jour + timedelta(days=i)).isoformat(): {
            "local": 0, "cloud": 0, "unknown": 0,
            "input_tokens": 0, "output_tokens": 0,
        }
        for i in range(days)
    }
    for row in par_jour:
        cle = str(row.day)
        seau = jours.get(cle)
        # Depuis que la borne tombe à minuit, le seul cas restant est une ligne
        # DATÉE DANS LE FUTUR (horloge décalée). On ne lui invente pas un jour.
        if seau is None:
            continue
        seau[_kind(row.provider)] += row.calls
        seau["input_tokens"] += row.tin or 0
        seau["output_tokens"] += row.tout or 0

    # ── Destinations : un fournisseur, ses modèles ───────────────────────
    fusion: dict[str, dict[str, Any]] = {}
    for row in par_destination:
        nom = (row.provider or "unknown").strip() or "unknown"
        dest = fusion.setdefault(nom, {
            "provider": nom, "kind": _kind(nom), "models": [],
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        if row.model and row.model not in dest["models"]:
            dest["models"].append(row.model)
        dest["calls"] += row.calls
        dest["input_tokens"] += row.tin or 0
        dest["output_tokens"] += row.tout or 0
        dest["cost_usd"] += row.cost or 0.0

    destinations = sorted(fusion.values(), key=lambda d: -d["calls"])
    for dest in destinations:
        dest["cost_usd"] = round(dest["cost_usd"], 4)
        dest["models"].sort()

    totaux = {
        "calls": sum(d["calls"] for d in destinations),
        "local_calls": sum(d["calls"] for d in destinations if d["kind"] == "local"),
        "cloud_calls": sum(d["calls"] for d in destinations if d["kind"] == "cloud"),
        "unknown_calls": sum(d["calls"] for d in destinations if d["kind"] == "unknown"),
        "input_tokens": sum(d["input_tokens"] for d in destinations),
        "output_tokens": sum(d["output_tokens"] for d in destinations),
        "cost_usd": round(sum(d["cost_usd"] for d in destinations), 4),
    }

    return {
        "window_days": days,
        "max_window_days": _MAX_WINDOW_DAYS,
        "since": since.isoformat(),
        "totals": totaux,
        "by_day": [{"day": jour, **seau} for jour, seau in sorted(jours.items())],
        "destinations": destinations,
        "purposes": [
            {"skill": row.skill_used, "calls": row.calls, "input_tokens": row.tin or 0}
            for row in par_usage
        ],
        # ⚠️ La liste est TRONQUÉE aux douze premiers usages, et ne le disait
        # pas — alors que la section voisine annonce scrupuleusement la taille
        # de son échantillon (``composition.sample_cap``). Un plafond tu se lit
        # comme un inventaire complet : « voilà tout ce pour quoi elle appelle
        # un modèle ». Le rendre coûte un entier.
        "purposes_cap": _TOP_PURPOSES,
        "channels": [
            {"channel": row.channel or "unknown", "calls": row.calls}
            for row in par_canal
        ],
        "composition": await _composition(user_id, since),
        "masking": _masquage(),
    }
