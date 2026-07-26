# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/routing_learning.py
# @brief      Self-improving router — learn keywords from user reformulations.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
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


# ===========================================================================
# Phase 2 — Auto-detection of user reformulations (background MAINTENANCE job)
# ===========================================================================
"""Detection des reformulations dans les conversations récentes.

Heuristique :
  - Paire de messages USER consécutifs dans la même conversation
  - Délai entre les deux < REFORMULATION_TIME_WINDOW_MIN (10 min par défaut)
  - Similarité (Jaccard sur tokens normalisés sans stop-words FR/EN) > 0.25
    OU présence d'un marqueur explicite de reformulation (« non plutôt »,
    « je voulais dire », « tu n'as pas compris », etc.)

Pour chaque paire détectée :
  - On re-route la query A et la query B via _quick_route
  - Si A et B routent vers des domaines différents → c'est probablement une
    correction utilisateur. On demande au LLM MAINTENANCE de proposer les
    keywords de A qui auraient dû matcher le domaine de B.
  - Chaque keyword extrait est inséré via propose_keyword() (auto-confirm
    après 3 occurrences identiques).

Le job est exécuté toutes les 6h (configurable via REFORMULATION_JOB_HOURS).
Idempotent : un curseur de timestamp évite de retraiter les mêmes paires.
"""

# Tunables
REFORMULATION_TIME_WINDOW_MIN = 10   # max gap between A and B for reformulation
REFORMULATION_MIN_JACCARD = 0.25     # token overlap threshold
REFORMULATION_LOOKBACK_HOURS = 24    # how far back to scan
REFORMULATION_BATCH_SIZE = 10        # max pairs analyzed per LLM call

_REFORM_MARKERS = (
    "non plutôt", "non en fait", "je voulais dire", "tu n'as pas compris",
    "ce n'est pas ce que", "reformule", "j'ai dit", "essaie plutôt",
    "non c'était", "pardon je voulais",
)

# Stop words minimal FR + EN — drop them before computing Jaccard so we don't
# inflate similarity on grammar tokens.
_STOPWORDS = {
    # FR
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "à", "au",
    "aux", "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "qui", "que", "quoi", "dont", "où", "est", "sont",
    "avec", "pour", "par", "sur", "sous", "dans", "en", "y", "se", "me",
    "moi", "te", "toi", "il", "elle", "ils", "elles", "on", "nous", "vous",
    "n'", "s'", "l'", "d'", "j'", "t'", "qu'", "c'",
    # EN
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "this", "that", "these", "those",
}


def _tokenize(s: str) -> set[str]:
    """Lowercase + strip punctuation + drop stop words. Returns set of tokens."""
    if not s:
        return set()
    cleaned = re.sub(r"[^\w\s'àâäéèêëïîôöùûüÿçñœæ-]", " ", s.lower(), flags=re.UNICODE)
    tokens = {t for t in cleaned.split() if len(t) > 1 and t not in _STOPWORDS}
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_reformulation(query_a: str, query_b: str) -> tuple[bool, str]:
    """Decide if query_b is a reformulation of query_a.

    Returns (is_reform, reason) where reason is 'marker', 'overlap', or ''.
    """
    if not query_a or not query_b:
        return False, ""
    b_lower = query_b.lower()
    if any(m in b_lower for m in _REFORM_MARKERS):
        return True, "marker"
    sim = _jaccard(_tokenize(query_a), _tokenize(query_b))
    if sim >= REFORMULATION_MIN_JACCARD:
        return True, f"overlap({sim:.2f})"
    return False, ""


async def _find_reformulation_pairs(lookback_hours: int = REFORMULATION_LOOKBACK_HOURS) -> list[dict]:
    """Scan recent conversations for query/reformulation pairs.

    Returns a list of {conv_id, user_id, query_a, query_b, ts_a, ts_b, reason}
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.database import async_session
    from app.models.conversation import Message, Conversation

    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    pairs: list[dict] = []

    async with async_session() as db:
        # Group user messages by conversation, sorted by created_at
        rows = (await db.execute(
            select(Message, Conversation.user_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.created_at >= since, Message.role == "user")
            .order_by(Message.conversation_id, Message.created_at)
        )).all()

    by_conv: dict[str, list[tuple]] = {}
    for msg, uid in rows:
        by_conv.setdefault(msg.conversation_id, []).append((msg, uid))

    window = timedelta(minutes=REFORMULATION_TIME_WINDOW_MIN)
    for conv_id, items in by_conv.items():
        for i in range(len(items) - 1):
            msg_a, uid_a = items[i]
            msg_b, uid_b = items[i + 1]
            if (msg_b.created_at - msg_a.created_at) > window:
                continue
            is_ref, reason = _is_reformulation(msg_a.content or "", msg_b.content or "")
            if not is_ref:
                continue
            pairs.append({
                "conv_id": conv_id,
                "user_id": uid_a,
                "query_a": (msg_a.content or "")[:500],
                "query_b": (msg_b.content or "")[:500],
                "ts_a": msg_a.created_at,
                "ts_b": msg_b.created_at,
                "reason": reason,
            })
    return pairs


# Cursor (timestamp of last processed pair) — kept in memory between runs.
# Resets on backend restart, which means up to lookback_hours of duplicate
# work after a reboot — acceptable since propose_keyword() is idempotent
# (existing rows just get confidence++).
_last_processed_ts: Optional[object] = None  # datetime


async def analyze_reformulations_tick() -> dict:
    """One iteration of the reformulation analysis job.

    Steps :
      1. Find candidate pairs in the last REFORMULATION_LOOKBACK_HOURS hours.
      2. Filter to those where _quick_route(A) != _quick_route(B) — i.e. the
         router really changed its mind, suggesting A was misrouted.
      3. Ask the MAINTENANCE LLM to extract from A the keywords that should
         have routed to the domain matched by B.
      4. Insert each extracted keyword via propose_keyword() — auto-promoted
         after AUTO_CONFIRM_THRESHOLD identical proposals.

    Returns a small status dict for logs / monitoring.
    """
    global _last_processed_ts
    started_at = datetime.now(timezone.utc)
    pairs = await _find_reformulation_pairs()

    # Skip pairs older than the cursor (already processed)
    if _last_processed_ts is not None:
        pairs = [p for p in pairs if p["ts_b"] > _last_processed_ts]

    if not pairs:
        return {"status": "ok", "pairs_found": 0, "keywords_proposed": 0}

    # V1 temps 2 (26/07) — CETTE BOUCLE N'A PLUS DE CONSOMMATEUR.
    #
    # Elle apprenait des mots-clés pour la passe rapide du ROUTEUR, afin
    # d'éviter la passe LLM coûteuse. Le routeur a été supprimé avec
    # `supervisor.py` : plus rien ne lit `learned_routing_keywords`, et la
    # table comptait de toute façon 0 ligne en production.
    #
    # L'audit posait la règle « rien ne se produit sans consommateur » : on
    # s'arrête donc ici plutôt que de dépenser des appels LLM pour une
    # sortie que personne ne lira. La suppression complète du service (587 l.
    # + page de réglages + table) touche le frontend et fera l'objet d'un
    # lot séparé.
    return {
        "status": "disabled",
        "reason": "consommateur supprimé avec le routeur (V1 temps 2)",
        "pairs_found": len(pairs),
        "keywords_proposed": 0,
    }
    diverging: list[dict] = []  # noqa: F841 — conservé pour le lot de suppression

    if not diverging:
        _last_processed_ts = max(p["ts_b"] for p in pairs)
        return {"status": "ok", "pairs_found": len(pairs), "diverging": 0, "keywords_proposed": 0}

    # Step 3: batch-ask the MAINTENANCE LLM for keyword extractions
    proposed = 0
    for batch_start in range(0, len(diverging), REFORMULATION_BATCH_SIZE):
        batch = diverging[batch_start:batch_start + REFORMULATION_BATCH_SIZE]
        try:
            extractions = await _llm_extract_keywords(batch)
        except Exception as exc:
            logger.warning("Routing learning: LLM extraction failed for batch: %s", exc)
            continue
        for ex in extractions:
            try:
                r = await propose_keyword(
                    keyword=ex["keyword"],
                    domain=ex["domain"],
                    user_id=ex.get("user_id"),
                    rationale=ex.get("rationale"),
                )
                if r:
                    proposed += 1
            except Exception as exc:
                logger.debug("propose_keyword failed for %r: %s", ex, exc)

    _last_processed_ts = max(p["ts_b"] for p in pairs)
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "Routing learning tick: %d pairs, %d diverging, %d keywords proposed (%.1fs)",
        len(pairs), len(diverging), proposed, elapsed,
    )
    return {
        "status": "ok",
        "pairs_found": len(pairs),
        "diverging": len(diverging),
        "keywords_proposed": proposed,
        "elapsed_s": round(elapsed, 1),
    }


async def _llm_extract_keywords(pairs: list[dict]) -> list[dict]:
    """Use the MAINTENANCE LLM to extract missing keywords from misrouted queries.

    Input : list of {query_a, query_b, dom_a, dom_b, user_id}.
    Output : list of {keyword, domain, user_id, rationale}.
    """
    import json
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.services.llm_provider import get_llm_for_tier, ComplexityTier

    if not pairs:
        return []

    sys_prompt = (
        "Tu es un analyseur de routage. Tu reçois des paires de messages user "
        "où le second est une reformulation du premier (que le routeur n'a "
        "pas compris du premier coup). Pour chaque paire, identifie 1-3 mots "
        "ou expressions courtes (2-4 mots max) du PREMIER message qui auraient "
        "dû déclencher le routage vers le domaine 'expected_domain' (= celui "
        "où la reformulation est partie). Privilégie les abréviations, le "
        "vocabulaire métier, les expressions familières. Évite les mots "
        "génériques (« supprime », « envoie », « cherche »).\n\n"
        "Réponse format JSON strict, sans markdown :\n"
        '{"extractions": [{"pair_index": 0, "keyword": "...", "domain": "...", '
        '"rationale": "..."}, ...]}\n\n'
        "Si une paire n'apporte aucun keyword utile (ex : reformulation "
        "trop similaire, simple typo), n'émets rien pour cette pair_index."
    )

    user_prompt_lines = []
    for i, p in enumerate(pairs):
        user_prompt_lines.append(
            f"--- PAIR {i} ---\n"
            f"query_misrouted (routée à tort sur '{p.get('dom_a') or 'general'}'): {p['query_a']!r}\n"
            f"reformulation     (routée correctement sur '{p['dom_b']}'): {p['query_b']!r}\n"
            f"expected_domain  : {p['dom_b']}"
        )
    user_prompt = "\n\n".join(user_prompt_lines)

    llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)
    msg = await llm.ainvoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_prompt),
    ])
    content = msg.content if isinstance(msg.content, str) else str(msg.content)

    # Strip code fences if any LLM still emits them
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(content)
        extractions_raw = data.get("extractions", [])
    except Exception as exc:
        logger.warning("Routing learning: LLM returned non-JSON: %s — content[:200]=%s", exc, content[:200])
        return []

    out: list[dict] = []
    for ex in extractions_raw:
        idx = ex.get("pair_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(pairs):
            continue
        kw = (ex.get("keyword") or "").strip()
        dom = (ex.get("domain") or "").strip()
        if not kw or dom not in _VALID_DOMAINS:
            continue
        out.append({
            "keyword": kw,
            "domain": dom,
            "user_id": pairs[idx].get("user_id"),  # per-user (safer than global)
            "rationale": ex.get("rationale") or f"auto-extracted from reformulation in conv {pairs[idx]['conv_id'][:8]}",
        })
    return out
