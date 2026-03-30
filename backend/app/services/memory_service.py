"""User memory service — episodic fact extraction and profile consolidation.

This service provides three async entry points:

    extract_and_store_facts()  — called after each agent response (fire-and-forget)
    get_user_context()         — injects a user profile summary into system prompts
    consolidate_user_memory()  — nightly job: merges logs into UserProfile
    consolidate_all_users()    — called by APScheduler at 3 AM
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import async_session
from app.models.user_memory import UserMemoryLog, UserProfile

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
Tu es un extracteur de faits silencieux. Analyse la conversation suivante et extrait \
les faits importants sur l'utilisateur (préférences, projets, outils, contexte personnel, \
compétences, habitudes).

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

Conversation :
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
- Confidence entre 0.0 et 1.0
"""


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

async def extract_and_store_facts(
    user_id: str,
    conversation_id: str,
    messages: list,
) -> None:
    """Extract key facts from a conversation and store them as UserMemoryLog entries.

    Uses Ollama (Tier 1) for extraction — fast, free, local.
    This function is designed to be called as fire-and-forget; it swallows all errors.
    """
    if not user_id or not messages:
        return

    try:
        # Build a compact conversation string (last N messages only)
        conversation_parts: list[str] = []
        for msg in messages[-10:]:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                role_label = "Utilisateur" if role == "human" else "Assistante"
                conversation_parts.append(f"{role_label}: {content[:500]}")

        if not conversation_parts:
            return

        conversation_text = "\n".join(conversation_parts)

        # Use MAINTENANCE tier (configurable via Settings → Niveaux de routage)
        from app.services.llm_provider import get_llm_for_tier, ComplexityTier
        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)

        prompt = _EXTRACTION_PROMPT.format(conversation=conversation_text)
        # config={"callbacks": []} isolates this call from any active LangGraph
        # callback context (propagated via contextvars through ensure_future).
        # Without this, Ollama's tokens would leak into the active chat stream.
        response = await llm.ainvoke(
            [{"role": "user", "content": prompt}],
            config={"callbacks": []},
        )
        raw = getattr(response, "content", "") or ""

        # Parse JSON response
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        facts = data.get("facts", [])

        if not facts:
            return

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
            await db.commit()

        logger.debug("Extracted %d facts for user %s", len(facts), user_id)

    except json.JSONDecodeError:
        logger.debug("extract_and_store_facts: could not parse JSON response — skipping")
    except Exception as exc:
        logger.debug("extract_and_store_facts failed silently: %s", exc)


# ---------------------------------------------------------------------------
# Context retrieval
# ---------------------------------------------------------------------------

async def get_user_context(user_id: str, limit: int = 20) -> str:
    """Return a formatted string of user profile facts for injection into system prompts.

    Returns an empty string if no profile exists yet (graceful degradation).
    """
    if not user_id:
        return ""

    try:
        async with async_session() as db:
            # Fetch top entries ordered by confidence × source_count descending
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
                .limit(limit)
            )
            rows: list[UserProfile] = list(result.scalars().all())

        if not rows:
            return ""

        lines = ["Ce que tu sais sur cet utilisateur :"]
        for row in rows:
            lines.append(f"- {row.key} : {row.value}")

        return "\n".join(lines)

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
        async with async_session() as db:
            result = await db.execute(
                select(UserMemoryLog)
                .where(UserMemoryLog.user_id == user_id)
                .where(UserMemoryLog.is_consolidated == False)  # noqa: E712
                .order_by(UserMemoryLog.observed_at)
                .limit(200)
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
        response = await llm.ainvoke(
            [{"role": "user", "content": prompt}],
            config={"callbacks": []},
        )
        raw = getattr(response, "content", "") or ""

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
