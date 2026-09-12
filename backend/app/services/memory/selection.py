"""Deterministic memory selection. Models may rank evidence, never create it."""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache

REQUEST_SCOPE: ContextVar[str] = ContextVar("memory_scope", default="")


def fuse_ranks(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """RRF over a real union; scores are comparable across retrieval engines."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking)):
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def eligible_payload(payload: dict, user_id: str, scope: str = "") -> bool:
    if not user_id or payload.get("user_id") != user_id:
        return False
    from app.services.memory.scopes import allowed_scopes

    if payload.get("scope", "") not in allowed_scopes(scope):
        return False
    if payload.get("superseded") or payload.get("forgotten"):
        return False
    expiry = payload.get("expires_at")
    if expiry:
        try:
            if isinstance(expiry, (int, float)):
                ts = float(expiry)
            else:
                value = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                ts = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
            if ts <= time.time():
                return False
        except (ValueError, TypeError):
            return False  # malformed validity is not permission to inject
    return True


def needs_recall(query: str) -> bool:
    """Only suppress unmistakably self-contained requests, never vague followups."""
    q = query.casefold().strip(" .!?\n")
    if q in {"bonjour", "salut", "hello", "merci", "merci beaucoup", "bonsoir", "ok", "coucou"}:
        return False
    q = re.sub(
        r"^(peux-tu me dire|j’ai besoin de savoir|rappelle-moi|pour continuer|aujourd’hui|une précision|s’il te plaît|avant de poursuivre|ma question est)\s*:\s*",
        "",
        q,
    )
    q = q.replace(" fois ", " × ")
    q = re.sub(r"^(calcule|combien font|combien fait)\s+", "", q)
    return not bool(re.fullmatch(r"[\d\s.,+*/×÷=()−-]+", q))


@lru_cache(maxsize=1)
def tokenizer():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    # Named reference tokenizer, not an assertion about every provider's billing.
    return len(tokenizer().encode(text, disallowed_special=()))


def truncate(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    return tokenizer().decode(tokenizer().encode(text, disallowed_special=())[:budget])


def pack(candidates: list[dict], budget: int, mandatory: str = "") -> tuple[str, list[dict]]:
    """Whole optional records, mandatory evidence first; explicit overflow blocks."""
    if tokens(mandatory) > budget:
        raise ValueError("État de travail obligatoire trop volumineux ; reprise automatique suspendue.")
    parts = [mandatory] if mandatory else []
    selected = []
    seen = set()
    sources: dict[str, int] = {}
    for item in candidates:
        fingerprint = re.sub(r"\s+", " ", item["text"].casefold()).strip()
        source = item.get("source", item["id"])
        if fingerprint in seen or sources.get(source, 0) >= 2:
            continue
        line = json.dumps(
            {
                "ref": item["id"],
                "source": source,
                "scope": item.get("scope", ""),
                "observed_at": item.get("observed_at"),
                "fact": item["text"],
                "confirmed": item.get("confirmed", False),
            },
            ensure_ascii=False,
        )
        if tokens("\n".join(parts + [line])) > budget:
            continue
        parts.append(line)
        seen.add(fingerprint)
        sources[source] = sources.get(source, 0) + 1
        selected.append({**item, "tokens": tokens(line), "reason": item.get("reason", "Pertinence pour la demande")})
    return "\n".join(parts), selected
