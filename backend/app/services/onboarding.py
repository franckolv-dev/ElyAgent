# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/onboarding.py
# @brief      Conversational onboarding — Éli learns the user's vocabulary at
#             first login (preferred name, communication style, Gmail labels,
#             calendar names, vocabulary mappings, routines, strict rules).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Conversational onboarding service.

Why : ELY is most useful when she understands the user's wording (« mes
mailings » = newsletters, « boulot » = the « Travail Pro » calendar,
« indésirables » = spam folder). Without this, the agent has to guess
each time — and sometimes guesses wrong with destructive consequences
(see May 2026 Temu incident).

Flow : at first login, Éli pushes a guided sequence of ~7 questions in
the chat. Each answer is :
  - Stored as a `fact` in `memory_manager` (long-term semantic memory)
  - Mapped into `user_vocabulary` rows when relevant (fast lookup at
    inference time)
  - The user can /skip at any moment.

Resumable : `User.onboarding_step` tracks the next question index, so
closing the tab mid-flow keeps progress.

A separate Settings page (« Mon profil Éli ») lets the user revise
their answers anytime — also accessible via `/api/onboarding/restart`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Question schema
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OnboardingQuestion:
    """Definition of a single onboarding step."""
    id: str                              # stable id, e.g. "preferred_name"
    text: str                            # what Éli says to the user
    placeholder: str = ""                # input placeholder hint
    skippable: bool = True               # show "Plus tard" button
    domain: str = "general"              # used for vocabulary entries
    free_form: bool = True               # vs multiple choice (future)


QUESTIONS: list[OnboardingQuestion] = [
    OnboardingQuestion(
        id="preferred_name",
        text=(
            "Bonjour ! Je suis Éli, ton assistante. Je vais te poser quelques "
            "questions rapides pour mieux te connaître — ça me permettra de "
            "comprendre ce que tu me demandes plus précisément, sans te faire "
            "répéter à chaque fois.\n\n"
            "Pour commencer : **comment veux-tu que je t'appelle ?** "
            "(prénom, surnom, ce que tu préfères)"
        ),
        placeholder="Franck, Mon Capitaine, …",
        domain="general",
    ),
    OnboardingQuestion(
        id="response_style",
        text=(
            "Quand je te réponds, **tu préfères que je sois plutôt concise "
            "(2-3 phrases) ou détaillée (avec contexte et exemples) ?** "
            "Les deux ont leur charme — tu peux aussi dire « ça dépend du sujet »."
        ),
        placeholder="concise / détaillée / ça dépend …",
        domain="general",
    ),
    OnboardingQuestion(
        id="gmail_labels",
        text=(
            "Parlons de ta boîte mail. **Quelles catégories ou libellés "
            "utilises-tu dans Gmail ?** Tu peux taper la liste, ou "
            "simplement m'indiquer ceux qui te servent le plus.\n\n"
            "Exemples : « j'utilise Achats, Réseaux sociaux, Notifications, "
            "et j'ai un libellé perso 'Personnel' »."
        ),
        placeholder="Achats, Notifications, Promotions, mes libellés perso : …",
        domain="gmail",
    ),
    OnboardingQuestion(
        id="calendars",
        text=(
            "**As-tu plusieurs calendriers Google ?** (par exemple un perso, "
            "un pro, un familial). Si oui, dis-moi comment tu les appelles — "
            "je saurai à quoi tu fais référence quand tu me dis « ajoute "
            "ça à mon agenda boulot »."
        ),
        placeholder="Travail Pro, Famille, Perso …",
        domain="calendar",
    ),
    OnboardingQuestion(
        id="vocabulary",
        text=(
            "Y a-t-il des mots que tu utilises souvent pour parler de tes "
            "outils ? **Donne-moi quelques équivalences** sous la forme "
            "« mon mot = ce que tu dois comprendre ». Par exemple :\n\n"
            "• mes mailings = newsletters\n"
            "• le boulot = mon calendrier 'Travail Pro'\n"
            "• mes indésirables = spam\n\n"
            "Si rien ne te vient → écris « rien »."
        ),
        placeholder="mes mailings = newsletters ; le boulot = Travail Pro ; …",
        domain="general",
    ),
    OnboardingQuestion(
        id="routines",
        text=(
            "**Y a-t-il une routine quotidienne que je peux t'organiser ?** "
            "Par exemple :\n"
            "• un briefing matinal (météo + résumé des mails non lus + agenda du jour)\n"
            "• un rappel de tes rendez-vous une heure avant\n"
            "• un récapitulatif en fin de journée\n\n"
            "Réponds avec ce qui t'intéresse, ou « rien pour l'instant »."
        ),
        placeholder="briefing matin à 8h, rappel RDV, …",
        domain="general",
    ),
    OnboardingQuestion(
        id="location",
        text=(
            "**Où es-tu basé géographiquement ?** (ville, département ou région). "
            "Ça me servira quand tu me demandes la météo, des restos, des "
            "trajets ou n'importe quoi de localisé — sinon je tape par défaut "
            "sur Paris et j'ai déjà fait l'erreur."
        ),
        placeholder="Bordeaux, Gironde, Nouvelle-Aquitaine, …",
        domain="general",
    ),
    OnboardingQuestion(
        id="profession",
        text=(
            "**Dans quel secteur d'activité travailles-tu ?** "
            "(facultatif — ça m'aide à comprendre tes priorités, tes échéances "
            "typiques, le vocabulaire que tu utilises sans m'expliquer). "
            "Tu peux aussi décrire ton rôle si tu préfères."
        ),
        placeholder="Avocat, freelance dev, DSI, médecin, retraité, …",
        domain="general",
    ),
    OnboardingQuestion(
        id="strict_rules",
        text=(
            "Dernière question : **y a-t-il des règles strictes à respecter ?** "
            "Par exemple :\n"
            "• ne jamais envoyer de mail sans validation\n"
            "• ne jamais supprimer de fichier sans confirmation\n"
            "• ne pas planifier de RDV avant 9h\n"
            "• toujours écrire en français même si on me parle en anglais\n\n"
            "Si tu n'as pas de règle particulière → « aucune »."
        ),
        placeholder="toujours valider avant suppression, jamais avant 9h, …",
        domain="general",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

SKIP_LIMIT = 3  # After this many "Plus tard" clicks, stop auto-prompting.


async def get_status(user_id: str) -> dict:
    """Return the onboarding state for a user.

    Shape :
      {
        "completed": bool,   # finished or not
        "skipped": bool,     # user explicitly clicked "plus tard"
        "step": int,         # next question index (0-based)
        "total": int,        # total number of questions
        "skip_count": int,   # how many times user has clicked "Plus tard"
        "should_show": bool, # frontend hint : auto-display the flow ?
        "completed_at": iso8601 | None,
        "skipped_at": iso8601 | None,
      }
    `should_show` = true if (not completed AND skip_count < SKIP_LIMIT).
    The frontend uses this to decide whether to take over /chat at login.
    """
    from app.database import async_session
    from app.models.user import User

    async with async_session() as db:
        u = await db.get(User, user_id)
        if u is None:
            return {
                "completed": False, "skipped": False, "step": 0,
                "total": len(QUESTIONS), "skip_count": 0, "should_show": True,
            }
        completed = u.onboarding_completed_at is not None
        skip_count = int(u.onboarding_skip_count or 0)
        return {
            "completed": completed,
            "skipped": u.onboarding_skipped_at is not None,
            "step": int(u.onboarding_step or 0),
            "total": len(QUESTIONS),
            "skip_count": skip_count,
            "should_show": (not completed) and (skip_count < SKIP_LIMIT),
            "completed_at": u.onboarding_completed_at.isoformat() if u.onboarding_completed_at else None,
            "skipped_at": u.onboarding_skipped_at.isoformat() if u.onboarding_skipped_at else None,
        }


async def get_next_question(user_id: str) -> dict | None:
    """Return the next question to ask the user, or None if onboarding is done.

    Shape :
      {
        "id": "preferred_name",
        "text": "Bonjour ! ...",
        "placeholder": "...",
        "step": 0,
        "total": 7,
        "skippable": True,
      }
    """
    status = await get_status(user_id)
    if status["completed"]:
        return None
    idx = status["step"]
    if idx >= len(QUESTIONS):
        return None
    q = QUESTIONS[idx]
    return {
        "id": q.id,
        "text": q.text,
        "placeholder": q.placeholder,
        "step": idx,
        "total": len(QUESTIONS),
        "skippable": q.skippable,
    }


async def record_answer(user_id: str, question_id: str, answer: str) -> dict:
    """Persist an answer and advance the user's onboarding cursor.

    Steps :
      1. Find the question by id (must match the current step — anti-replay)
      2. Run the question's `parse_and_store` logic to extract structured
         data into user_vocabulary + memory_manager
      3. Bump `User.onboarding_step` by +1 ; if last → set completed_at
      4. Return new status (so frontend can fetch the next question)

    Raises ValueError if `question_id` doesn't match the current step.
    """
    from app.database import async_session
    from app.models.user import User

    answer = (answer or "").strip()
    status = await get_status(user_id)
    if status["completed"]:
        raise ValueError("Onboarding déjà terminé.")

    cur_idx = status["step"]
    if cur_idx >= len(QUESTIONS):
        raise ValueError("Aucune question en attente.")

    q = QUESTIONS[cur_idx]
    if q.id != question_id:
        raise ValueError(
            f"Question ID '{question_id}' ne correspond pas à l'étape actuelle "
            f"'{q.id}'. Le frontend doit appeler /onboarding/next-question d'abord."
        )

    # Store the raw answer + extracted vocabulary
    if answer and answer.lower() not in {"rien", "aucune", "aucun", "skip", "passer", "non", "no", "n/a", "-"}:
        await _persist_answer(user_id, q, answer)

    # Advance cursor + maybe complete
    async with async_session() as db:
        u = await db.get(User, user_id)
        if u is None:
            raise ValueError("Utilisateur introuvable.")
        u.onboarding_step = cur_idx + 1
        if u.onboarding_step >= len(QUESTIONS):
            u.onboarding_completed_at = datetime.now(timezone.utc)
            u.onboarding_skipped_at = None  # cancel any prior skip
        await db.commit()

    return await get_status(user_id)


async def skip_onboarding(user_id: str) -> dict:
    """User clicked « Plus tard ». Stays in 'skipped' state — re-prompted at
    next login but no nag during the current session.

    After SKIP_LIMIT clicks, we stop re-prompting automatically — the user
    can still launch the flow manually via Settings."""
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        u = await db.get(User, user_id)
        if u is None:
            raise ValueError("Utilisateur introuvable.")
        u.onboarding_skipped_at = datetime.now(timezone.utc)
        u.onboarding_skip_count = int(u.onboarding_skip_count or 0) + 1
        await db.commit()
    return await get_status(user_id)


async def restart_onboarding(user_id: str) -> dict:
    """Wipe progress and start over. Existing user_vocabulary entries are
    KEPT (this lets the user refine, not reset entirely).

    Also resets `onboarding_skip_count` so the flow re-displays at next
    /chat visit (otherwise a user who skipped 3 times couldn't restart
    without a manual reset)."""
    from app.database import async_session
    from app.models.user import User
    async with async_session() as db:
        u = await db.get(User, user_id)
        if u is None:
            raise ValueError("Utilisateur introuvable.")
        u.onboarding_step = 0
        u.onboarding_completed_at = None
        u.onboarding_skipped_at = None
        u.onboarding_skip_count = 0
        await db.commit()
    return await get_status(user_id)


# ──────────────────────────────────────────────────────────────────────────────
# Persistence — split per question type so we can extend later
# ──────────────────────────────────────────────────────────────────────────────

# Regex for "term = value" or "term : value" or "term -> value"
_MAPPING_RE = re.compile(r"\s*([^=:→\->\n]+?)\s*(?:=|:|→|->)\s*([^;,\n]+)\s*")


async def _persist_answer(user_id: str, question: OnboardingQuestion, answer: str) -> None:
    """Dispatch by question id to the right storage strategy.

    Every answer is stored in two ways:
    1. As a semantic memory fact (Qdrant) — surfaced via RAG when contextually relevant.
    2. As a structured UserProfile row (SQLite) — immediately injected into every
       system prompt via get_user_context(), no need to wait for the cron consolidation.
    """
    # 1. Semantic memory (Qdrant) — use store_memory, not the non-existent store_fact
    try:
        from app.services.memory_manager import get_memory_manager
        await get_memory_manager().store_memory(
            content=f"[Onboarding/{question.id}] {answer[:500]}",
            user_id=user_id,
            extra_payload={"category": "preference", "source": "onboarding"},
        )
    except Exception as exc:
        logger.debug("Onboarding memory store failed: %s", exc)

    # 2. Structured UserProfile rows — available immediately in get_user_context()
    #    Map each question to the profile key that get_user_context() will inject.
    _profile_key_map: dict[str, str] = {
        "preferred_name": "user_name",
        "response_style": "response_style",
        "location":       "location",
        "profession":     "profession",
        "routines":       "routines",
        "strict_rules":   "strict_rules",
    }
    if question.id in _profile_key_map:
        await _upsert_user_profile(user_id, _profile_key_map[question.id], answer)

    # 3. Question-specific extraction → user_vocabulary (fast lookup for term mapping)
    try:
        if question.id == "vocabulary":
            await _store_vocab_mappings(user_id, question.domain, answer)
        elif question.id == "gmail_labels":
            await _store_label_terms(user_id, "gmail", answer)
        elif question.id == "calendars":
            await _store_label_terms(user_id, "calendar", answer)
        elif question.id == "preferred_name":
            await _store_single_vocab(user_id, "general", "préféré_nom_utilisateur", answer)
        elif question.id == "response_style":
            await _store_single_vocab(user_id, "general", "style_de_réponse_préféré", answer)
    except Exception as exc:
        logger.warning("Onboarding answer persistence failed for %s: %s", question.id, exc)


async def _upsert_user_profile(user_id: str, key: str, value: str) -> None:
    """Write (or overwrite) a UserProfile fact directly — bypasses the consolidation
    cron so data is available in the very next conversation turn."""
    try:
        from app.database import async_session
        from app.models.user_memory import UserProfile
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        async with async_session() as db:
            # Use INSERT OR REPLACE semantics via merge
            result = await db.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(UserProfile).where(
                    UserProfile.user_id == user_id,
                    UserProfile.key == key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                db.add(UserProfile(
                    user_id=user_id,
                    key=key,
                    value=value[:500],
                    confidence=1.0,
                    source_count=1,
                ))
            else:
                row.value = value[:500]
                row.confidence = 1.0
                row.source_count = (row.source_count or 0) + 1
            await db.commit()
    except Exception as exc:
        logger.warning("Onboarding UserProfile upsert failed for key=%s: %s", key, exc)


async def _store_vocab_mappings(user_id: str, domain: str, answer: str) -> None:
    """Parse 'term = value' style mappings and persist them.

    Accepts separators : `=`, `:`, `→`, `->`. Pairs separated by `;` or newline.
    Ex: "mes mailings = newsletters ; le boulot = Travail Pro"
    """
    from app.database import async_session
    from app.models.user_vocabulary import UserVocabulary

    pairs = _MAPPING_RE.findall(answer)
    if not pairs:
        # No structured mapping found → still store as a free-form note
        await _store_single_vocab(user_id, domain, "vocabulaire_libre", answer)
        return

    async with async_session() as db:
        for user_term, canonical in pairs:
            user_term = user_term.strip()
            canonical = canonical.strip()
            if not user_term or not canonical:
                continue
            await _upsert_vocabulary(db, user_id, domain, user_term, canonical)
        await db.commit()


async def _store_label_terms(user_id: str, domain: str, answer: str) -> None:
    """Store comma- or newline-separated labels as identity mappings.

    Ex: « Achats, Notifications, Personnel » →
      gmail/Achats        → Achats
      gmail/Notifications → Notifications
      gmail/Personnel     → Personnel
    The point is to ENROLL these terms so the agent knows they're
    relevant for this user (and can cite them when planning).
    """
    from app.database import async_session

    parts = re.split(r"[,\n;]", answer)
    async with async_session() as db:
        for raw in parts:
            term = raw.strip(" .-•")
            if not term or len(term) > 100:
                continue
            await _upsert_vocabulary(db, user_id, domain, term, term)
        await db.commit()


async def _store_single_vocab(user_id: str, domain: str, slug: str, value: str) -> None:
    from app.database import async_session
    async with async_session() as db:
        await _upsert_vocabulary(db, user_id, domain, slug, value)
        await db.commit()


async def _upsert_vocabulary(db, user_id: str, domain: str, user_term: str, canonical: str) -> None:
    """Insert or update a (user_id, user_term, domain) row."""
    from app.models.user_vocabulary import UserVocabulary
    existing = await db.execute(
        select(UserVocabulary).where(
            UserVocabulary.user_id == user_id,
            UserVocabulary.user_term == user_term,
            UserVocabulary.domain == domain,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = UserVocabulary(
            user_id=user_id,
            domain=domain,
            user_term=user_term[:200],
            canonical_term=canonical[:200],
            confidence=1.0,
        )
        db.add(row)
    else:
        row.canonical_term = canonical[:200]
        row.learned_at = datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
# Inference-time injection — called by the chat / mission system prompt builder
# ──────────────────────────────────────────────────────────────────────────────

async def get_vocabulary_for_prompt(user_id: str, max_entries: int = 30) -> str:
    """Return a Markdown-formatted block to inject in the system prompt.

    Empty string if the user has no vocabulary recorded yet.
    """
    if not user_id:
        return ""
    from app.database import async_session
    from app.models.user_vocabulary import UserVocabulary
    from sqlalchemy import desc

    async with async_session() as db:
        rows = (await db.execute(
            select(UserVocabulary)
            .where(UserVocabulary.user_id == user_id)
            .order_by(desc(UserVocabulary.learned_at))
            .limit(max_entries)
        )).scalars().all()

    if not rows:
        return ""

    # Group by domain for readability
    by_domain: dict[str, list[UserVocabulary]] = {}
    for r in rows:
        by_domain.setdefault(r.domain, []).append(r)

    lines = ["## Vocabulaire personnel de cet utilisateur (à respecter) :"]
    for domain, items in by_domain.items():
        lines.append(f"\n### {domain.capitalize()}")
        for r in items:
            if r.user_term == r.canonical_term:
                lines.append(f"- libellé/catégorie utilisé(e) : « {r.user_term} »")
            else:
                lines.append(f'- quand l\'utilisateur dit « {r.user_term} » il veut dire « {r.canonical_term} »')
    return "\n".join(lines)
