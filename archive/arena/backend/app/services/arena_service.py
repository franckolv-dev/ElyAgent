# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/arena_service.py
# @brief      Arena service -- run head-to-head prompts against two LLMs and update ELO
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Arena service -- run head-to-head prompts against two LLMs and update ELO.

This is entirely user-facing (not used by the agent loop).  The user asks a
prompt, two models respond in parallel, the user votes, ELO is updated.

The pool of candidate models is built from whatever provider credentials are
available at call time (gemini, anthropic, openrouter, deepseek, mistral,
ollama).  Two distinct labels are randomly sampled for each match.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


# ELO hyper-parameters
_ELO_K = 32
_ELO_START = 1000.0

# System prompt that frames Ely's identity in Arena mode
_ARENA_SYSTEM = (
    "Tu es une assistante IA utile, concise et précise. "
    "Réponds en français sauf si l'utilisateur écrit dans une autre langue. "
    "N'utilise pas de markdown lourd."
)


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------

def _local_provider_reachable(provider: str) -> bool:
    """Quick TCP/HTTP ping to local providers (lm_studio / ollama).

    Sans ce ping, l'arena tirait systématiquement le modèle local même quand
    le daemon était down, et chaque match concerné renvoyait
    ``[Erreur du modèle : All connection attempts failed]``.
    """
    settings = get_settings()
    try:
        import httpx
        if provider == "ollama":
            url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
        elif provider == "lm_studio":
            url = f"{settings.lm_studio_base_url.rstrip('/')}/models"
        else:
            return True  # cloud providers — pas besoin de ping
        with httpx.Client(timeout=1.5) as client:
            r = client.get(url)
            r.raise_for_status()
        return True
    except Exception as exc:
        logger.debug("Arena: %s unreachable, skipping: %s", provider, exc)
        return False


def _available_candidates() -> list[tuple[str, BaseChatModel]]:
    """Return ``(label, llm)`` tuples built from the user's configured instances.

    Branche l'Arena directement sur la table ``llm_instances`` (page « Modèles
    IA » des paramètres). Le classement ELO reflète donc les modèles réellement
    utilisables par cet utilisateur — Haiku 4.5, Gemini 3.1, Qwen, Ministral,
    LM Studio local, etc. — au lieu d'une liste hardcodée.

    Filtres appliqués :
      * Cloud provider sans clé (instance ou env) → exclu
      * Instance locale (lm_studio / ollama) avec daemon down → exclue
      * Doublons exacts ``provider/model`` → première instance gagne
    """
    from app.services.llm_provider import _make_llm_for_instance, _instance_cache

    candidates: list[tuple[str, BaseChatModel]] = []
    seen_labels: set[str] = set()

    # Snapshot du cache (peut être mis à jour en concurrent par les CRUD instances)
    for instance_id, info in list(_instance_cache.items()):
        provider = info.get("provider", "")
        model = info.get("model", "")
        label = f"{provider}/{model}"

        # Évite les doublons (ex. plusieurs instances pour le même provider/model)
        if label in seen_labels:
            continue

        # Skip locaux down
        if provider in ("ollama", "lm_studio") and not _local_provider_reachable(provider):
            continue

        try:
            llm = _make_llm_for_instance(instance_id, max_tokens=2048, temperature=0.7)
        except Exception as exc:
            logger.debug("Arena: instance %s (%s) factory failed: %s", instance_id, label, exc)
            continue

        if llm is None:
            # _make_llm_for_instance renvoie None si la clé manque pour un cloud provider
            continue

        candidates.append((label, llm))
        seen_labels.add(label)

    return candidates


def list_available_models() -> list[str]:
    """Return the labels of every model currently usable in the Arena."""
    return [label for label, _ in _available_candidates()]


# ---------------------------------------------------------------------------
# Match execution
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    """Sérialise proprement le ``content`` d'un AIMessage LangChain.

    Certains providers (Gemini en particulier, mais aussi Anthropic en mode
    multi-block) renvoient une liste de blocks ``[{type:'text', text:'...'}]``
    au lieu d'une string. ``str(...)`` donnait alors un repr Python illisible
    affiché tel quel dans l'Arena.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if isinstance(blk, str):
                parts.append(blk)
            elif isinstance(blk, dict):
                # Anthropic / Gemini / OpenAI : {'type': 'text', 'text': '...'}
                if "text" in blk and isinstance(blk["text"], str):
                    parts.append(blk["text"])
                elif blk.get("type") == "text" and "content" in blk:
                    parts.append(str(blk["content"]))
        if parts:
            return "\n".join(p for p in parts if p)
    return str(content)


async def _invoke_one(llm: BaseChatModel, prompt: str) -> tuple[str, int]:
    """Invoke *llm* with *prompt* and return ``(text, latency_ms)``."""
    start = time.perf_counter()
    try:
        msg = await llm.ainvoke([
            SystemMessage(content=_ARENA_SYSTEM),
            HumanMessage(content=prompt),
        ])
        latency = int((time.perf_counter() - start) * 1000)
        return _extract_text(msg.content), latency
    except Exception as exc:
        latency = int((time.perf_counter() - start) * 1000)
        logger.warning("Arena: model invocation failed: %s", exc)
        return f"[Erreur du modèle : {exc}]", latency


async def run_match(
    prompt: str,
    user_id: str,
    force_models: Optional[tuple[str, str]] = None,
) -> dict:
    """Run a blind head-to-head match. Persists the match row without a vote.

    Returns a dict with ``match_id``, ``model_a``, ``model_b``, ``response_a``,
    ``response_b``, ``latency_a_ms``, ``latency_b_ms``.
    """
    from app.database import async_session
    from app.models.arena import ArenaMatch

    candidates = _available_candidates()
    if len(candidates) < 2:
        raise RuntimeError(
            "Au moins deux modèles doivent être configurés pour utiliser le "
            "mode Arena. Configure au minimum deux fournisseurs LLM dans "
            "les paramètres."
        )

    # Pick two distinct candidates
    if force_models is not None:
        pool = {label: llm for label, llm in candidates}
        try:
            chosen = [(force_models[0], pool[force_models[0]]),
                      (force_models[1], pool[force_models[1]])]
        except KeyError as exc:
            raise RuntimeError(f"Modèle indisponible : {exc.args[0]}") from exc
    else:
        chosen = random.sample(candidates, 2)

    # Run both in parallel
    (resp_a, lat_a), (resp_b, lat_b) = await asyncio.gather(
        _invoke_one(chosen[0][1], prompt),
        _invoke_one(chosen[1][1], prompt),
    )

    # Persist
    async with async_session() as db:
        match = ArenaMatch(
            user_id=user_id,
            prompt=prompt[:4000],
            model_a=chosen[0][0],
            model_b=chosen[1][0],
            response_a=resp_a,
            response_b=resp_b,
            latency_a_ms=lat_a,
            latency_b_ms=lat_b,
        )
        db.add(match)
        await db.commit()
        await db.refresh(match)

    return {
        "match_id": match.id,
        "model_a": chosen[0][0],
        "model_b": chosen[1][0],
        "response_a": resp_a,
        "response_b": resp_b,
        "latency_a_ms": lat_a,
        "latency_b_ms": lat_b,
    }


# ---------------------------------------------------------------------------
# ELO update
# ---------------------------------------------------------------------------

def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


async def _get_or_create_elo(db, model: str):
    from app.models.arena import ArenaElo
    from sqlalchemy import select
    row = (await db.execute(select(ArenaElo).where(ArenaElo.model == model))).scalar_one_or_none()
    if row is None:
        row = ArenaElo(model=model, elo=_ELO_START)
        db.add(row)
        await db.flush()
    return row


async def record_vote(match_id: str, user_id: str, vote: str) -> dict:
    """Record a vote and update ELO.

    *vote* is one of ``a``, ``b``, ``tie``, ``both_bad``.
    Only the owner of the match (same ``user_id``) may vote.
    Returns the post-vote ELO for both models.
    """
    if vote not in ("a", "b", "tie", "both_bad"):
        raise ValueError(f"Vote invalide : {vote}")

    from app.database import async_session
    from app.models.arena import ArenaMatch
    from sqlalchemy import select

    async with async_session() as db:
        match = (
            await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
        ).scalar_one_or_none()

        if match is None:
            raise ValueError(f"Match introuvable : {match_id}")
        if match.user_id != user_id:
            raise PermissionError("Ce match appartient a un autre utilisateur.")
        if match.vote is not None:
            raise ValueError("Ce match a deja ete vote.")

        match.vote = vote
        match.voted_at = datetime.now(timezone.utc)

        elo_a = await _get_or_create_elo(db, match.model_a)
        elo_b = await _get_or_create_elo(db, match.model_b)

        # Determine scores
        if vote == "a":
            score_a, score_b = 1.0, 0.0
            elo_a.wins += 1
            elo_b.losses += 1
        elif vote == "b":
            score_a, score_b = 0.0, 1.0
            elo_a.losses += 1
            elo_b.wins += 1
        else:  # "tie" or "both_bad" -- symmetric half-point
            score_a, score_b = 0.5, 0.5
            elo_a.ties += 1
            elo_b.ties += 1

        exp_a = _expected(elo_a.elo, elo_b.elo)
        exp_b = _expected(elo_b.elo, elo_a.elo)

        new_a = elo_a.elo + _ELO_K * (score_a - exp_a)
        new_b = elo_b.elo + _ELO_K * (score_b - exp_b)

        elo_a.elo = round(new_a, 2)
        elo_b.elo = round(new_b, 2)
        elo_a.matches += 1
        elo_b.matches += 1
        elo_a.updated_at = datetime.now(timezone.utc)
        elo_b.updated_at = datetime.now(timezone.utc)

        await db.commit()

        return {
            "match_id": match_id,
            "vote": vote,
            "elo": {
                match.model_a: elo_a.elo,
                match.model_b: elo_b.elo,
            },
        }


async def leaderboard() -> list[dict]:
    """Return the global ELO leaderboard, sorted descending."""
    from app.database import async_session
    from app.models.arena import ArenaElo
    from sqlalchemy import select

    async with async_session() as db:
        rows = (await db.execute(select(ArenaElo).order_by(ArenaElo.elo.desc()))).scalars().all()
        return [
            {
                "model": r.model,
                "elo": round(r.elo, 2),
                "wins": r.wins,
                "losses": r.losses,
                "ties": r.ties,
                "matches": r.matches,
            }
            for r in rows
        ]


async def match_history(user_id: str, limit: int = 20) -> list[dict]:
    """Return the user's recent Arena matches."""
    from app.database import async_session
    from app.models.arena import ArenaMatch
    from sqlalchemy import select

    async with async_session() as db:
        rows = (
            await db.execute(
                select(ArenaMatch)
                .where(ArenaMatch.user_id == user_id)
                .order_by(ArenaMatch.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {
                "match_id": r.id,
                "prompt": r.prompt,
                "model_a": r.model_a,
                "model_b": r.model_b,
                "vote": r.vote,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "voted_at": r.voted_at.isoformat() if r.voted_at else None,
            }
            for r in rows
        ]
