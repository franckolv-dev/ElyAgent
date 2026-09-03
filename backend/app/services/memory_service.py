# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory_service.py
# @brief      User memory service — episodic fact extraction and profile consolidation
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""User memory service — episodic fact extraction and profile consolidation.

This service provides these async entry points:

    extract_and_store_facts()      — extraction d'un échange (chemin par tour,
                                     désormais réservé au drapeau de secours)
    extract_new_facts_for_user()   — extraction PAR LOT : un appel de modèle
                                     pour tout ce qui est nouveau
    extract_facts_for_all_users()  — passe quotidienne (APScheduler, 02:45)
    get_user_context()             — injects a user profile summary into system prompts
    consolidate_user_memory()      — nightly job: merges logs into UserProfile
    consolidate_all_users()        — called by APScheduler at 3 AM
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import async_session
from app.models.user_memory import UserMemoryLog, UserProfile
from app.services.background_tasks import spawn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt injection guard
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = re.compile(
    r'\b(ignore|oublie|forget|override|bypass|system\s+prompt|new\s+instruction|'
    r'tu\s+es\s+maintenant|act\s+as|pretend|jailbreak|disregard|instruc)\b',
    re.IGNORECASE,
)


def _is_safe_fact(fact: str) -> bool:
    """Reject facts that look like prompt injection attempts."""
    if len(fact) > 500:  # suspiciously long "fact"
        return False
    if _INJECTION_PATTERNS.search(fact):
        return False
    return True


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
Tu es un extracteur de faits silencieux. Analyse le ou les fils de conversation \
ci-dessous et extrait les faits importants sur l'utilisateur (préférences, projets, \
outils, contexte personnel, compétences, habitudes).

Chaque fil est introduit par une ligne « --- Fil n --- ». Deux fils sont deux sujets \
distincts : ne combine JAMAIS un élément d'un fil avec un élément d'un autre.

Réponds UNIQUEMENT avec un objet JSON de la forme :
{{
  "facts": [
    {{"fact": "L'utilisateur travaille sur un projet Python nommé ELY", "type": "context"}},
    {{"fact": "L'utilisateur préfère les réponses courtes", "type": "preference"}}
  ]
}}

Types valides : "preference", "context", "event", "skill", "personal"
Si aucun fait utile n'est détectable, réponds avec : {{"facts": []}}
N'invente aucun fait. N'extrait que ce qui est dit EXPLICITEMENT.
N'extrais JAMAIS l'état d'une tâche en cours (avancement, étape atteinte, « fait / à faire », statut d'une mission) : la mémoire retient qui est l'utilisateur, pas où en est le travail.
Certaines valeurs sont masquées ([EMAIL_0], [PHONE_1], …) : recopie le masque tel quel.

Fils :
{conversation}
"""

_CONSOLIDATION_PROMPT = """\
Tu es un synthétiseur de profil utilisateur. Voici les faits bruts récemment collectés \
sur un utilisateur, ainsi que son profil existant.

Nouveaux faits bruts :
{raw_facts}

Profil existant :
{existing_profile}

Consolide ces informations en un profil mis à jour. Pour chaque fait, génère une clé courte \
(snake_case, ex: main_project, preferred_language, expertise_level, timezone, work_schedule) \
et une valeur concise.

Réponds UNIQUEMENT avec un objet JSON :
{{
  "profile": [
    {{"key": "main_project", "value": "Agent IA personnel nommé ELY en Python/FastAPI", "confidence": 0.95}},
    {{"key": "preferred_language", "value": "français", "confidence": 1.0}}
  ]
}}

Règles :
- Utilise des clés stables et réutilisables (pas de clés trop spécifiques)
- Si un fait existant est contredit, baisse la confidence à 0.5 ou remplace la valeur
- N'invente pas de faits non présents dans les données brutes
- N'extrais JAMAIS l'état d'une tâche en cours (avancement, étape atteinte, « fait / à faire », statut d'une mission) : la mémoire retient qui est l'utilisateur, pas où en est le travail.
- Confidence entre 0.0 et 1.0
"""


# ---------------------------------------------------------------------------
# Quand extraire — une fois par TOUR, pas une fois par itération d'outils
# ---------------------------------------------------------------------------
#
# Le graphe boucle : ``add_edge("tools", "agent")``. Le nœud agent est donc
# ré-entré après chaque lot d'outils. Lancer l'extraction à chaque passage
# produisait 755 appels de modèle en 7 jours (74,5 % de TOUS les appels,
# contre 2,7 % pour le chat direct), sur un contenu quasi identique à chaque
# fois — jusqu'à 14 extractions dans la même minute, 33 % de doublons
# littéraux dans les faits stockés.
#
# Une réponse termine le tour quand elle ne porte PAS de ``tool_calls`` :
# c'est la seule dont le graphe ne revient pas. Bonus non recherché mais
# réel : à ce moment-là ``messages`` contient tout l'échange, résultats
# d'outils compris — l'extraction voit donc PLUS que n'importe quel
# instantané pris au milieu de la boucle.


def should_extract_facts(response) -> bool:
    """True si ``response`` termine le tour et mérite donc une extraction.

    Args:
        response: la réponse du modèle (``AIMessage``), ou ``None``.

    Returns:
        False si la réponse porte des ``tool_calls`` (le graphe va repasser
        par ``tools`` et revenir ici), False si elle est absente, True sinon.
    """
    if response is None:
        return False
    return not getattr(response, "tool_calls", None)


# ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : la fin d'un tour payait un appel de
# modèle. Sur 30 jours glissants, l'extraction pesait 336 appels contre 208
# demandes web réelles — le travail de fond coûtait plus cher que le travail
# demandé, et l'extraction en était le premier poste. Chaque tour relançait
# le modèle sur une conversation qui n'avait bougé que d'un échange.
#
# L'extraction est désormais GROUPÉE : une passe quotidienne
# (``extract_facts_for_all_users``, 02:45, juste avant la consolidation)
# émet UN appel par utilisateur pour tout ce qui est nouveau. Un utilisateur
# qui fait 20 tours dans sa journée coûte 1 appel au lieu de 20.
#
# La fin d'un tour ne marque rien : ce serait de l'état à tenir à jour pour
# rien. La borne « depuis quand » se dérive de la base — voir
# ``_last_extraction_at``.
def _per_turn_extraction_enabled() -> bool:
    """Porte de sortie : ``MEMORY_EXTRACTION_PER_TURN=true`` rétablit l'ancien
    comportement (une extraction par tour, en tâche de fond).

    À n'activer que si la passe quotidienne se révélait manquer des faits en
    production — elle relit les messages persistés, pas les résultats d'outils
    de la boucle, qui eux ne sont pas stockés.
    """
    return os.getenv("MEMORY_EXTRACTION_PER_TURN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def maybe_spawn_fact_extraction(user_id: str, messages: list, response) -> bool:
    """Point de fin de tour. **Ne coûte plus rien par défaut.**

    Appelé par les deux nœuds qui peuvent clore un tour : ``agent_node`` (cas
    normal) et ``force_summary_node`` (budget d'itérations épuisé — là,
    TOUTES les réponses du nœud agent portent des ``tool_calls``, donc sans
    ce second point d'appel le tour n'aurait aucune extraction du tout).

    Ne lève jamais : c'est une corvée de fond, elle ne doit pas faire tomber
    le tour de l'utilisateur.

    Returns:
        True seulement si le drapeau de secours a effectivement fait partir
        une extraction ; False dans le fonctionnement normal, où c'est la
        passe quotidienne qui s'en charge.
    """
    if not user_id or not should_extract_facts(response):
        return False
    if not _per_turn_extraction_enabled():
        return False

    async def _safe_extract() -> None:
        try:
            await extract_and_store_facts(user_id, "", list(messages) + [response])
        except Exception as exc:  # noqa: BLE001
            logger.debug("Memory extraction failed: %s", exc)

    try:
        spawn(_safe_extract(), label="memory_extraction")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Memory extraction could not be scheduled: %s", exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

# Bornes du prompt d'extraction. Historiques, mesurées : les N derniers
# messages, chacun tronqué à 500 caractères.
_EXTRACTION_MESSAGE_WINDOW = 10
_EXTRACTION_CHAR_CAP = 500

# Même forme de borne pour le lot quotidien — les N derniers messages,
# tronqués à 500 caractères — seul N change, parce que la fenêtre est une
# JOURNÉE et non un tour. 6 × 10 = 60 messages, soit ~30 tours : au-delà on
# garde les plus RÉCENTS, un utilisateur bavard ne peut pas faire enfler le
# prompt indéfiniment.
_DAILY_EXTRACTION_MESSAGE_WINDOW = 6 * _EXTRACTION_MESSAGE_WINDOW


async def extract_and_store_facts(
    user_id: str,
    conversation_id: str,
    messages: list,
) -> None:
    """Extract key facts from a conversation and store them as UserMemoryLog entries.

    Chemin par TOUR. Depuis le 02/09/2026 il n'est plus branché par défaut :
    seul ``MEMORY_EXTRACTION_PER_TURN=true`` le rallume (cf.
    ``maybe_spawn_fact_extraction``). Le chemin normal est
    ``extract_new_facts_for_user``, une fois par jour.

    Uses Ollama (Tier 1) for extraction — fast, free, local.
    This function is designed to be called as fire-and-forget; it swallows all errors.
    """
    if not user_id or not messages:
        return

    try:
        # Build a compact conversation string (last N messages only)
        conversation_parts: list[str] = []
        for msg in messages[-_EXTRACTION_MESSAGE_WINDOW:]:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                role_label = "Utilisateur" if role == "human" else "Assistante"
                conversation_parts.append(
                    f"{role_label}: {content[:_EXTRACTION_CHAR_CAP]}"
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_and_store_facts failed silently: %s", exc)
        return

    if not conversation_parts:
        return

    await _extract_facts_from_text(
        user_id, conversation_id, "\n".join(conversation_parts)
    )


async def _extract_facts_from_text(
    user_id: str,
    conversation_id: str | None,
    conversation_text: str,
) -> int:
    """UN appel de modèle sur un texte de conversation déjà borné.

    Cœur partagé par le chemin par tour et le lot quotidien : c'est ici que
    se compte le coût. Ne lève jamais.

    Returns:
        Le nombre de faits réellement stockés.
    """
    try:
        # Use MAINTENANCE tier (configurable via Settings → Niveaux de routage)
        from app.services.llm_provider import get_llm_for_tier, ComplexityTier
        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)

        prompt = _EXTRACTION_PROMPT.format(conversation=conversation_text)
        # config={"callbacks": []} isolates this call from any active LangGraph
        # callback context (propagated via contextvars through ensure_future).
        # Without this, Ollama's tokens would leak into the active chat stream.
        # OPTIM — corvée de fond : pas de raisonnement. Mesuré en prod,
        # ce chemin générait 2 101 tokens de sortie par appel sur
        # qwen3.5-9b (151 avec un modèle sans raisonnement), 3 814 fois.
        # L'isolation du stream et le retrait du bloc <think> sont dans le
        # helper. Voir services/background_llm.py.
        from app.services.background_llm import ainvoke_background_with_usage
        raw, response = await ainvoke_background_with_usage(
            llm, [{"role": "user", "content": prompt}],
        )

        # A-6b — chemin background compté dans UsageLog (best-effort)
        try:
            from app.services.analytics_service import log_response_usage
            await log_response_usage(
                user_id, response,
                skill_used="memory_extraction",
                conversation_id=conversation_id,
            )
        except Exception:
            pass

        # Parse JSON response
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        facts = data.get("facts", [])

        if not facts:
            return 0

        stored = 0
        # Store facts in DB
        async with async_session() as db:
            for item in facts:
                if not isinstance(item, dict):
                    continue
                fact_text = str(item.get("fact", "")).strip()
                fact_type = str(item.get("type", "context")).strip()
                if not fact_text:
                    continue
                # MED-5: Reject facts that look like prompt injection attempts
                if not _is_safe_fact(fact_text):
                    logger.warning(
                        "Rejected potentially injected fact for user %s: %.100s",
                        user_id, fact_text,
                    )
                    continue
                if fact_type not in ("preference", "context", "event", "skill", "personal"):
                    fact_type = "context"

                log_entry = UserMemoryLog(
                    user_id=user_id,
                    conversation_id=conversation_id or None,
                    fact=fact_text,
                    fact_type=fact_type,
                    is_consolidated=False,
                )
                db.add(log_entry)
                stored += 1
            await db.commit()

        logger.debug("Extracted %d facts for user %s", stored, user_id)
        return stored

    except json.JSONDecodeError:
        logger.debug("_extract_facts_from_text: could not parse JSON response — skipping")
        return 0
    except Exception as exc:
        logger.debug("_extract_facts_from_text failed silently: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Extraction par LOT — un appel de modèle par utilisateur et par jour
# ---------------------------------------------------------------------------
#
# ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : voir le commentaire de
# ``maybe_spawn_fact_extraction``. Ici vit le remplaçant.
#
# **Aucune table ni colonne nouvelle.** La borne « depuis quand » se dérive de
# l'existant : ``observed_at`` est posé à l'instant de l'extraction, donc le
# plus récent des ``UserMemoryLog`` d'un utilisateur dit jusqu'où on avait lu.
# ``_extract_facts_from_text`` est le SEUL écrivain de cette table dans tout
# ``app/`` (vérifié le 02/09/2026 : ``grep -rn "UserMemoryLog(" app`` ne rend
# que cet appel), la borne ne peut donc pas être avancée par un autre chemin.
#
# ⚠️ Le seul angle mort assumé : si une passe ne rend AUCUN fait, rien n'est
# écrit, donc la borne n'avance pas et le lendemain relit la même fenêtre.
# Ça coûte 1 appel par jour — exactement le budget visé — et ça ne
# s'accumule pas, la fenêtre glissant sur les messages les plus récents.


async def _last_extraction_at(db, user_id: str) -> datetime | None:
    """Jusqu'où l'extraction avait lu pour cet utilisateur, ou None."""
    result = await db.execute(
        select(UserMemoryLog.observed_at)
        .where(UserMemoryLog.user_id == user_id)
        .order_by(UserMemoryLog.observed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ⚠️ PII (02/09/2026) — CE CHEMIN LIT LA BASE, PAS LE GRAPHE.
#
# Le chemin par TOUR ne voyait que du texte déjà anonymisé : ``chat.py``
# anonymise avant de construire l'état du graphe, et l'extraction recevait
# ces messages-là. Le lot, lui, relit la table ``messages``, qui stocke les
# valeurs RÉELLES : ``chat.py`` y persiste ``user_content`` et non
# ``clean_content``, et les réponses assistant y sont écrites
# DÉ-anonymisées (pour l'affichage). C'est précisément pour ça que
# ``chat.py`` ré-anonymise chaque ligne d'historique avant de la rendre au
# modèle. Sans le même geste ici, la passe quotidienne envoyait adresses,
# numéros, IBAN et jetons en clair au modèle de fond — qui peut être un
# modèle cloud.
#
# Même discipline que ``chat.py`` : ``ner_detection`` actif sur ce que
# l'utilisateur a TAPÉ, éteint sur le contenu machine (réponses assistant,
# majoritairement du web recopié — y détecter chaque personne/organisation
# détruit l'utilité de l'extraction, cf. security_filter.anonymize).
#
# FILTRE NEUF, PAS CELUI DU REGISTRE ``conversation_filters``. Trois raisons :
#   1. Le lot couvre PLUSIEURS conversations ; le registre est indexé PAR
#      conversation. Il n'existe donc pas « un » filtre partagé à prendre,
#      et en choisir un mélangerait les vaults de fils distincts.
#   2. Le registre est en mémoire, borné à 1000 entrées avec un TTL
#      d'inactivité de 24 h. À 02:45, les filtres de la veille sont morts (ou
#      le processus a redémarré) : ``get_filter`` FABRIQUERAIT des vaults
#      vides et évincerait au passage ceux de conversations vivantes.
#   3. La réversibilité ne sert à rien ici : la sortie n'est jamais
#      dé-anonymisée ni rendue à l'utilisateur.
#
# ⚠️ ET ON NE DÉ-ANONYMISE PAS AU RETOUR. Les faits extraits sont stockés
# masqués, donc un placeholder peut finir dans ``user_profiles`` puis dans un
# prompt sans être résoluble — c'est déjà le cas du chemin par tour, qui
# extrait lui aussi d'un texte masqué. Le remettre en clair déplacerait
# simplement la fuite d'un cran : ``consolidate_user_memory`` (03:00) renvoie
# le texte des faits au modèle SANS aucun filtre. Un masque irrésoluble se
# lit comme un masque ; une adresse en clair partie au cloud ne se rattrape
# pas.
async def extract_new_facts_for_user(user_id: str) -> int:
    """Extrait en UN appel les faits de tout ce qui est nouveau, toutes
    conversations confondues.

    Zéro appel de modèle si l'utilisateur n'a rien dit depuis la dernière
    passe : la question « y a-t-il du nouveau ? » se répond en SQL.

    Ne lève jamais — c'est un cron.

    Returns:
        Le nombre de faits stockés.
    """
    if not user_id:
        return 0

    try:
        from app.models.conversation import Conversation, Message
        from app.services.security_filter import SecurityFilter

        async with async_session() as db:
            bound = await _last_extraction_at(db, user_id)
            query = (
                select(Message.conversation_id, Message.role, Message.content)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.user_id == user_id)
            )
            if bound is not None:
                query = query.where(Message.created_at > bound)
            # Les plus RÉCENTS d'abord pour que le plafond coupe le vieux,
            # puis remise en ordre chronologique pour le prompt.
            query = query.order_by(Message.created_at.desc()).limit(
                _DAILY_EXTRACTION_MESSAGE_WINDOW
            )
            rows = list((await db.execute(query)).all())

        if not rows:
            return 0

        # Vault jeté à la fin de la passe — voir le commentaire au-dessus de
        # la fonction pour le choix du filtre neuf.
        filtre = SecurityFilter()

        # La coupe de récence a été faite en SQL sur la DATE. On regroupe
        # ensuite PAR FIL : deux conversations menées en parallèle dans la
        # journée ressortaient sinon entrelacées ligne à ligne, et rien ne
        # disait au modèle qu'il changeait de sujet — d'où des faits
        # conflatés (« l'utilisateur travaille sur X avec Y », X et Y venant
        # de deux fils). L'ordre des fils suit leur plus ancien message
        # retenu ; l'ordre à l'intérieur d'un fil reste chronologique.
        fils: dict[str, list[str]] = {}
        for fil_id, role, content in reversed(rows):
            if not isinstance(content, str) or not content.strip():
                continue
            venant_de_l_utilisateur = role == "user"
            # Anonymiser AVANT de tronquer : couper d'abord pourrait scinder
            # une adresse en deux et en laisser la moitié passer en clair,
            # que la regex ne reconnaît plus.
            masque = filtre.anonymize(
                content, ner_detection=venant_de_l_utilisateur
            )[:_EXTRACTION_CHAR_CAP]
            role_label = "Utilisateur" if venant_de_l_utilisateur else "Assistante"
            fils.setdefault(fil_id, []).append(f"{role_label}: {masque}")

        if not fils:
            return 0

        blocs = [
            f"--- Fil {rang} ---\n" + "\n".join(lignes)
            for rang, lignes in enumerate(fils.values(), start=1)
        ]

        # conversation_id volontairement None : le lot couvre la journée,
        # pas un fil.
        return await _extract_facts_from_text(user_id, None, "\n\n".join(blocs))

    except Exception as exc:  # noqa: BLE001
        logger.error("extract_new_facts_for_user failed for user %s: %s", user_id, exc)
        return 0


async def extract_facts_for_all_users() -> None:
    """Passe quotidienne — APScheduler, 02:45, juste AVANT la consolidation.

    Au plus un appel de modèle par utilisateur, et aucun pour ceux qui n'ont
    pas parlé.
    """
    try:
        from app.models.user import User
        async with async_session() as db:
            result = await db.execute(select(User.id))
            user_ids: list[str] = [row[0] for row in result.fetchall()]

        total_facts = 0
        for uid in user_ids:
            try:
                total_facts += await extract_new_facts_for_user(uid)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "extract_facts_for_all_users: failed for user %s: %s", uid, exc
                )

        logger.info(
            "extract_facts_for_all_users: %d faits extraits sur %d utilisateurs",
            total_facts,
            len(user_ids),
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("extract_facts_for_all_users failed: %s", exc)


# ---------------------------------------------------------------------------
# Context retrieval
# ---------------------------------------------------------------------------

# Keys that are ALWAYS included (identity-critical, cheap on tokens).
# Anything else goes through a verbosity/relevance filter.
_PROFILE_CORE_KEYS: frozenset[str] = frozenset({
    "user_name", "preferred_language", "response_style",
    "main_project", "email_provider", "timezone_reminder",
    # Onboarding-sourced keys — always injected so agent knows them from turn 1
    "location", "profession", "routines", "strict_rules",
    # C2-a — identité stable que le classement ne doit jamais évincer.
    # L'adresse de l'utilisateur est nécessaire au « mail à soi-même »
    # (_SELF_MAIL_TOOLS), et le fuseau à toute planification. Sans ces clés
    # au noyau, la pondération par récence les faisait sortir au profit de
    # faits plus frais mais moins utiles (constaté sur le profil réel).
    "primary_email", "user_email", "timezone",
})

# Keys we deliberately SKIP in the compact injection — they're too
# situation-specific to be useful in every prompt and they inflate the
# token count. They remain in the DB and can still be retrieved via the
# semantic RAG path when relevant.
_PROFILE_NOISY_KEYS: frozenset[str] = frozenset({
    "current_delivery", "ionos_client_id",
    "upcoming_events", "daily_summary_config",
    "news_format_preference", "news_recency_preference",
    "news_date_tolerance", "news_topics",
    "dev_context_tag", "gmail_preferences",
    "notification_methods", "location_interest",
    "shopping_routine", "secondary_project",
})


# C2-a — fenêtre de candidats. Le `.limit(20)` historique écartait 218 des
# 238 clés d'un profil réel AVANT tout autre critère : c'était lui, et non le
# plafond de 800 caractères, qui décidait de ce qu'Ely sait de son
# utilisateur. La table fait quelques centaines de lignes par personne ;
# élargir la fenêtre ne coûte rien de sensible et ne touche pas au prompt.
_PROFILE_CANDIDATE_WINDOW = 200

# Demi-vie de la récence, en jours. Un fait revu il y a une semaine pèse
# ~0,8 fois un fait revu aujourd'hui ; un fait vieux d'un an, ~0,1.
_PROFILE_RECENCY_HALFLIFE_DAYS = 45.0


def _rank_profile_rows(rows: list) -> list:
    """Trie les entrées de profil par UTILITÉ, pas par répétition.

    Le tri SQL historique était ``confidence × source_count`` — c'est-à-dire
    *combien de fois le fait a été redit*. Mesuré sur la production le 25/07,
    ça donnait ceci pour un profil de 238 clés :

        rang  19  mobile_provider ......... « Free Mobile »   → injecté
        rang  74  personal_contacts ....... les proches       → jamais
        rang  92  custom_preferences ...... l'ordre d'appel   → jamais
        rang 110  email_facture_process ... le circuit        → jamais
        rang 150  medical_preferences ..... les motifs de RDV → jamais

    Un fait trivial mais souvent redit écrasait un fait décisif dit une fois.
    On garde donc la fréquence comme signal — elle dit quelque chose — mais on
    la pondère par la **récence** : ce qui a été revu récemment a plus de
    chances d'être encore vrai, et d'être utile maintenant.

    Le tri ne décide pas seul : les clés du noyau (identité) passent devant
    quoi qu'il arrive, et les clés bruyantes sont filtrées, en aval.
    """
    now = datetime.now(timezone.utc)

    def _score(row) -> float:
        base = float(getattr(row, "confidence", 1.0) or 1.0) * float(
            getattr(row, "source_count", 1) or 1
        )
        last_seen = getattr(row, "last_seen", None)
        if last_seen is None:
            return base * 0.5  # jamais revu : on ne le privilégie pas
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
        recency = 0.5 ** (age_days / _PROFILE_RECENCY_HALFLIFE_DAYS)
        # Racine de la fréquence : redire dix fois vaut mieux qu'une, mais pas
        # dix fois mieux — sans quoi la trivialité répétée regagne la partie.
        return (base ** 0.5) * (0.3 + 0.7 * recency)

    return sorted(rows, key=_score, reverse=True)


# C2-b — budget du rappel contextuel. Volontairement petit : ce bloc est
# recalculé à CHAQUE tour, donc il invalide d'autant le cache de prompt du
# fournisseur. Le profil permanent (800 car.) reste le gros du contexte.
_CONTEXTUAL_RECALL_BUDGET = 500

# Mots trop courants pour discriminer quoi que ce soit dans une question.
_RECALL_STOPWORDS: frozenset[str] = frozenset({
    "les", "des", "mes", "mon", "ma", "est", "que", "qui", "quoi", "quel",
    "quelle", "pour", "dans", "avec", "sur", "une", ", ", "tu", "je", "il",
    "elle", "ce", "cette", "ces", "sont", "ai", "as", "peux", "fait", "faire",
    "deja", "déjà", "bien", "plus", "moins", "tout", "tous", "toute",
})


def _recall_tokens(text: str) -> set[str]:
    """Tokens signifiants d'un texte, pour le rapprochement lexical."""
    import re
    raw = re.findall(r"[\w\u00c0-\u024f]+", (text or "").lower())
    return {t for t in raw if len(t) >= 4 and t not in _RECALL_STOPWORDS}


# Seuil de quasi-doublon. 0,72 sépare les trois paraphrases mesurées en
# production (elles se ressemblent à ~0,75-0,85) des faits réellement
# distincts. Trop haut, les redondances repassent ; trop bas, on perd des
# faits différents qui partagent du vocabulaire.
_RECALL_SIMILARITY_THRESHOLD = 0.72


def _too_similar(candidate: str, kept: str) -> bool:
    """Deux valeurs disent-elles la même chose ?

    Combine deux signaux, parce qu'aucun ne suffit seul : le recouvrement de
    vocabulaire (robuste aux réordonnancements) et la similarité de séquence
    (robuste aux petites variantes de formulation).
    """
    import difflib

    a, b = _recall_tokens(candidate), _recall_tokens(kept)
    if a and b:
        jaccard = len(a & b) / len(a | b)
        if jaccard >= _RECALL_SIMILARITY_THRESHOLD:
            return True
    return difflib.SequenceMatcher(None, candidate, kept).ratio() >= (
        _RECALL_SIMILARITY_THRESHOLD + 0.08
    )


async def get_query_relevant_profile(
    user_id: str, query: str, budget: int = _CONTEXTUAL_RECALL_BUDGET
) -> str:
    """Faits du profil pertinents POUR CETTE DEMANDE, ou chaîne vide.

    C'est la strate « rappel à la demande » du chantier C2 — et elle comble
    une promesse que le code faisait sans la tenir. ``_PROFILE_NOISY_KEYS``
    annonce que ces clés « can still be retrieved via the semantic RAG path
    when relevant » : **aucun code ne le fait**. `user_profiles` n'est lu que
    par l'injection plafonnée et un rapport admin ; le magasin sémantique
    interroge Qdrant, et sa réconciliation avec SQL n'a jamais été écrite.
    Une clé bruyante était donc inatteignable — une suppression déguisée.

    Ici, elles redeviennent atteignables **quand la question les appelle** :
    « j'ai un rendez-vous bientôt ? » ramène ``upcoming_events``, « où vont
    mes factures ? » ramène ``email_facture_process``.

    Deux principes :

    - **Ne jamais remplir pour remplir.** Sans correspondance, on rend une
      chaîne vide : le prompt système a un plafond de 15 000 caractères, et
      un bloc au hasard coûte de l'attention sans rien apporter.
    - **Ne pas répéter le profil permanent.** Les clés du noyau y sont déjà ;
      les redire ici gaspillerait le budget.

    ⚠️ **Ce bloc ne doit PAS entrer dans le snapshot mémoire gelé**
    (``frozen_memory``), qui est mis en cache par conversation : il ne
    servirait que la première question du fil. Sa place est la zone volatile
    du prompt, avec la date.

    Best-effort : ne lève jamais.
    """
    q_tokens = _recall_tokens(query)
    if not user_id or not q_tokens:
        return ""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(UserProfile)
                .where(UserProfile.user_id == user_id)
                .where(
                    (UserProfile.expires_at == None)  # noqa: E711
                    | (UserProfile.expires_at > datetime.now(timezone.utc))
                )
                .limit(_PROFILE_CANDIDATE_WINDOW)
            )
            rows: list[UserProfile] = list(result.scalars().all())

        scored: list[tuple[float, str, str]] = []
        for row in rows:
            if row.key in _PROFILE_CORE_KEYS:
                continue  # déjà dans le profil permanent
            haystack = _recall_tokens(f"{row.key} {row.value}")
            if not haystack:
                continue
            overlap = q_tokens & haystack
            if not overlap:
                continue
            scored.append((
                len(overlap) / len(q_tokens),
                f"{row.key}: {str(row.value)[:110]}",
                str(row.value).strip().lower()[:120],
            ))

        if not scored:
            return ""

        scored.sort(key=lambda p: p[0], reverse=True)
        header = "Ce que tu sais déjà, en lien avec cette demande:"
        parts = [header]
        current = len(header)
        kept_fingerprints: list[str] = []
        for _score, entry, fingerprint in scored:
            # Constaté en prod : « où vont mes factures ? » remplissait les
            # trois places avec gmail_preferences, email_preferences et
            # email_cleanup_preference :
            #   « Supprimer promotions/spams, conserver pièces jointes… »
            #   « Supprimer spams/newsletters, Conserver factures »
            #   « Supprimer promotions/newsletters, conserver factures »
            # Le même fait, dit trois fois avec des mots différents. Une
            # égalité stricte ne les voit pas — d'où le rapprochement par
            # SIMILARITÉ. Le coût est négligeable : on ne compare que les
            # quelques candidats déjà retenus pour cette question.
            if any(_too_similar(fingerprint, kept) for kept in kept_fingerprints):
                continue
            kept_fingerprints.append(fingerprint)
            new_len = current + 3 + len(entry)
            if new_len > budget:
                break
            parts.append(entry)
            current = new_len
        return " | ".join(parts) if len(parts) > 1 else ""

    except Exception as exc:  # noqa: BLE001
        logger.debug("get_query_relevant_profile failed: %s", exc)
        return ""


async def get_user_context(user_id: str, limit: int = 20, compact: bool = True) -> str:
    """Return a compact user profile string for injection into system prompts.

    PERF (2026-04-24) : la version historique renvoyait 15-20 lignes
    "- key : value" à chaque prompt — ~600-1000 tokens. Pour les petits
    modèles locaux (Qwen 2.5-VL 7B), ce volume dilue l'attention et
    détourne le modèle du tool-calling vers du texte conversationnel.

    Le mode compact (défaut) renvoie 3-6 lignes priorisées :
    - core keys (name, style, langue, projet principal) : toujours incluses
    - autres keys : uniquement si pas dans la blacklist bruit
    - limite stricte : ~200 tokens / ~800 caractères

    Mettre compact=False rétablit le comportement historique (pour debug
    ou pour les très gros modèles qui bénéficient du contexte complet).
    """
    if not user_id:
        return ""

    try:
        async with async_session() as db:
            # Fetch top entries ordered by confidence × source_count descending
            # C2-a — la fenêtre de candidats n'est PLUS le verrou.
            #
            # Mesuré en prod le 25/07 : 238 clés stockées, `.limit(20)`, donc
            # 218 écartées AVANT tout autre critère. Et le tri
            # `confidence × source_count` classe par *répétition*, pas par
            # utilité : « mobile_provider: Free Mobile » (rang 19) atteignait
            # le modèle, « upcoming_events: RDV médical » (rang 186) jamais.
            #
            # On élargit la fenêtre et on reclasse en Python (§ _rank_profile_
            # rows). Le coût est une requête plus large sur une table de
            # quelques centaines de lignes ; le PROMPT, lui, ne bouge pas —
            # le plafond de 800 caractères plus bas est inchangé.
            result = await db.execute(
                select(UserProfile)
                .where(UserProfile.user_id == user_id)
                .where(
                    (UserProfile.expires_at == None)  # noqa: E711
                    | (UserProfile.expires_at > datetime.now(timezone.utc))
                )
                .order_by(
                    (UserProfile.confidence * UserProfile.source_count).desc()
                )
                .limit(max(limit, _PROFILE_CANDIDATE_WINDOW))
            )
            rows: list[UserProfile] = list(result.scalars().all())

        if not rows:
            return ""

        if not compact:
            # Legacy verbose mode — all facts, one per line
            lines = ["Ce que tu sais sur cet utilisateur :"]
            for row in rows:
                lines.append(f"- {row.key} : {row.value}")
            return "\n".join(lines)

        # ── Compact mode ──────────────────────────────────────────────
        # 1. Extract core keys first (identity-critical).
        # 2. Then add non-noisy keys up to the 800-char ceiling.
        # 3. Skip noisy keys entirely — semantic RAG will surface them
        #    when contextually relevant, not in every prompt.
        core: list[str] = []
        extra: list[str] = []
        seen_values: set[str] = set()
        for row in _rank_profile_rows(rows):
            if row.key in _PROFILE_NOISY_KEYS:
                continue
            # Mesuré en prod : `user_email`, `primary_email`, `personal_email`
            # et `primary_contact_email` portent la MÊME valeur. Le budget est
            # trop court pour la dire quatre fois.
            fingerprint = str(row.value).strip().lower()[:120]
            if fingerprint in seen_values:
                continue
            seen_values.add(fingerprint)
            value_truncated = str(row.value)[:80]
            entry = f"{row.key}: {value_truncated}"
            if row.key in _PROFILE_CORE_KEYS:
                core.append(entry)
            else:
                extra.append(entry)

        if not core and not extra:
            return ""

        # Assemble with a hard cap of ~800 chars (≈200 tokens)
        parts = ["Profil utilisateur:"]
        current_len = len(parts[0])
        for entry in core + extra:
            new_len = current_len + 2 + len(entry)  # 2 for " | " separator
            if new_len > 800:
                break
            parts.append(entry)
            current_len = new_len

        return " | ".join(parts)

    except Exception as exc:
        logger.debug("get_user_context failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Memory consolidation
# ---------------------------------------------------------------------------

async def consolidate_user_memory(user_id: str) -> int:
    """Consolidate UserMemoryLog entries into UserProfile for a single user.

    Process:
    1. Fetch all unconsolidated UserMemoryLog for this user
    2. Fetch existing UserProfile
    3. Call Mistral-small with a consolidation prompt
    4. Parse response and upsert UserProfile entries
    5. Mark logs as consolidated

    Returns the number of log entries processed.
    """
    if not user_id:
        return 0

    try:
        # Step 1: Fetch unconsolidated logs
        # Limite bumpée de 200 → 2000 après observation d'un backlog qui
        # grossissait plus vite que le traitement (80+ faits/jour extraits
        # contre 200/jour consolidés). Avec 2000, un seul run rattrape
        # 10 jours d'usage normal d'un coup.
        async with async_session() as db:
            result = await db.execute(
                select(UserMemoryLog)
                .where(UserMemoryLog.user_id == user_id)
                .where(UserMemoryLog.is_consolidated == False)  # noqa: E712
                .order_by(UserMemoryLog.observed_at)
                .limit(2000)
            )
            logs: list[UserMemoryLog] = list(result.scalars().all())

        if not logs:
            return 0

        log_ids = [log.id for log in logs]
        raw_facts_text = "\n".join(
            f"[{log.fact_type}] {log.fact}" for log in logs
        )

        # Step 2: Fetch existing profile
        async with async_session() as db:
            result = await db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            existing_rows: list[UserProfile] = list(result.scalars().all())

        existing_profile_text = ""
        if existing_rows:
            existing_profile_text = "\n".join(
                f"- {row.key} : {row.value} (confidence={row.confidence:.2f})"
                for row in existing_rows
            )
        else:
            existing_profile_text = "(aucun profil existant)"

        # Step 3: Use MAINTENANCE tier for consolidation — background task,
        # no real-time interaction required. Configurable via Settings → Niveaux de routage.
        from app.services.llm_provider import get_llm_for_tier, ComplexityTier
        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)

        prompt = _CONSOLIDATION_PROMPT.format(
            raw_facts=raw_facts_text,
            existing_profile=existing_profile_text,
        )
        # OPTIM — 6 675 tokens de sortie par consolidation mesurés en prod,
        # le pire ratio de toutes les tâches de fond. Voir background_llm.py.
        from app.services.background_llm import ainvoke_background_with_usage
        raw, response = await ainvoke_background_with_usage(
            llm, [{"role": "user", "content": prompt}],
        )

        # A-6b — consolidation nocturne comptée dans UsageLog (best-effort)
        try:
            from app.services.analytics_service import log_response_usage
            await log_response_usage(
                user_id, response, skill_used="memory_consolidation",
            )
        except Exception:
            pass

        # Parse JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        profile_entries = data.get("profile", [])

        # Step 4: Upsert UserProfile entries
        async with async_session() as db:
            for item in profile_entries:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", "")).strip()
                value = str(item.get("value", "")).strip()
                confidence = float(item.get("confidence", 1.0))

                if not key or not value:
                    continue
                confidence = max(0.0, min(1.0, confidence))

                # Check if entry exists
                result = await db.execute(
                    select(UserProfile)
                    .where(UserProfile.user_id == user_id)
                    .where(UserProfile.key == key)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.value = value
                    existing.confidence = confidence
                    existing.source_count = existing.source_count + 1
                    existing.last_seen = datetime.now(timezone.utc)
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    db.add(UserProfile(
                        user_id=user_id,
                        key=key,
                        value=value,
                        confidence=confidence,
                        source_count=1,
                        last_seen=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    ))

            # Step 5: Mark logs as consolidated
            await db.execute(
                update(UserMemoryLog)
                .where(UserMemoryLog.id.in_(log_ids))
                .values(is_consolidated=True)
            )
            await db.commit()

        logger.info(
            "Consolidated %d memory logs into %d profile entries for user %s",
            len(logs),
            len(profile_entries),
            user_id,
        )
        return len(logs)

    except json.JSONDecodeError:
        logger.warning("consolidate_user_memory: JSON parse error for user %s", user_id)
        return 0
    except Exception as exc:
        logger.error("consolidate_user_memory failed for user %s: %s", user_id, exc)
        return 0


# ---------------------------------------------------------------------------
# Nightly scheduler entry point
# ---------------------------------------------------------------------------

async def consolidate_all_users() -> None:
    """Consolidate memory for ALL users. Called by APScheduler at 3 AM."""
    try:
        from app.models.user import User
        async with async_session() as db:
            result = await db.execute(select(User.id))
            user_ids: list[str] = [row[0] for row in result.fetchall()]

        if not user_ids:
            logger.info("consolidate_all_users: no users found")
            return

        total_processed = 0
        for uid in user_ids:
            try:
                n = await consolidate_user_memory(uid)
                total_processed += n
            except Exception as exc:
                logger.error("consolidate_all_users: failed for user %s: %s", uid, exc)

        logger.info(
            "consolidate_all_users: processed %d log entries across %d users",
            total_processed,
            len(user_ids),
        )

    except Exception as exc:
        logger.error("consolidate_all_users failed: %s", exc)
