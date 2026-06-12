# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/memory_tool.py
# @brief      Memory tools — save user preferences and constraints in real time
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Memory tools — save user preferences and constraints in real time.

These tools allow the agent to immediately persist user preferences (tone,
format, style) and behavioral constraints when the user explicitly expresses
them during a conversation. Without these tools, preferences were only
extracted post-session and could be lost or delayed.

Sprint 2.5 Jalon 4 — explicit write routing
-------------------------------------------
This module writes to two distinct typed stores. Each tool below states
its target type + store + rationale right above the @tool decorator,
so the routing is auditable from a single grep. See
``app/services/memory/ROUTING.md`` for the full mapping.
"""
from __future__ import annotations

import logging
import re
from typing import Annotated

from langchain_core.tools import tool, InjectedToolArg

from app.services.memory import (
    get_constraint_store,
    get_semantic_user_store,
)

logger = logging.getLogger(__name__)


# Patterns that indicate the model is trying to persist its OWN hallucinated
# limitations as if they were user-imposed rules. These must NEVER reach the
# permanent constraints store: they poison every future conversation by being
# re-injected into the system prompt, causing all subsequent models to refuse
# the same task. (Discovered 2026-05-06 — Ministral 3 8B persisted "Je ne
# peux pas envoyer d'e-mails" and "Je ne peux pas faire de captures" as
# constraints, which then made Kimi K2.6 + Qwen 3.6 Flash refuse the same
# workflow.)
_SELF_LIMITATION_PATTERNS = [
    # ── French — capacité ────────────────────────────────────────────────
    re.compile(r"\bje\s+(ne\s+)?peux\s+pas\b", re.IGNORECASE),
    re.compile(r"\bne\s+peut\s+pas\b", re.IGNORECASE),
    re.compile(r"\bje\s+ne\s+suis\s+pas\s+(capable|en\s+mesure|autoris[ée]e?)\b", re.IGNORECASE),
    re.compile(r"\bje\s+ne\s+sais\s+pas\s+(faire|comment)\b", re.IGNORECASE),
    re.compile(r"\bne\s+dispose\s+pas\b", re.IGNORECASE),
    # ── French — possibilité / impossibilité ─────────────────────────────
    re.compile(r"\bimpossible\s+(de|d['e]?|pour)\b", re.IGNORECASE),
    re.compile(r"\bpas\s+possible\s+(de|d['e]?)\b", re.IGNORECASE),
    re.compile(r"\bil\s+(n['e]?\s*)?est\s+pas\s+possible\b", re.IGNORECASE),
    # ── French — droit / permission / autorisation ───────────────────────
    re.compile(r"\bje\s+n['e]?\s*ai\s+pas\s+(le\s+droit|l['e]?\s*autorisation|la\s+permission)\b",
               re.IGNORECASE),
    re.compile(r"\bil\s+m['e]?\s*est\s+interdit\s+(de|d['e]?)\b", re.IGNORECASE),
    re.compile(r"\binterdit\s+(de|d['e]?|par)\b", re.IGNORECASE),
    re.compile(r"\bnon\s+autoris[ée]e?\b", re.IGNORECASE),
    re.compile(r"\bje\s+n['e]?\s*ai\s+pas\s+l['e]?\s*acc[eè]s\b", re.IGNORECASE),
    # ── French — outils manquants ────────────────────────────────────────
    re.compile(r"\baucun\s+outil\s+n['e]?\s*(est\s+)?disponible\b", re.IGNORECASE),
    re.compile(r"\boutils?\s+non\s+disponibles?\b", re.IGNORECASE),
    re.compile(r"\bnon\s+disponibles?\s+pour\s+cet\s+agent\b", re.IGNORECASE),
    re.compile(r"\bne\s+pas\s+tenter\s+d['e]?\s*utiliser\b", re.IGNORECASE),
    re.compile(r"\bjeton\s+d['e]?\s*acc[eè]s\s+(est\s+)?(expir[ée]|r[ée]voqu[ée])\b", re.IGNORECASE),
    # ── English — capacité ───────────────────────────────────────────────
    re.compile(r"\bi\s+(can\s*not|can'?t)\b", re.IGNORECASE),
    re.compile(r"\bcannot\s+(access|use|do|send|create|read|write|navigate|capture)\b",
               re.IGNORECASE),
    re.compile(r"\bi\s+am\s+(unable|not\s+able)\s+to\b", re.IGNORECASE),
    re.compile(r"\bunable\s+to\b", re.IGNORECASE),
    # ── English — permission ─────────────────────────────────────────────
    re.compile(r"\bi\s*(am|'?m)\s+not\s+(allowed|permitted|authorized)\s+to\b", re.IGNORECASE),
    re.compile(r"\bi\s+do\s*n['o]?t\s+have\s+(permission|the\s+right|authorization)\b",
               re.IGNORECASE),
    re.compile(r"\bi\s+have\s+no\s+(permission|right|authorization|access|tool)\b",
               re.IGNORECASE),
    re.compile(r"\b(it'?s|it\s+is)\s+(forbidden|prohibited|not\s+allowed)\b", re.IGNORECASE),
    re.compile(r"\bforbidden\s+to\b", re.IGNORECASE),
    re.compile(r"\bprohibited\s+(from|to)\b", re.IGNORECASE),
    # ── English — outils manquants ───────────────────────────────────────
    re.compile(r"\bdo\s+not\s+have\s+(access|the\s+tool|tools)\b", re.IGNORECASE),
    re.compile(r"\bno\s+tool\s+(is\s+)?available\b", re.IGNORECASE),
]

# A model that gets bounced by _SELF_LIMITATION_PATTERNS may rephrase its
# refusal as "Ne jamais [native capability]" — which looks like a legitimate
# user-imposed rule. We block these blanket capability denials UNLESS the
# rule names a specific target (an email address, URL, path, etc.).
#
# Rationale: a real user rule is "Ne jamais envoyer de mail à spam@x.com"
# (specific). A hallucinated blanket like "Ne jamais envoyer de mails" or
# "Ne jamais capturer de sites web" must be rejected — those are core
# capabilities that the model is paid to deliver.
_NATIVE_CAPABILITY_BLOCKERS = [
    # Screenshot / capture
    re.compile(
        r"\b(ne\s+jamais|never)\s+("
        r"capturer|prendre\s+(une\s+)?capture|faire\s+(une\s+|de\s+)?capture|"
        r"capture|screenshot|screen\s*capture"
        r")\b",
        re.IGNORECASE,
    ),
    # Email send
    re.compile(
        r"\b(ne\s+jamais|never)\s+(envoyer|exp[ée]dier|send)\s+(d['e]?\s*|de\s+|an?\s+|the\s+)?"
        r"(e[\s-]?mails?|mails?|courriels?|messages?\s+[ée]lectroniques?)",
        re.IGNORECASE,
    ),
    # File save / disk access (generic)
    re.compile(
        r"\b(ne\s+jamais|never)\s+("
        r"enregistrer|sauvegarder|stocker|[ée]crire|save|store|write"
        r")\s+.*?("
        r"fichiers?|files?|disque|disk|locale?ment|locally|"
        r"syst[eè]me\s+de\s+fichiers?|filesystem"
        r")",
        re.IGNORECASE,
    ),
    # Browse / navigate
    re.compile(
        r"\b(ne\s+jamais|never)\s+("
        r"naviguer|browse|consulter|aller\s+sur|visiter|visit"
        r")\b",
        re.IGNORECASE,
    ),
    # Tasks / calendar / drive — blanket denial of an integrated service
    re.compile(
        r"\b(ne\s+jamais|never)\s+(acc[ée]der|access|utiliser|use)\s+.*?"
        r"(google\s+(tasks|drive|docs|sheets|calendar|agenda)|drive|gmail|tasks?)",
        re.IGNORECASE,
    ),
]

# A rule that has a specific target (email address, URL, file path, named
# entity) is exempt from the capability blocker check — it's likely a real
# user rule like "Ne jamais envoyer de mail à spam@bad.com".
_SPECIFIC_TARGET_RE = re.compile(
    r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"     # email
    r"|https?://\S+"                    # URL
    r"|\b(?:à|to|vers|pour)\s+\"[^\"]+\""  # quoted target
    r"|\b(?:à|to|vers|pour)\s+'[^']+'",
    re.IGNORECASE,
)


def _looks_like_self_limitation(rule: str) -> bool:
    """True if the rule reads like the model describing its own (false)
    limitations rather than a user-imposed constraint."""
    if not rule:
        return False
    return any(p.search(rule) for p in _SELF_LIMITATION_PATTERNS)


def _looks_like_capability_blocker(rule: str) -> bool:
    """True if the rule reads like a blanket prohibition of a native ELY
    capability (capture, send mail, save file, browse) without naming a
    specific target — which means it must be a hallucinated self-limit."""
    if not rule:
        return False
    if not any(p.search(rule) for p in _NATIVE_CAPABILITY_BLOCKERS):
        return False
    # Exempt rules with a specific target (legitimate "never X to Y").
    if _SPECIFIC_TARGET_RE.search(rule):
        return False
    return True


@tool
async def save_user_preference(
    preference: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Sauvegarde immédiatement une préférence de communication de l'utilisateur
    en mémoire permanente.

    Utilise cet outil DÈS QUE l'utilisateur exprime explicitement une préférence
    sur la façon dont il veut être servi : ton, format, style, longueur des réponses,
    langue, émojis, markdown, niveau de détail, humour, etc.

    Exemples de déclencheurs :
    - "arrête les émojis" → preference="Ne jamais utiliser d'émojis dans les réponses"
    - "sois plus concise" → preference="Réponses courtes et directes, sans détails superflus"
    - "ne mets plus de markdown" → preference="Ne pas utiliser de formatage markdown"
    - "réponds toujours en anglais" → preference="Répondre en anglais"
    - "tu peux me tutoyer" → preference="Tutoyer l'utilisateur"

    ⚠️ Pour une DONNÉE FACTUELLE à retenir (URL de profil, contact, référence,
    date, nom de serveur…), ce n'est PAS le bon outil : utilise
    `memory_archive` (category=contact/fact/event).

    La préférence est stockée de façon permanente et sera appliquée à toutes les
    conversations futures.

    Args:
        preference: Description claire et directement actionnable de la préférence
                    (ex: "Ne jamais utiliser d'émojis dans les réponses")

    Sprint 2.5 Jalon 4 — routing explicite:
        MemoryType  = SEMANTIC_USER (kind=preference)
        Store       = SemanticUserStore.store_preference
        Collection  = Qdrant `user_profile` (with dedup ≥ 0.88 cosine)
        Rationale   = communication style, no decay, injected every prompt
    """
    await get_semantic_user_store().store_preference(preference, user_id)
    return f"Préférence enregistrée : {preference}"


@tool
async def save_constraint(
    rule: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Sauvegarde une règle ou contrainte permanente apprise d'un refus ou d'une
    limite explicitement posée par L'UTILISATEUR (jamais par toi-même).

    ⚠️ NE JAMAIS utiliser cet outil pour enregistrer tes propres limites
    perçues. Si tu penses ne pas pouvoir faire quelque chose, c'est sans
    doute parce que tu n'as pas trouvé l'outil — pas parce que c'est
    interdit. Ne crée JAMAIS de contrainte du type "Je ne peux pas X" ou
    "Aucun outil n'est disponible pour X". Ces règles polluent la mémoire
    permanente et empêchent toutes les conversations futures de fonctionner.

    Utilise cet outil UNIQUEMENT quand l'utilisateur pose explicitement une
    règle ferme sur ce qu'Éli ne doit JAMAIS faire.

    Exemples VALIDES :
    - "ne contacte jamais cette adresse email" → rule="Ne jamais envoyer d'email à X"
    - "ne supprime jamais mes fichiers sans confirmation explicite"
    - "ne partage pas mes données avec des services tiers"

    Exemples INVALIDES (rejetés automatiquement) :
    - "Je ne peux pas envoyer d'e-mails" ❌ (auto-limitation hallucinée)
    - "Aucun outil disponible pour WhatsApp" ❌ (faux — l'outil existe)
    - "Je ne peux pas accéder aux logs" ❌ (auto-limitation)

    Args:
        rule: Règle claire et permanente imposée par l'UTILISATEUR
    """
    if _looks_like_self_limitation(rule):
        logger.warning(
            "save_constraint: REJECTED self-limitation rule for user=%s: %r",
            user_id, rule,
        )
        return (
            "❌ Refus d'enregistrement : cette règle décrit une auto-limitation "
            "perçue, pas une contrainte imposée par l'utilisateur. Vérifie si "
            "l'outil existe vraiment dans ta liste avant de conclure que tu ne "
            "peux pas faire quelque chose. Les contraintes ne servent qu'à "
            "stocker les règles explicites de l'utilisateur (ex: \"ne contacte "
            "jamais X\")."
        )
    if _looks_like_capability_blocker(rule):
        logger.warning(
            "save_constraint: REJECTED blanket capability blocker for user=%s: %r",
            user_id, rule,
        )
        return (
            "❌ Refus d'enregistrement : cette règle interdit une capacité "
            "native d'Éli (capture, envoi de mail, écriture fichier, "
            "navigation web…) sans cible spécifique. Une règle valide doit "
            "nommer un destinataire, une URL, un chemin précis (ex: \"Ne "
            "jamais envoyer de mail à spam@x.com\"). Les interdictions globales "
            "de capacités ne peuvent pas être enregistrées."
        )
    # Sprint 2.5 Jalon 4 — routing explicite:
    #     MemoryType  = CONSTRAINT
    #     Store       = ConstraintStore.store
    #     Collection  = Qdrant `security_constraints` (no decay)
    #     Rationale   = user-imposed permanent rules, injected every prompt
    await get_constraint_store().store(rule, user_id)
    return f"Contrainte enregistrée : {rule}"
