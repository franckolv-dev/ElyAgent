# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/user_state.py
# @brief      Sprint 3 Jalon 1 — User State Vector service.
#             Reads, writes and refreshes the per-user state JSON
#             (mood / current_focus / recent_topics / open_loops /
#             energy_budget). Refresh uses the MAINTENANCE LLM (Gemma 4
#             E4B local) ; failures never propagate to the caller.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# @version    1.6.0
# =============================================================================
"""User State Vector — Sprint 3 §3.

Public API ::

    DEFAULT_STATE        — canonical empty state ; every field present.
    get_user_state(uid)  — read + merge with defaults so callers always
                           get a full dict (no missing keys).
    set_user_state(uid, state)
                         — upsert the JSON document.
    compute_user_state(uid, conversation_id)
                         — call the MAINTENANCE LLM on recent messages,
                           parse, merge with current state, persist.
                           Best-effort : on any failure returns the
                           pre-existing state untouched.
    format_user_state_block(state) -> str
                         — render the JSON as a `<user_state>...</user_state>`
                           XML-style block ready to be glued into the
                           system prompt (Sprint 3 Jalon 2 will call this).

Three invariants :

  1. **Never raise out of the service.** Every public function swallows
     LLM / DB errors. The caller (chat router, maintenance agent, UI)
     must keep working even when the state subsystem is broken.
  2. **Idempotent merge.** `set_user_state` with a partial dict only
     overwrites the keys present ; missing keys keep their previous
     value. Lets callers update one field without re-sending all.
  3. **Single row per user.** ``user_id`` is the PK ; we never INSERT
     a duplicate. First write creates, subsequent writes update.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models.user_state import UserState
from app.services.learning.prompt_version import current_system_prompt_version

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Canonical schema
# ─────────────────────────────────────────────────────────────────────────


DEFAULT_STATE: dict[str, Any] = {
    "mood": "neutral",
    "current_focus": "",
    "recent_topics": [],
    "open_loops": [],
    "energy_budget": "normal",
}


# Tunable bounds — the LLM extractor sometimes produces verbose output ;
# we clip defensively so a chatty model can't blow up the system prompt.
MAX_TOPIC_CHARS: int = 80
MAX_LOOP_CHARS: int = 120
MAX_FOCUS_CHARS: int = 160
MAX_LIST_LEN: int = 5
ALLOWED_ENERGY: frozenset[str] = frozenset({"high", "normal", "low"})


def _merge_with_defaults(partial: dict[str, Any]) -> dict[str, Any]:
    """Return DEFAULT_STATE | partial, but bounded :
       - lists capped to MAX_LIST_LEN entries, each string capped
       - strings capped to their MAX_*_CHARS
       - energy_budget validated against ALLOWED_ENERGY
    Anything else is silently coerced to its default."""
    out = dict(DEFAULT_STATE)
    if not isinstance(partial, dict):
        return out

    if isinstance(partial.get("mood"), str):
        out["mood"] = partial["mood"].strip()[:MAX_TOPIC_CHARS] or "neutral"

    if isinstance(partial.get("current_focus"), str):
        out["current_focus"] = partial["current_focus"].strip()[:MAX_FOCUS_CHARS]

    if isinstance(partial.get("recent_topics"), list):
        out["recent_topics"] = [
            str(t).strip()[:MAX_TOPIC_CHARS]
            for t in partial["recent_topics"]
            if t is not None and isinstance(t, (str, int, float)) and str(t).strip()
        ][:MAX_LIST_LEN]

    if isinstance(partial.get("open_loops"), list):
        out["open_loops"] = [
            str(t).strip()[:MAX_LOOP_CHARS]
            for t in partial["open_loops"]
            if t is not None and isinstance(t, (str, int, float)) and str(t).strip()
        ][:MAX_LIST_LEN]

    eb = str(partial.get("energy_budget", "")).strip().lower()
    if eb in ALLOWED_ENERGY:
        out["energy_budget"] = eb

    return out


# ─────────────────────────────────────────────────────────────────────────
# Read / write
# ─────────────────────────────────────────────────────────────────────────


async def get_user_state(user_id: str) -> dict[str, Any]:
    """Return the user's state, always with every key (filled with
    defaults if the row is missing or its JSON is corrupt)."""
    if not user_id:
        return dict(DEFAULT_STATE)
    try:
        async with async_session() as db:
            row = (await db.execute(
                select(UserState).where(UserState.user_id == user_id)
            )).scalar_one_or_none()
    except Exception as exc:
        logger.debug("user_state: SQL read failed user=%s : %s", user_id, exc)
        return dict(DEFAULT_STATE)

    if row is None or not row.state_json:
        return dict(DEFAULT_STATE)

    try:
        parsed = json.loads(row.state_json)
    except json.JSONDecodeError:
        logger.warning(
            "user_state: corrupt JSON for user=%s, returning defaults", user_id
        )
        return dict(DEFAULT_STATE)

    return _merge_with_defaults(parsed)


async def set_user_state(
    user_id: str,
    partial_state: dict[str, Any],
    *,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Upsert ``partial_state`` into the user's row.

    Returns the FINAL merged state actually written (so callers can
    show "here's what I learned"). Idempotent : calling twice with the
    same input does the same thing.

    Missing keys in ``partial_state`` keep their previous value — this
    is what lets the maintenance LLM update one field at a time.
    """
    if not user_id:
        return dict(DEFAULT_STATE)

    # Load existing so we merge instead of overwrite ↳ the LLM may have
    # returned only the fields it could confidently update.
    current = await get_user_state(user_id)
    merged_input = dict(current)
    if isinstance(partial_state, dict):
        for k, v in partial_state.items():
            if v is not None:
                merged_input[k] = v
    new_state = _merge_with_defaults(merged_input)

    pv = prompt_version
    if pv is None:
        try:
            pv = current_system_prompt_version()
        except Exception:
            pv = None

    try:
        async with async_session() as db:
            row = (await db.execute(
                select(UserState).where(UserState.user_id == user_id)
            )).scalar_one_or_none()
            payload = json.dumps(new_state, ensure_ascii=False)
            if row is None:
                row = UserState(
                    user_id=user_id,
                    state_json=payload,
                    prompt_version=pv,
                )
                db.add(row)
            else:
                row.state_json = payload
                row.prompt_version = pv
            await db.commit()
    except Exception as exc:
        logger.debug("user_state: SQL write failed user=%s : %s", user_id, exc)
        # Don't propagate — the caller gets the merged state in-memory
        # and life goes on. Next refresh attempt will retry the write.

    return new_state


# ─────────────────────────────────────────────────────────────────────────
# LLM refresh
# ─────────────────────────────────────────────────────────────────────────


# Kept module-level so a test can monkeypatch the constant without having
# to touch the function body.
_REFRESH_PROMPT_TEMPLATE = """Tu es l'agent MAINTENANCE d'ELY. Tu produis un état JSON de l'utilisateur en français à partir d'une conversation récente. RIEN d'autre — pas de prose, pas de ```json fences.

ÉTAT ACTUEL (à mettre à jour, pas à recréer de zéro) :
{current_state}

CONVERSATION RÉCENTE (oldest-first) :
{conversation}

CONSIGNES STRICTES :
- Sortie : un JSON object avec EXACTEMENT ces clés :
  {{"mood": str, "current_focus": str, "recent_topics": [str], "open_loops": [str], "energy_budget": "high"|"normal"|"low"}}
- `mood` : un seul mot (français), ton affectif perçu — ex. "focused", "fatigué", "joueur", "stressé".
- `current_focus` : phrase courte (max 160 chars) décrivant ce qui occupe l'utilisateur en ce moment.
- `recent_topics` : 3 à 5 sujets distincts abordés. Mots-clés courts (max 80 chars), pas de phrases.
- `open_loops` : 0 à 5 fils non résolus que tu as captés (questions en suspens, TODO implicites).
- `energy_budget` : "high" (l'utilisateur veut creuser), "normal" (échange standard), "low" (réponses courtes attendues).
- Si une info te manque ou est inchangée, RECOPIE la valeur actuelle. Ne mets pas null.

Réponds UNIQUEMENT par le JSON.
"""


async def compute_user_state(
    user_id: str,
    conversation_id: str | None = None,
    *,
    messages: list | None = None,
    llm: Any = None,
) -> dict[str, Any]:
    """Refresh the user's state from a recent conversation slice.

    Best-effort end-to-end :
      - If the LLM call fails → returns current state untouched.
      - If JSON parsing fails → returns current state untouched.
      - On success → merged + persisted state.

    Parameters
    ----------
    user_id :
        Whose state to refresh.
    conversation_id :
        Source conversation for the recent-messages slice. If ``None``
        and ``messages`` is also ``None``, the function refreshes purely
        from the current persisted state (essentially a no-op LLM call
        with empty context — useful for tests).
    messages :
        Pre-loaded list of messages. When provided, ``conversation_id``
        is ignored. Lets tests inject deterministic input.
    llm :
        Optional LLM override. If ``None``, the MAINTENANCE tier LLM is
        resolved lazily via ``llm_provider.get_llm_for_tier``.
    """
    started = time.monotonic()
    current = await get_user_state(user_id)

    if not user_id:
        return current

    # Resolve message slice
    try:
        if messages is None and conversation_id:
            messages = await _load_recent_messages(conversation_id)
    except Exception as exc:
        logger.debug("user_state: message load failed conv=%s : %s", conversation_id, exc)
        return current

    conversation_text = _format_messages(messages or [])
    if not conversation_text:
        # Nothing to learn from — keep current state as-is.
        return current

    # Resolve LLM
    if llm is None:
        try:
            from app.services.llm_provider import ComplexityTier, get_llm_for_tier
            llm = get_llm_for_tier(ComplexityTier.MAINTENANCE)
        except Exception as exc:
            logger.debug("user_state: LLM resolution failed : %s", exc)
            return current

    prompt = _REFRESH_PROMPT_TEMPLATE.format(
        current_state=json.dumps(current, ensure_ascii=False, indent=2),
        conversation=conversation_text,
    )

    try:
        response = await llm.ainvoke(
            [{"role": "user", "content": prompt}],
            config={"callbacks": []},
        )
    except Exception as exc:
        logger.debug("user_state: LLM call failed : %s", exc)
        return current

    raw = getattr(response, "content", "") or ""
    raw = _strip_json_fences(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("user_state: invalid JSON from LLM : %.200s", raw)
        return current

    if not isinstance(parsed, dict):
        return current

    new_state = await set_user_state(user_id, parsed)
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "user_state : refreshed user=%s mood=%s focus=%.40s topics=%d loops=%d duration=%dms",
        user_id,
        new_state["mood"],
        new_state["current_focus"],
        len(new_state["recent_topics"]),
        len(new_state["open_loops"]),
        duration_ms,
    )
    return new_state


# ─────────────────────────────────────────────────────────────────────────
# Prompt block formatter (used by Jalon 2 injection)
# ─────────────────────────────────────────────────────────────────────────


def format_user_state_block(state: dict[str, Any]) -> str:
    """Render the state as an XML-tagged block for the system prompt.

    Empty / default state collapses to a tiny block so it doesn't bloat
    the prompt early on, when ELY hasn't learned anything yet.
    """
    s = _merge_with_defaults(state or {})
    has_signal = bool(
        s["current_focus"]
        or s["recent_topics"]
        or s["open_loops"]
        or s["mood"] != "neutral"
        or s["energy_budget"] != "normal"
    )
    if not has_signal:
        return ""  # nothing useful to inject — keep the prompt lean

    lines = ["<user_state>"]
    lines.append(f"- mood: {s['mood']}")
    if s["current_focus"]:
        lines.append(f"- current_focus: {s['current_focus']}")
    if s["recent_topics"]:
        lines.append(f"- recent_topics: {', '.join(s['recent_topics'])}")
    if s["open_loops"]:
        lines.append("- open_loops:")
        for loop in s["open_loops"]:
            lines.append(f"  • {loop}")
    lines.append(f"- energy_budget: {s['energy_budget']}")
    lines.append("</user_state>")
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers (kept private, easily monkeypatched in tests)
# ─────────────────────────────────────────────────────────────────────────


async def _load_recent_messages(conversation_id: str, limit: int = 20) -> list:
    """Last N messages of a conversation, oldest-first. Mirrors the
    ``maintenance_rapid._load_recent_messages`` pattern so the two
    services stay in sync."""
    from app.models.conversation import Message
    async with async_session() as db:
        rows = (await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )).scalars().all()
    return list(reversed(list(rows)))


def _format_messages(messages: list) -> str:
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "") or getattr(msg, "type", "")
        content = getattr(msg, "content", "") or ""
        if not isinstance(content, str) or not content.strip():
            continue
        role_label = "Utilisateur" if role in ("user", "human") else "Assistante"
        # Compact tool-spam : long assistant messages from tool dumps
        # don't help the state extractor.
        snippet = content.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        parts.append(f"{role_label}: {snippet}")
    return "\n".join(parts)


def _strip_json_fences(raw: str) -> str:
    """Pull JSON out of a fenced markdown block if the LLM ignored the
    "no fences" instruction."""
    s = raw.strip()
    if s.startswith("```"):
        # Drop the opening fence (optionally with `json` tag) and trailing fence
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3].rstrip()
    return s
