# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/memory/maintenance_rapid.py
# @brief      Sprint 2.5 Jalon 6 — event-driven memory consolidation agent.
#             Runs in fire-and-forget at the end of a conversation, extracts
#             3-5 salient facts via Ministral 3B local, and writes them
#             directly into the typed semantic-user store.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.3.0
# =============================================================================
"""Maintenance agent rapide — Sprint 2.5 §4 niveau 1.

Two-tier maintenance architecture (design note §4) :

  - **Niveau 1 (this module)** : event-driven, fires on WebSocket
    disconnect, runs in ~5 s on Ministral 3B local. Extracts the
    salient facts of the conversation that just ended and writes them
    directly to the typed `SemanticUserStore`. Goal : low latency,
    catches facts while the conversation context is fresh.

  - **Niveau 2 (existing `consolidate_user_memory` cron)** : runs twice
    a day (03:00 + 15:00) on the same MAINTENANCE tier, fuses raw
    `UserMemoryLog` entries into the consolidated `UserProfile`.
    Untouched by this jalon — keeps working for the legacy path.

Why two separate agents (decision validated by Franck 2026-05-21) : the
event-driven one is reactive and fine-grained ; the cron one re-examines
the accumulated raw logs and does deduplication / contradiction
resolution that would be wasted CPU after every single conversation.

Disable the rapid agent on weak hardware via env var ::

    MAINTENANCE_RAPID_DISABLED=true

The cron (Niveau 2) compensates : facts captured by the running
extract_and_store_facts pipeline still land in UserMemoryLog and get
consolidated nightly. Only the speedy update of the typed
SemanticUserStore is skipped.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from functools import lru_cache

from sqlalchemy import select

from app.database import async_session
from app.models.conversation import Message
from app.services.memory import get_semantic_user_store

logger = logging.getLogger(__name__)


# Prompt is intentionally identical in shape to the existing
# _EXTRACTION_PROMPT in memory_service.py — same JSON envelope so a
# future merge into a single extractor is straightforward.
_EXTRACTION_PROMPT = """\
Tu es un extracteur de faits silencieux. Voici la conversation qui vient \
de se terminer. Extrait 3 à 5 faits saillants sur l'utilisateur \
(préférences, projets, outils, contexte personnel, compétences, habitudes).

Réponds UNIQUEMENT avec un objet JSON de la forme :
{{
  "facts": [
    {{"fact": "L'utilisateur travaille sur un projet Python nommé ELY", "type": "context"}},
    {{"fact": "L'utilisateur préfère les réponses courtes", "type": "preference"}}
  ]
}}

Types valides : "preference", "context", "event", "skill", "personal"
Si aucun fait utile n'est détectable, réponds avec : {{"facts": []}}
N'invente AUCUN fait. N'extrait que ce qui est dit EXPLICITEMENT.
Maximum 5 facts. Chaque fact tient en 1-2 phrases (< 200 caractères).

Conversation :
{conversation}
"""


def _is_disabled() -> bool:
    """True if the rapid maintenance is turned off by env var."""
    return os.environ.get("MAINTENANCE_RAPID_DISABLED", "").lower() in (
        "1", "true", "yes", "on",
    )


def _strip_json_fences(raw: str) -> str:
    """Trim Markdown ``` fences a chatty LLM might wrap its JSON with."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _route_type_to_store_kind(fact_type: str) -> str:
    """Map the extractor's type tag to a SemanticUserStore write path.

    Returns one of :
      - "preference"  → store_preference (no decay, dedup)
      - "fact"        → store_fact (λ=0.01, with category in payload)
    """
    if fact_type == "preference":
        return "preference"
    # "context", "event", "skill", "personal" → fact (with category)
    return "fact"


class MaintenanceAgentRapid:
    """Sprint 2.5 §4 Niveau 1 — event-driven consolidator."""

    # Tunable defaults — kept on the class so a test can monkeypatch them
    # without reaching into module-level constants.
    MAX_MESSAGES_LOADED = 20
    MIN_MESSAGES_TO_RUN = 2

    async def consolidate(
        self,
        conversation_id: str,
        user_id: str,
    ) -> dict:
        """Extract facts from a just-ended conversation and store them.

        Never raises — best-effort, all errors swallowed and logged. The
        caller fires this with `asyncio.create_task` and never awaits.

        Returns a stats dict for tests/logs :
            {"status": "ok|skipped|failed", "preferences": N, "facts": N,
             "duration_ms": int, "reason": str?}
        """
        started = time.monotonic()

        if _is_disabled():
            return {"status": "skipped", "reason": "disabled"}
        if not user_id or not conversation_id:
            return {"status": "skipped", "reason": "missing_ids"}

        try:
            messages = await self._load_recent_messages(conversation_id)
        except Exception as exc:
            logger.debug("maintenance_rapid: SQL load failed: %s", exc)
            return {"status": "failed", "reason": "sql_load_failed"}

        if len(messages) < self.MIN_MESSAGES_TO_RUN:
            return {"status": "skipped", "reason": "too_short"}

        conversation_text = self._format_messages(messages)
        if not conversation_text:
            return {"status": "skipped", "reason": "empty_text"}

        try:
            facts = await self._extract_facts(conversation_text)
        except Exception as exc:
            logger.debug("maintenance_rapid: LLM call failed: %s", exc)
            return {"status": "failed", "reason": "llm_failed"}

        if not facts:
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                "status": "ok",
                "preferences": 0,
                "facts": 0,
                "duration_ms": duration_ms,
            }

        pref_count, fact_count = await self._store_facts(facts, user_id, conversation_id)

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "maintenance_rapid : user=%s conv=%s facts=%d preferences=%d duration=%dms",
            user_id, conversation_id, fact_count, pref_count, duration_ms,
        )
        return {
            "status": "ok",
            "preferences": pref_count,
            "facts": fact_count,
            "duration_ms": duration_ms,
        }

    # ── Helpers (kept small + monkeypatchable for tests) ───────────────

    async def _load_recent_messages(self, conversation_id: str) -> list:
        """Load the last N messages of a conversation, oldest-first."""
        async with async_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(self.MAX_MESSAGES_LOADED)
            )
            rows = list(result.scalars().all())
        # Reverse so the oldest message is first in the prompt — easier
        # for the extractor to track narrative.
        rows.reverse()
        return rows

    @staticmethod
    def _format_messages(messages: list) -> str:
        """Compact the message rows into the prompt-friendly conversation block."""
        parts: list[str] = []
        for msg in messages:
            role = getattr(msg, "role", "") or getattr(msg, "type", "")
            content = getattr(msg, "content", "") or ""
            if not isinstance(content, str) or not content.strip():
                continue
            role_label = "Utilisateur" if role in ("user", "human") else "Assistante"
            parts.append(f"{role_label}: {content[:500]}")
        return "\n".join(parts)

    async def _extract_facts(self, conversation_text: str) -> list[dict]:
        """Call the Ministral 3B tier and parse the JSON response.

        Wrapped so tests can monkeypatch this method to a fake list and
        skip the LLM round-trip entirely.
        """
        from app.services.llm_provider import ComplexityTier, get_llm_for_tier

        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)
        prompt = _EXTRACTION_PROMPT.format(conversation=conversation_text)
        # config={"callbacks": []} isolates this call from any active
        # LangGraph callback context so Ministral's tokens don't leak
        # into the user-visible chat stream.
        response = await llm.ainvoke(
            [{"role": "user", "content": prompt}],
            config={"callbacks": []},
        )
        raw = getattr(response, "content", "") or ""
        raw = _strip_json_fences(raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("maintenance_rapid: invalid JSON from LLM: %.200s", raw)
            return []
        facts = data.get("facts", []) if isinstance(data, dict) else []
        # Defensive cap — protects against a chatty model that ignores
        # the "max 5" instruction.
        return [f for f in facts if isinstance(f, dict)][:5]

    async def _store_facts(
        self,
        facts: list[dict],
        user_id: str,
        conversation_id: str,
    ) -> tuple[int, int]:
        """Dispatch each fact to its typed store. Returns (pref_count, fact_count)."""
        from app.services.memory_service import _is_safe_fact

        store = get_semantic_user_store()
        pref_count, fact_count = 0, 0

        for item in facts:
            text = str(item.get("fact", "")).strip()
            ftype = str(item.get("type", "context")).strip().lower()
            if not text:
                continue
            if not _is_safe_fact(text):
                logger.warning(
                    "maintenance_rapid: rejected possibly-injected fact user=%s : %.100s",
                    user_id, text,
                )
                continue

            kind = _route_type_to_store_kind(ftype)
            try:
                if kind == "preference":
                    # Sprint 2.5 Jalon 4 — routing explicite:
                    #     MemoryType  = SEMANTIC_USER (kind=preference)
                    #     Store       = SemanticUserStore.store_preference
                    await store.store_preference(text, user_id)
                    pref_count += 1
                else:
                    # Sprint 2.5 Jalon 4 — routing explicite:
                    #     MemoryType  = SEMANTIC_USER (kind=fact)
                    #     Store       = SemanticUserStore.store_fact
                    await store.store_fact(
                        content=text,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        extra_payload={
                            "category": ftype,
                            "source": "maintenance_rapid",
                        },
                    )
                    fact_count += 1
            except Exception as exc:
                logger.debug(
                    "maintenance_rapid: store failed for fact %r: %s", text[:60], exc
                )

        return pref_count, fact_count


@lru_cache(maxsize=1)
def get_maintenance_agent_rapid() -> MaintenanceAgentRapid:
    return MaintenanceAgentRapid()


# ──────────────────────────────────────────────────────────────────────
# Fire-and-forget wrapper for chat.py hook
# ──────────────────────────────────────────────────────────────────────


def schedule_consolidation(conversation_id: str, user_id: str) -> asyncio.Task | None:
    """Wrap `consolidate` in an `asyncio.create_task` with error swallowing.

    Returns the task so a test can await it deterministically ; production
    callers just discard the return value.
    """
    if _is_disabled():
        return None
    if not conversation_id or not user_id:
        return None

    async def _safe_run() -> None:
        try:
            await get_maintenance_agent_rapid().consolidate(conversation_id, user_id)
        except Exception as exc:
            logger.debug("maintenance_rapid schedule wrapper swallowed: %s", exc)

    return asyncio.create_task(_safe_run())
