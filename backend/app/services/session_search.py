# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/session_search.py
# @brief      Cross-conversation memory recall (Sprint 1, Phase 2).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Retrieve and summarise past conversations relevant to a user's query.

Sits on top of ``messages_fts_store`` (FTS5 keyword index built in
Phase 1 of Sprint 1). The flow:

    user query
       │
       ▼
    FTS5 search  ──►  raw matches across all the user's conversations
       │
       ▼
    group by conversation_id, rank by cumulative BM25 score
       │
       ▼
    keep top-K conversations
       │
       ▼
    for each kept conversation, in parallel:
         a. load the conversation's title + creation date
         b. load the full message history (truncated to a safe budget)
         c. ask the SIMPLE-tier LLM (Ministral 3B local) to summarise
            it in light of the user's current query
       │
       ▼
    return list of structured summaries — ready for an agent tool to
    expose to the LLM as ``search_past_conversations(query)``.

Design choices
--------------
- **Local Ministral 3B for summarisation**: the task is "read this
  block of text and write 3-4 sentences" — small models nail this and
  it's free to run. The MEDIUM/COMPLEX tiers would be overkill and
  the per-call cost would discourage agent-side use.
- **Parallel summarisation**: K conversations are summarised in
  ``asyncio.gather``. K=3 default → about 5-7s total instead of 15-21s
  serial on a typical M1 Max.
- **Conversation-wide context, not message-snippet only**: the LLM
  sees the full conversation (truncated). Otherwise summaries fixate
  on the matched fragments and miss the "what was the outcome"
  context that makes recall useful.
- **JSON-structured output from the summariser**: we ask the LLM to
  return ``{"title": ..., "summary": ...}``. Title is regenerated even
  if the conversation already has one in DB — most conversations
  carry the default "New conversation" because the auto-title feature
  hasn't kicked in. The LLM-generated title is search-aware.

Safety / failure modes
----------------------
- If FTS returns nothing → ``[]``. No LLM call.
- If LLM call fails or returns non-JSON → that conversation is
  represented by a fallback dict (title = DB title, summary = first
  matched snippet). The whole call still returns the K-1 others.
- All operations are best-effort; the caller (agent tool) treats a
  raised exception as "no memory found".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.database import async_session
from app.models.conversation import Conversation, Message
from app.services.llm_provider import ComplexityTier, get_llm_for_tier
from app.services.messages_fts_store import get_messages_fts_store

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────────

# Max raw FTS hits to consider before grouping by conversation. Larger
# = more conversations matched but more sorting work. 50 is plenty for
# personal-scale histories.
_FTS_LIMIT = 50

# Max characters of conversation content sent to the summariser. Ministral
# 3B has a 32k-token context window (~128k chars) but we leave room for
# the system prompt + output. 80k chars is conservative.
_MAX_CONTEXT_CHARS = 80_000

# Soft cap on how long each individual message can be before it gets
# truncated in the dump (avoids one giant tool-result dominating the
# context). The matched snippets remain intact in the FTS-result layer.
_MAX_MESSAGE_CHARS = 3_000


# ── Prompts ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Tu es un assistant de mémoire. L'utilisateur cherche dans ses conversations \
passées un sujet précis. Ta tâche : lire une conversation complète et écrire \
un résumé focalisé sur ce qu'il cherche.

Réponds UNIQUEMENT avec un objet JSON valide de la forme :
{
  "title":   "Titre court de 4-7 mots décrivant le sujet de la conversation",
  "summary": "Résumé en 2-4 phrases mettant l'accent sur ce qui est pertinent par rapport à la requête de l'utilisateur. Si la conversation a abouti à une décision, un résultat ou une liste concrète, mentionne-le. Si elle est restée sans conclusion, dis-le aussi."
}

CONTRAINTES STRICTES sur le format :
- Le champ "title" DOIT être une string simple, pas un objet imbriqué.
- Le champ "summary" DOIT être une string simple en prose continue (2-4 phrases),
  PAS un objet, PAS une liste, PAS une structure avec sous-catégories.
- Pas de markdown autour du JSON. Pas de commentaire avant ou après.
  Juste l'objet JSON.

EXEMPLE de bonne réponse :
{"title": "Recherche pompe Bestway 58361", "summary": "Tu cherchais une pompe à filtre Bestway. On a comparé 5 sites : Amazon (49,99€), Cdiscount (52,90€), Leroy Merlin (54,99€). Tu n'as pas commandé."}

EXEMPLE de MAUVAISE réponse (à éviter) :
{"title": "Recherche pompe", "summary": {"sites": [...], "decisions": [...]}}
"""


def _user_prompt(query: str, conversation_dump: str, date_str: str) -> str:
    return (
        f"Date de la conversation : {date_str}\n\n"
        f"Requête actuelle de l'utilisateur : « {query} »\n\n"
        "Conversation passée :\n"
        "---\n"
        f"{conversation_dump}\n"
        "---\n\n"
        "Résume au format JSON demandé."
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _group_matches_by_conversation(
    fts_results: list[dict],
) -> list[tuple[str, list[dict], float]]:
    """Group FTS matches by conversation_id and compute a relevance score.

    SQLite FTS5 BM25 returns *negative* numbers — closer to 0 is better.
    We aggregate by summing the (negated) ranks: a conversation with
    several strong matches outranks one with a single weak match.

    Returns: list of (conversation_id, [matches], score) sorted by
    score descending (best first).
    """
    by_conv: dict[str, list[dict]] = defaultdict(list)
    for r in fts_results:
        by_conv[r["conversation_id"]].append(r)

    scored = [
        (conv_id, matches, sum(-m["rank"] for m in matches))
        for conv_id, matches in by_conv.items()
    ]
    scored.sort(key=lambda t: t[2], reverse=True)
    return scored


async def _load_conversation_dump(
    conversation_id: str, max_chars: int = _MAX_CONTEXT_CHARS,
) -> tuple[Conversation | None, str]:
    """Load a conversation + its messages, formatted for LLM consumption.

    Returns ``(conversation, dump_string)``. The dump is alternating
    ``[USER] ...`` / ``[ASSISTANT] ...`` lines, truncated message-by-
    message if needed, with a cumulative cap of ``max_chars``.

    If the conversation doesn't exist (e.g. orphan message), returns
    ``(None, "")``.
    """
    async with async_session() as db:
        conv = (await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )).scalar_one_or_none()
        if conv is None:
            return None, ""

        messages = (await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )).scalars().all()

    parts: list[str] = []
    total = 0
    for m in messages:
        role = (m.role or "").lower()
        if role == "system":
            continue
        content = (m.content or "").strip()
        if not content:
            continue
        if len(content) > _MAX_MESSAGE_CHARS:
            content = content[:_MAX_MESSAGE_CHARS] + " […tronqué]"
        line = f"[{role.upper()}] {content}"
        if total + len(line) + 1 > max_chars:
            parts.append("[…historique antérieur tronqué pour rester dans le budget…]")
            break
        parts.append(line)
        total += len(line) + 1

    return conv, "\n".join(parts)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _content_to_text(content) -> str:
    """Normalise a LangChain ``response.content`` into a plain string.

    Délègue au helper partagé ``agent.helpers.message_content.content_to_text``
    (source de vérité unique — voir son docstring pour les providers
    concernés : LM Studio, Anthropic reasoning, Gemini multimodal,
    OpenAI Responses/codex). Alias conservé pour les imports/tests existants.
    """
    from app.agent.helpers.message_content import content_to_text
    return content_to_text(content)


def _flatten_to_summary(value, _depth: int = 0) -> str:
    """Aplatir récursivement n'importe quoi en string lisible.

    Sister of ``_content_to_text`` but with a different goal: instead of
    extracting "the text field of a LangChain block", this flattens any
    structured value (str / list / dict / numeric) into a Markdown-ish
    bullet-list representation that a human (and an agent) can read.

    Born from audit 2026-05-15: Ministral 3B sometimes ignores the
    instruction "summary must be a plain string" and returns a nested
    object like ``{"rendez-vous_principaux": [...], "actions_pendantes":
    [...]}``. The content is excellent — it's just shaped as a JSON
    object rather than prose. Rather than dropping the LLM's work
    on the floor, we serialise it back into prose-ish text.

    Output examples:
        "hello"           → "hello"
        ["a", "b"]        → "• a\n• b"
        {"k": "v"}        → "k : v"
        {"k": ["a", "b"]} → "k :\n  • a\n  • b"
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    indent = "  " * _depth
    if isinstance(value, list):
        if not value:
            return ""
        items = [_flatten_to_summary(v, _depth + 1) for v in value]
        return "\n".join(f"{indent}• {item}" for item in items if item)
    if isinstance(value, dict):
        if not value:
            return ""
        parts: list[str] = []
        for k, v in value.items():
            v_str = _flatten_to_summary(v, _depth + 1)
            if not v_str:
                continue
            # If the value spans multiple lines, put the key on its own line
            if "\n" in v_str:
                parts.append(f"{indent}{k} :\n{v_str}")
            else:
                parts.append(f"{indent}{k} : {v_str}")
        return "\n".join(parts)
    return str(value).strip()


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction from a LLM response.

    Ministral 3B usually respects the "no markdown" instruction but
    occasionally wraps the output in a code fence. Try the strict
    parse first; on failure, strip a fence and retry.
    """
    text = (text or "").strip()
    if not text:
        return None
    # First, try as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip Markdown fence if present
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Last resort: find the first { ... } block by counting braces
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


async def _summarise_conversation(
    conv: Conversation,
    dump: str,
    query: str,
    matches: list[dict],
) -> dict:
    """Summarise one conversation via the SIMPLE-tier LLM (Ministral 3B).

    Returns a result dict in the same shape as the caller-facing API.
    On any error, falls back to a snippet-based stub so the caller
    still gets something usable.
    """
    date_str = conv.created_at.strftime("%d %B %Y") if conv.created_at else "(date inconnue)"

    fallback = {
        "conversation_id": conv.id,
        "title": conv.title or "Conversation passée",
        "date": conv.created_at.isoformat() if conv.created_at else None,
        "summary": (matches[0]["snippet"] if matches else "")[:300],
        "matched_messages": len(matches),
        "via": "fallback",
    }

    if not dump:
        return fallback

    try:
        llm = get_llm_for_tier(ComplexityTier.SIMPLE)
        response = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_user_prompt(query, dump, date_str)),
        ])
        # Normalise content first: LM Studio sometimes returns a list of
        # typed blocks rather than a plain string.
        response_text = _content_to_text(response.content)
        parsed = _extract_json(response_text)
        if not parsed or not isinstance(parsed, dict):
            # One-time diagnostic log so we can spot weird LLM outputs
            # in production. Truncated to keep the log readable.
            logger.info(
                "session_search: LLM JSON parse failed for conv %s. "
                "raw_response_text[:300]=%r",
                conv.id, (response_text or "")[:300],
            )
            return fallback

        # Robustness: parsed values can themselves be non-strings if the
        # LLM returned a nested object. Ministral 3B sometimes ignores
        # the "summary must be a plain string" instruction and returns
        # a JSON object like {"rendez-vous_principaux": [...],
        # "actions_pendantes": [...]} — the content is excellent, just
        # mis-shaped. ``_flatten_to_summary`` reshapes it back into
        # bullet-list prose rather than dropping it.
        raw_title = parsed.get("title") or conv.title or "Conversation passée"
        raw_summary = parsed.get("summary") or ""
        title = _flatten_to_summary(raw_title)
        summary = _flatten_to_summary(raw_summary)
        if not summary:
            logger.info(
                "session_search: parsed JSON had empty summary for conv %s. "
                "parsed=%r", conv.id, str(parsed)[:300],
            )
            return fallback

        return {
            "conversation_id": conv.id,
            "title": title[:120],  # safety cap
            "date": conv.created_at.isoformat() if conv.created_at else None,
            "summary": summary,
            "matched_messages": len(matches),
            "via": "llm",
        }
    except Exception as exc:
        logger.warning(
            "session_search: summarisation failed for conv %s: %s — falling back",
            conv.id, exc,
        )
        return fallback


# ── Public API ────────────────────────────────────────────────────────


async def search_past_conversations(
    user_id: str,
    query: str,
    limit: int = 3,
) -> list[dict]:
    """Find and summarise up to ``limit`` past conversations matching the query.

    Args:
        user_id: scope of the search (each user only sees their own).
        query: free-text query (will go through the FTS tokenizer).
        limit: maximum number of conversation summaries to return.

    Returns a list of dicts (best match first):
        {
          "conversation_id":  str,
          "title":            str,   # LLM-generated, focused on the query
          "date":             str,   # ISO-8601, or None if missing
          "summary":          str,   # 2-4 sentences, in user's language
          "matched_messages": int,   # how many FTS hits in this conv
          "via":              "llm" | "fallback",
        }

    Empty list if no FTS match or if the user has no indexed messages.
    Never raises — failures degrade to "no memory found".
    """
    if not user_id or not query:
        return []

    # 1. FTS search across the user's entire history
    store = get_messages_fts_store()
    raw = await store.search(query, user_id=user_id, limit=_FTS_LIMIT)
    if not raw:
        return []

    # 2. Group by conversation, rank by cumulative score
    grouped = _group_matches_by_conversation(raw)
    top_conversations = grouped[:limit]

    # 3. Load + summarise each kept conversation in parallel
    async def _process(conv_id: str, matches: list[dict]) -> dict | None:
        conv, dump = await _load_conversation_dump(conv_id)
        if conv is None:
            return None  # orphan message — conversation was deleted
        return await _summarise_conversation(conv, dump, query, matches)

    results = await asyncio.gather(
        *(_process(conv_id, matches) for conv_id, matches, _score in top_conversations),
        return_exceptions=False,
    )
    return [r for r in results if r is not None]
