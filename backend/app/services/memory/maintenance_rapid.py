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
# @license    Elastic License 2.0
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


# Prompt is intentionally identical in JSON shape to the existing
# _EXTRACTION_PROMPT in memory_service.py — same envelope so a future
# merge into a single extractor is straightforward. The instructions
# above the schema are tightened (2026-05-21) after Franck observed
# Ministral 3B mis-classifying hibiscus-tisane conversational details
# as "preferences" — confusing what happened in *this* conv with what
# is true of the user *in general*. The new rules + worked examples
# move borderline items to "context" or to nothing at all.
_EXTRACTION_PROMPT = """\
Tu es un extracteur de faits silencieux. Voici la conversation qui vient \
de se terminer. Extrait UNIQUEMENT les faits STABLES sur l'utilisateur — \
ceux qui resteront vrais dans toutes les conversations futures, \
indépendamment du sujet du jour.

Règles strictes :
1. Une PRÉFÉRENCE doit s'appliquer à TOUTES les conversations futures, \
pas seulement à celle-ci. Si elle est liée au sujet du jour, c'est du \
contexte ponctuel, pas une préférence stable.
2. Un CONTEXTE = un fait durable sur la vie de l'utilisateur (projet \
récurrent, famille, lieu, outil utilisé régulièrement).
3. Ignore : ce que l'assistante a dit, ce que l'utilisateur a demandé \
pour cette conv précise, et le sujet de la conv lui-même.
4. En cas de doute entre PRÉFÉRENCE et CONTEXTE, choisis CONTEXTE.
5. En cas de doute total, NE L'EXTRAIS PAS.
6. N'extrais JAMAIS l'état d'une tâche en cours (avancement, étape atteinte, « fait / à faire », statut d'une mission) : la mémoire retient qui est l'utilisateur, pas où en est le travail.

Exemples (à appliquer LITTÉRALEMENT) :
  ✓ PRÉFÉRENCE  : "L'utilisateur préfère le tutoiement"
  ✓ PRÉFÉRENCE  : "L'utilisateur veut des réponses courtes sans markdown"
  ✓ CONTEXTE    : "Sa femme apprécie les tisanes d'hibiscus"
  ✓ CONTEXTE    : "Il travaille sur un projet IA nommé ELY"
  ✗ À ÉVITER   : "A demandé des comparaisons gustatives" \
(juste cette conv, pas un trait stable)
  ✗ À ÉVITER   : "Veut des étapes structurées" \
(juste cette conv, pas une règle générale)
  ✗ À ÉVITER   : "Aime les détails botaniques" \
(sujet du jour, pas un trait stable)
  ✗ À ÉVITER   : un résumé en plusieurs phrases ou un paragraphe \
entier — chaque fact tient en UNE phrase courte sous 200 caractères, \
pas un résumé de conv

Réponds UNIQUEMENT avec un objet JSON :
{{
  "facts": [
    {{"fact": "L'utilisateur travaille sur un projet IA nommé ELY", "type": "context"}},
    {{"fact": "L'utilisateur préfère les réponses courtes sans markdown", "type": "preference"}}
  ]
}}

Types valides : "preference", "context", "event", "skill", "personal"
Si rien d'utile à extraire, réponds : {{"facts": []}}
Maximum 5 facts. Chaque fact tient en 1-2 phrases (< 200 caractères).
N'invente AUCUN fait. N'extrait que ce qui est dit EXPLICITEMENT.

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
    # Hard cap on the length of a single extracted fact. Anything longer
    # is rejected as a probable conversation summary (Ministral 3B
    # ignored the prompt's 200-char hint on 2026-05-21 — observed on a
    # hibiscus-tisane conv where it packed a whole 600-char recap into
    # a single `fact` field). `_is_safe_fact` in memory_service.py also
    # rejects > 500, but we want a tighter cap here so paragraphs never
    # reach the typed stores at all.
    MAX_FACT_CHARS = 250

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
            # user_id/conversation_id transmis pour que l'appel soit RATTACHABLE :
            # sans user_id la ligne d'usage n'est pas écrivable (clé étrangère).
            facts = await self._extract_facts(
                conversation_text, user_id, conversation_id,
            )
        except Exception as exc:
            logger.debug("maintenance_rapid: LLM call failed: %s", exc)
            return {"status": "failed", "reason": "llm_failed"}

        if not facts:
            # Even with no extractable facts, the user_state vector may have
            # drifted (mood / current_focus shift on a single message). Run
            # the refresh anyway before bailing.
            state_status = await self._refresh_user_state(user_id, conversation_id)
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                "status": "ok",
                "preferences": 0,
                "facts": 0,
                "user_state": state_status,
                "duration_ms": duration_ms,
            }

        pref_count, fact_count = await self._store_facts(facts, user_id, conversation_id)

        # Sprint 3 Jalon 2 — refresh the User State Vector after fact store.
        state_status = await self._refresh_user_state(user_id, conversation_id)

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "maintenance_rapid : user=%s conv=%s facts=%d preferences=%d user_state=%s duration=%dms",
            user_id, conversation_id, fact_count, pref_count, state_status, duration_ms,
        )
        return {
            "status": "ok",
            "preferences": pref_count,
            "facts": fact_count,
            "user_state": state_status,
            "duration_ms": duration_ms,
        }

    async def _refresh_user_state(self, user_id: str, conversation_id: str) -> str:
        """Best-effort refresh of the per-user state vector + frozen-memory
        invalidation. Returns one of ``"refreshed" | "skipped" | "failed"``
        for the upstream log line. Never raises — the maintenance pipeline
        must stay fire-and-forget."""
        try:
            from app.services.frozen_memory import invalidate as _fm_invalidate
            from app.services.learning.user_state import (
                compute_user_state, is_disabled as _us_disabled,
            )
            if _us_disabled():
                return "skipped"
            await compute_user_state(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            # Drop the cached snapshot so the next turn / next conversation
            # picks up the refreshed state. No-op if no entry was cached.
            _fm_invalidate(conversation_id)
            return "refreshed"
        except Exception as exc:
            logger.debug(
                "maintenance_rapid: user_state refresh failed conv=%s : %s",
                conversation_id, exc,
            )
            return "failed"

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

    async def _extract_facts(
        self, conversation_text: str, user_id: str = "",
        conversation_id: str | None = None,
    ) -> list[dict]:
        """Call the Ministral 3B tier and parse the JSON response.

        Wrapped so tests can monkeypatch this method to a fake list and
        skip the LLM round-trip entirely.
        """
        from app.services.llm_provider import ComplexityTier, get_llm_for_tier

        llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)
        # Le tier MAINTENANCE est local par défaut, mais c'est une
        # configuration d'administrateur : la conversation passe par un
        # masque, et les faits extraits se démasquent avec le même
        # dictionnaire (audit 02/09/2026, §9). Masque NEUF : cette corvée
        # tourne après la déconnexion, quand le filtre du tour a déjà quitté
        # le registre ; en réclamer un au registre en laisserait un orphelin.
        from app.services.security_filter import SecurityFilter
        _sf = SecurityFilter()
        prompt = _EXTRACTION_PROMPT.format(
            conversation=_sf.anonymize(conversation_text, ner_detection=False),
        )
        # config={"callbacks": []} isolates this call from any active
        # LangGraph callback context so Ministral's tokens don't leak
        # into the user-visible chat stream.
        # OPTIM — corvée de fond : pas de raisonnement (voir
        # services/background_llm.py). Le helper porte aussi l'isolation du
        # stream et le retrait d'un éventuel bloc <think> avant le parse.
        # `..._with_usage` plutôt qu'`ainvoke_background` : il rend AUSSI la
        # réponse brute, dont l'`usage_metadata`. L'isolation du stream met
        # cet appel hors de portée de `record_turn_usage`, qui compte au
        # niveau du tour — sans consignation propre, la corvée dépense hors
        # bilan (défaut diagnostiqué le 05/08).
        from app.services.background_llm import ainvoke_background_with_usage
        raw, _reponse = await ainvoke_background_with_usage(
            llm, [{"role": "user", "content": prompt}],
        )
        try:
            from app.services.analytics_service import log_response_usage
            from app.services.llm_provider import describe_llm

            _provider, _model = describe_llm(llm)
            await log_response_usage(
                user_id, _reponse, provider=_provider, model=_model,
                channel="background", skill_used="memory_maintenance",
                conversation_id=conversation_id,
            )
        except Exception as exc:  # noqa: BLE001 — consigner ne bloque jamais
            logger.debug("maintenance_rapid: usage non consigné (%s)", exc)
        raw = _strip_json_fences(_sf.deanonymize(raw))
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
            if len(text) > self.MAX_FACT_CHARS:
                # The model packed a paragraph-length summary into one
                # fact, ignoring the prompt's 200-char hint. Reject hard
                # so the typed stores never see a paragraph.
                logger.warning(
                    "maintenance_rapid: rejected over-long fact (%d chars) user=%s : %.80s...",
                    len(text), user_id, text,
                )
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

    # Laisse : un ``create_task`` nu que l'appelant jetait pouvait être
    # ramassé en vol (dernier cas du genre, relecture du 03/09/2026).
    from app.services.background_tasks import spawn
    return spawn(_safe_run(), label=f"maintenance-rapid-{conversation_id[:8]}")
