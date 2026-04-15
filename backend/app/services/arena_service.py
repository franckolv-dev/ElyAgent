# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits reserves.
#
# Ce logiciel est mis a disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RESUME DES CONDITIONS :
# - AUTORISE : Utilisation personnelle, educative et tests prives.
# - INTERDIT : Toute utilisation commerciale sans accord prealable.
# - INTERDIT : Redistribution de versions modifiees de ce code.
#
# Pour consulter le texte integral de la licence, veuillez vous referer au
# fichier LICENSE a la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
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

def _available_candidates() -> list[tuple[str, BaseChatModel]]:
    """Return ``(label, llm)`` tuples for every provider with a usable key."""
    from app.services.llm_provider import (
        _make_anthropic, _make_openrouter, _make_glm, _runtime,
    )
    settings = get_settings()

    def _key(prov: str, env_val: str) -> Optional[str]:
        return _runtime.get(f"key_{prov}") or env_val or None

    candidates: list[tuple[str, BaseChatModel]] = []

    # Gemini
    gemini_key = _key("gemini", settings.gemini_api_key)
    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            candidates.append((
                "gemini/gemini-2.5-flash",
                ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=gemini_key,
                    max_output_tokens=2048,
                    temperature=0.7,
                ),
            ))
        except Exception as exc:
            logger.debug("Arena: gemini unavailable: %s", exc)

    # Anthropic
    anthropic_key = _key("anthropic", settings.anthropic_api_key)
    if anthropic_key:
        try:
            candidates.append((
                "anthropic/claude-sonnet-4-6",
                _make_anthropic(model="claude-sonnet-4-6", api_key=anthropic_key),
            ))
        except Exception as exc:
            logger.debug("Arena: anthropic unavailable: %s", exc)

    # Mistral
    mistral_key = _key("mistral", settings.mistral_api_key)
    if mistral_key:
        try:
            from langchain_mistralai import ChatMistralAI
            candidates.append((
                "mistral/mistral-large-latest",
                ChatMistralAI(
                    model="mistral-large-latest",
                    api_key=mistral_key,
                    max_tokens=2048,
                    temperature=0.7,
                ),
            ))
        except Exception as exc:
            logger.debug("Arena: mistral unavailable: %s", exc)

    # DeepSeek
    deepseek_key = _key("deepseek", settings.deepseek_api_key)
    if deepseek_key:
        try:
            from langchain_openai import ChatOpenAI
            candidates.append((
                "deepseek/deepseek-chat",
                ChatOpenAI(
                    model="deepseek-chat",
                    api_key=deepseek_key,
                    base_url="https://api.deepseek.com/v1",
                    max_tokens=2048,
                    temperature=0.7,
                ),
            ))
        except Exception as exc:
            logger.debug("Arena: deepseek unavailable: %s", exc)

    # OpenRouter (free Llama)
    openrouter_key = _key("openrouter", settings.openrouter_api_key)
    if openrouter_key:
        try:
            candidates.append((
                "openrouter/llama-3.3-70b",
                _make_openrouter(
                    model="meta-llama/llama-3.3-70b-instruct:free",
                    api_key=openrouter_key,
                ),
            ))
        except Exception as exc:
            logger.debug("Arena: openrouter unavailable: %s", exc)

    # Zhipu GLM
    zhipu_key = _key("zhipu", settings.zhipu_api_key)
    if zhipu_key:
        try:
            candidates.append((
                "zhipu/glm-4-flash",
                _make_glm(model="glm-4-flash", api_key=zhipu_key),
            ))
        except Exception as exc:
            logger.debug("Arena: zhipu unavailable: %s", exc)

    # Local Ollama (always attempt -- fails silently if daemon is down)
    try:
        from langchain_ollama import ChatOllama
        candidates.append((
            f"ollama/{settings.slm_model}",
            ChatOllama(
                model=settings.slm_model,
                base_url=settings.ollama_base_url,
                temperature=0.7,
            ),
        ))
    except Exception as exc:
        logger.debug("Arena: ollama unavailable: %s", exc)

    return candidates


def list_available_models() -> list[str]:
    """Return the labels of every model currently usable in the Arena."""
    return [label for label, _ in _available_candidates()]


# ---------------------------------------------------------------------------
# Match execution
# ---------------------------------------------------------------------------

async def _invoke_one(llm: BaseChatModel, prompt: str) -> tuple[str, int]:
    """Invoke *llm* with *prompt* and return ``(text, latency_ms)``."""
    start = time.perf_counter()
    try:
        msg = await llm.ainvoke([
            SystemMessage(content=_ARENA_SYSTEM),
            HumanMessage(content=prompt),
        ])
        latency = int((time.perf_counter() - start) * 1000)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        return content, latency
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
