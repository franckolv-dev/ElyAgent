# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/routing_learning.py
# @brief      Self-improving router — learn keywords from user reformulations.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Self-improving router via reformulation analysis.

Architecture :
  - Cache mémoire (per-user) : { user_id: { domain: [keyword, …] } }
  - Loaded at startup + refreshed after every CRUD on the table.
  - `match_learned_keywords(msg, user_id)` is called from `_quick_route` AFTER
    the hardcoded patterns. If a keyword matches, the corresponding domain is
    added to the matched_domains list (same multi-domain logic applies).
  - `propose_keyword(...)` and `confirm_keyword(...)` are the two write paths :
    the maintenance LLM job uses them to gradually grow the dictionary.

Threshold logic (auto-confirmation) :
  - When a keyword is auto-proposed for the first time, ``source='auto-proposed'``,
    ``active=False``, ``confidence=1``.
  - Each subsequent observation of the same (user_id, keyword, domain) increments
    ``confidence``.
  - When ``confidence >= AUTO_CONFIRM_THRESHOLD`` (currently 3), the row flips to
    ``source='auto-confirmed'`` and ``active=True`` — the live router uses it.
  - Manual entries skip this : ``source='manual'`` is always ``active=True``.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

logger = logging.getLogger(__name__)

# A keyword is auto-promoted to active after this many confirmations.
AUTO_CONFIRM_THRESHOLD = 3

# In-memory cache. Refreshed on startup and after each CRUD via this module.
# Shape: { (user_id_or_None): { domain: [keyword, …] } }
# Per-user keywords always include None entries (global keywords) when the
# router queries for a specific user.
_cache: dict[Optional[str], dict[str, list[str]]] = {}


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

async def reload_cache() -> None:
    """Reload all active keywords from DB into the in-memory cache."""
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    new_cache: dict[Optional[str], dict[str, list[str]]] = {}
    async with async_session() as db:
        rows = (await db.execute(
            select(LearnedRoutingKeyword).where(LearnedRoutingKeyword.active.is_(True))
        )).scalars().all()
    for row in rows:
        bucket = new_cache.setdefault(row.user_id, {})
        bucket.setdefault(row.domain, []).append(row.keyword.lower())
    global _cache
    _cache = new_cache
    n_global = sum(len(v) for v in (_cache.get(None) or {}).values())
    n_per_user = sum(
        len(kws) for uid, dom_map in _cache.items() if uid is not None
        for kws in dom_map.values()
    )
    logger.info(
        "Routing learning cache reloaded: %d global keywords, %d per-user keywords across %d users",
        n_global, n_per_user, max(0, len(_cache) - (1 if None in _cache else 0)),
    )


def match_learned_keywords(msg: str, user_id: Optional[str] = None) -> list[str]:
    """Return the list of domains matched by learned keywords for this query.

    Checks (a) the user's own keywords if ``user_id`` is given, then (b) the
    global keywords. Word-boundary case-insensitive substring match.
    Returns a deduped list, or [] if nothing matched.
    """
    if not msg:
        return []
    lower = msg.lower()
    matched: list[str] = []

    def _scan(bucket: dict[str, list[str]]) -> None:
        for domain, kws in bucket.items():
            if domain in matched:
                continue
            for kw in kws:
                # Word-boundary test for short keywords (avoid « doc » matching « docteur »).
                # For multi-word phrases (with spaces), substring check is enough.
                if " " in kw:
                    if kw in lower:
                        matched.append(domain)
                        break
                else:
                    if re.search(rf"\b{re.escape(kw)}\b", lower):
                        matched.append(domain)
                        break

    if user_id and user_id in _cache:
        _scan(_cache[user_id])
    if None in _cache:
        _scan(_cache[None])
    return matched


# ---------------------------------------------------------------------------
# Write paths — manual + auto
# ---------------------------------------------------------------------------

async def add_manual_keyword(
    keyword: str, domain: str, user_id: Optional[str], rationale: str | None = None
) -> dict:
    """Insert a manually-entered keyword (admin path). Always active."""
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    keyword_clean = (keyword or "").strip().lower()
    if not keyword_clean:
        raise ValueError("keyword must not be empty")
    if len(keyword_clean) < 2:
        raise ValueError("keyword too short (min 2 chars)")
    if domain not in _VALID_DOMAINS:
        raise ValueError(f"invalid domain '{domain}', must be one of {_VALID_DOMAINS}")

    async with async_session() as db:
        existing = (await db.execute(
            select(LearnedRoutingKeyword).where(
                LearnedRoutingKeyword.user_id.is_(user_id) if user_id is None
                else LearnedRoutingKeyword.user_id == user_id,
                LearnedRoutingKeyword.keyword == keyword_clean,
                LearnedRoutingKeyword.domain == domain,
            )
        )).scalar_one_or_none()
        if existing:
            existing.active = True
            existing.source = "manual"
            existing.rationale = rationale or existing.rationale
            row = existing
        else:
            row = LearnedRoutingKeyword(
                keyword=keyword_clean,
                domain=domain,
                user_id=user_id,
                source="manual",
                confidence=AUTO_CONFIRM_THRESHOLD,  # bypass auto-promotion
                active=True,
                rationale=rationale,
            )
            db.add(row)
        await db.commit()
        await db.refresh(row)
    await reload_cache()
    logger.info("Added manual routing keyword: %r → %s (user_id=%s)", keyword_clean, domain, user_id)
    return _row_to_dict(row)


async def propose_keyword(
    keyword: str, domain: str, user_id: Optional[str], rationale: str | None = None
) -> dict:
    """Insert (or increment) an auto-proposed keyword. Activates if threshold reached."""
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    keyword_clean = (keyword or "").strip().lower()
    if not keyword_clean or domain not in _VALID_DOMAINS:
        return {}

    async with async_session() as db:
        existing = (await db.execute(
            select(LearnedRoutingKeyword).where(
                LearnedRoutingKeyword.user_id.is_(user_id) if user_id is None
                else LearnedRoutingKeyword.user_id == user_id,
                LearnedRoutingKeyword.keyword == keyword_clean,
                LearnedRoutingKeyword.domain == domain,
            )
        )).scalar_one_or_none()

        if existing:
            existing.confidence += 1
            if existing.confidence >= AUTO_CONFIRM_THRESHOLD and not existing.active:
                existing.active = True
                existing.source = "auto-confirmed"
                logger.info(
                    "Auto-confirmed routing keyword: %r → %s (user_id=%s, confidence=%d)",
                    keyword_clean, domain, user_id, existing.confidence,
                )
            row = existing
        else:
            row = LearnedRoutingKeyword(
                keyword=keyword_clean,
                domain=domain,
                user_id=user_id,
                source="auto-proposed",
                confidence=1,
                active=False,
                rationale=rationale,
            )
            db.add(row)
        await db.commit()
        await db.refresh(row)
    if row.active:
        await reload_cache()
    return _row_to_dict(row)


async def list_keywords(user_id: Optional[str] = None, include_inactive: bool = False) -> list[dict]:
    """List all learned keywords. Admin endpoint helper."""
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    async with async_session() as db:
        q = select(LearnedRoutingKeyword)
        if user_id is not None:
            q = q.where(LearnedRoutingKeyword.user_id == user_id)
        if not include_inactive:
            q = q.where(LearnedRoutingKeyword.active.is_(True))
        rows = (await db.execute(q.order_by(LearnedRoutingKeyword.created_at.desc()))).scalars().all()
    return [_row_to_dict(r) for r in rows]


async def delete_keyword(keyword_id: str) -> bool:
    """Delete a keyword by ID. Returns True if a row was deleted."""
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    async with async_session() as db:
        row = (await db.execute(
            select(LearnedRoutingKeyword).where(LearnedRoutingKeyword.id == keyword_id)
        )).scalar_one_or_none()
        if not row:
            return False
        await db.delete(row)
        await db.commit()
    await reload_cache()
    return True


async def mark_match(keyword: str, domain: str, user_id: Optional[str] = None) -> None:
    """Update last_matched_at when a learned keyword fires successfully.

    Called by the supervisor *after* it has resolved that the routed domain
    is the one the user actually wanted (no immediate reformulation).
    """
    from app.database import async_session
    from app.models.learned_routing_keyword import LearnedRoutingKeyword

    keyword_clean = (keyword or "").strip().lower()
    if not keyword_clean:
        return
    async with async_session() as db:
        await db.execute(
            update(LearnedRoutingKeyword)
            .where(
                LearnedRoutingKeyword.keyword == keyword_clean,
                LearnedRoutingKeyword.domain == domain,
                (LearnedRoutingKeyword.user_id == user_id) if user_id is not None
                else LearnedRoutingKeyword.user_id.is_(None),
            )
            .values(last_matched_at=datetime.now(timezone.utc))
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DOMAINS = {
    "research", "workspace", "infra", "creative", "data", "memory",
    "desktop", "general",
}


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "keyword": row.keyword,
        "domain": row.domain,
        "source": row.source,
        "confidence": row.confidence,
        "active": row.active,
        "last_matched_at": row.last_matched_at.isoformat() if row.last_matched_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "rationale": row.rationale,
    }
