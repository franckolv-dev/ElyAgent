# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Router — LLM provider / model / API-key / tier-routing management.

Endpoints
---------
GET  /api/settings/llm               — any authenticated user
PUT  /api/settings/llm               — admin only
PUT  /api/settings/llm/keys/{provider} — admin only
GET  /api/settings/llm/tiers         — any authenticated user
PUT  /api/settings/llm/tiers         — admin only
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_admin
from app.config import get_settings
from app.models.user import User
from app.services.system_config import get_config, set_config
from app.services.llm_provider import (
    set_runtime_llm, set_runtime_key, has_runtime_key,
    get_active_provider, get_active_model,
    set_tier_config, DEFAULT_TIER_CONFIG,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/llm", tags=["settings-llm"])

# ---------------------------------------------------------------------------
# Provider catalogue (source of truth used in this router)
# ---------------------------------------------------------------------------
PROVIDERS_META = [
    {
        "id": "zhipu",
        "name": "Zhipu AI — GLM",
        "env_key": "ZHIPU_API_KEY",
        "config_key": "api_key_zhipu",
        # GLM-4.7 : optimisé function-calling / agents, prefix caching automatique
        "models": ["glm-4.7", "glm-4-plus", "glm-4-air", "glm-4-flash"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "env_key": "ANTHROPIC_API_KEY",
        "config_key": "api_key_anthropic",
        "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-4-6", "claude-opus-4-5-20251101", "claude-opus-4-6"],
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "config_key": "api_key_gemini",
        "models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "config_key": "api_key_deepseek",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "env_key": "MISTRAL_API_KEY",
        "config_key": "api_key_mistral",
        "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "config_key": "api_key_openrouter",
        # Models are fetched dynamically from the OpenRouter API
        # (GET /api/settings/llm/openrouter-models) — this list is a minimal fallback
        "models": ["meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free",
                   "deepseek/deepseek-r1:free", "mistralai/mistral-7b-instruct:free"],
    },
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "env_key": None,
        "config_key": None,
        "models": ["llama3.2", "qwen2.5-coder", "qwen2.5:7b-instruct"],
    },
]

_PROVIDER_IDS = {p["id"] for p in PROVIDERS_META}


def _env_key_for(provider_id: str) -> str:
    """Return the env-var attribute name on Settings for this provider's API key."""
    mapping = {
        "anthropic":  "anthropic_api_key",
        "mistral":    "mistral_api_key",
        "gemini":     "gemini_api_key",
        "deepseek":   "deepseek_api_key",
        "zhipu":      "zhipu_api_key",
        "openrouter": "openrouter_api_key",
    }
    return mapping.get(provider_id, "")


async def _has_key(meta: dict) -> bool:
    """Return True if an API key is available for this provider (DB or env)."""
    if meta["config_key"] is None:
        # Ollama — no key needed
        return True
    # Check DB first
    db_val = await get_config(meta["config_key"], "")
    if db_val:
        return True
    # Check runtime cache (LOW-4: use public accessor instead of _runtime directly)
    if has_runtime_key(meta["id"]):
        return True
    # Check env/settings
    env_attr = _env_key_for(meta["id"])
    if env_attr:
        settings = get_settings()
        env_val = getattr(settings, env_attr, "")
        if env_val:
            return True
    return False


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LLMSettingsResponse(BaseModel):
    provider: str
    model: str
    providers: list[dict]


class LLMSettingsUpdate(BaseModel):
    provider: str
    model: str


class APIKeyUpdate(BaseModel):
    api_key: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=LLMSettingsResponse)
async def get_llm_settings(
    current_user: User = Depends(get_current_user),
) -> LLMSettingsResponse:
    """Return current provider, model, and per-provider metadata."""
    settings = get_settings()

    # Active provider/model: DB > runtime > env (LOW-4: use public accessors)
    provider = await get_config("active_llm_provider", "")
    if not provider:
        provider = get_active_provider()

    model = await get_config("active_llm_model", "")
    if not model:
        model = get_active_model()

    providers_out = []
    for meta in PROVIDERS_META:
        providers_out.append({
            "id":      meta["id"],
            "name":    meta["name"],
            "models":  meta["models"],
            "has_key": await _has_key(meta),
        })

    return LLMSettingsResponse(
        provider=provider,
        model=model,
        providers=providers_out,
    )


@router.put("", status_code=status.HTTP_200_OK)
async def update_llm_settings(
    body: LLMSettingsUpdate,
    admin: User = Depends(require_admin),
) -> dict:
    """Persist active provider + model and update in-memory runtime."""
    if body.provider not in _PROVIDER_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{body.provider}'. Valid: {sorted(_PROVIDER_IDS)}",
        )

    # Validate model belongs to this provider.
    # OpenRouter is skipped: its catalogue is fetched dynamically from the API
    # (GET /openrouter-models) so the static models list is only a fallback —
    # any model string returned by their API must be accepted.
    meta = next(p for p in PROVIDERS_META if p["id"] == body.provider)
    if body.provider != "openrouter" and body.model not in meta["models"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{body.model}' not available for provider '{body.provider}'.",
        )

    await set_config(
        "active_llm_provider",
        body.provider,
        is_secret=False,
        description="Active LLM provider",
    )
    await set_config(
        "active_llm_model",
        body.model,
        is_secret=False,
        description="Active LLM model",
    )

    # Update in-memory runtime immediately (no restart needed)
    set_runtime_llm(body.provider, body.model)

    logger.info("LLM settings updated by admin %s: provider=%s model=%s", admin.id, body.provider, body.model)
    return {"provider": body.provider, "model": body.model}


@router.put("/keys/{provider}", status_code=status.HTTP_200_OK)
async def update_llm_api_key(
    provider: str,
    body: APIKeyUpdate,
    admin: User = Depends(require_admin),
) -> dict:
    """Store an API key for the given provider (DB, marked secret, never returned)."""
    if provider not in _PROVIDER_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{provider}'. Valid: {sorted(_PROVIDER_IDS)}",
        )

    meta = next(p for p in PROVIDERS_META if p["id"] == provider)
    if meta["config_key"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider}' does not use an API key.",
        )

    if not body.api_key or not body.api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key must not be empty.",
        )

    await set_config(
        meta["config_key"],
        body.api_key.strip(),
        is_secret=True,
        description=f"API key for {meta['name']}",
    )

    # Update in-memory runtime immediately
    set_runtime_key(provider, body.api_key.strip())

    logger.info("API key updated by admin %s for provider=%s", admin.id, provider)
    return {"provider": provider, "has_key": True}


# ---------------------------------------------------------------------------
# OpenRouter — dynamic model catalogue
# ---------------------------------------------------------------------------

_or_cache: dict = {"data": None, "ts": 0.0}
_OR_CACHE_TTL = 3600  # 1 hour


@router.get("/openrouter-models")
async def get_openrouter_models(
    free_only: bool = False,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Fetch the OpenRouter model catalogue, optionally filtered to free models only.

    Results are cached for 1 hour to avoid rate-limiting the OpenRouter API.
    Free models are identified by pricing.prompt == "0" AND pricing.completion == "0".
    """
    import time
    import httpx

    now = time.time()
    if _or_cache["data"] is None or (now - _or_cache["ts"]) > _OR_CACHE_TTL:
        api_key = await get_config("api_key_openrouter", "")
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                )
                resp.raise_for_status()
                _or_cache["data"] = resp.json().get("data", [])
                _or_cache["ts"] = now
        except Exception as exc:
            logger.warning("OpenRouter models fetch failed: %s", exc)
            if _or_cache["data"] is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Could not reach OpenRouter API: {exc}",
                )
            # Return stale cache on transient error

    raw: list[dict] = _or_cache["data"] or []

    result = []
    for m in raw:
        pricing = m.get("pricing", {})
        prompt_price  = pricing.get("prompt", "1")
        compl_price   = pricing.get("completion", "1")
        is_free = (str(prompt_price) == "0" and str(compl_price) == "0")

        if free_only and not is_free:
            continue

        arch = m.get("architecture", {})
        result.append({
            "id":             m.get("id", ""),
            "name":           m.get("name", m.get("id", "")),
            "context_length": m.get("context_length", 0),
            "is_free":        is_free,
            "modality":       arch.get("modality", "text->text"),
            "prompt_price":   prompt_price,
            "completion_price": compl_price,
        })

    # Sort: free first, then alphabetically by name
    result.sort(key=lambda x: (not x["is_free"], x["name"].lower()))
    return result


# ---------------------------------------------------------------------------
# Tier routing config
# ---------------------------------------------------------------------------

TIER_META = [
    {
        "id": "simple",
        "label": "Niveau A — Simple",
        "badge": "A",
        "color": "emerald",
        "description": (
            "Questions courtes, calculs rapides, réponses directes sans outil. "
            "Un modèle local (Ollama) est idéal : zéro latence réseau, coût nul, "
            "100 % privé. Le score de complexité est < 30."
        ),
    },
    {
        "id": "medium",
        "label": "Niveau B — Standard",
        "badge": "B",
        "color": "blue",
        "description": (
            "Conversations standards, utilisation des outils (agenda, e-mail, recherche), "
            "raisonnement modéré. Représente la majorité des échanges. "
            "Score de complexité 30-70."
        ),
    },
    {
        "id": "complex",
        "label": "Niveau C — Complexe",
        "badge": "C",
        "color": "violet",
        "description": (
            "Analyses approfondies, génération de code, workflows multi-étapes, "
            "documents longs. Nécessite un modèle performant avec une grande fenêtre "
            "de contexte. Score de complexité > 70."
        ),
    },
    {
        "id": "image",
        "label": "Niveau IMG — Vision",
        "badge": "IMG",
        "color": "amber",
        "description": (
            "Analyse d'images, reconnaissance visuelle, description de photos ou "
            "captures d'écran jointes à un message. Nécessite un modèle multimodal."
        ),
    },
    {
        "id": "maintenance",
        "label": "Niveau SYS — Maintenance",
        "badge": "SYS",
        "color": "slate",
        "description": (
            "Tâches de fond : extraction de faits pour la mémoire utilisateur, "
            "maintenance des profils, exécution des tâches planifiées. "
            "Recommandé : Ollama local (zéro coût, disponible 24/7, sans quota)."
        ),
    },
]


class TierEntry(BaseModel):
    providers: list[str]
    fallback_enabled: bool = True


class TierConfigUpdate(BaseModel):
    config: dict[str, TierEntry]


@router.get("/tiers")
async def get_tier_config_endpoint(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return tier routing config, tier metadata, and available provider ids."""
    raw = await get_config("tier_routing_config", "")
    if raw:
        try:
            config = json.loads(raw)
        except Exception:
            config = DEFAULT_TIER_CONFIG
    else:
        config = DEFAULT_TIER_CONFIG

    # Ensure all tiers are present (add missing ones with defaults)
    for tier_id, default_cfg in DEFAULT_TIER_CONFIG.items():
        if tier_id not in config:
            config[tier_id] = default_cfg

    return {
        "tiers": TIER_META,
        "config": config,
        "provider_ids": [p["id"] for p in PROVIDERS_META],
    }


@router.put("/tiers", status_code=status.HTTP_200_OK)
async def update_tier_config_endpoint(
    body: TierConfigUpdate,
    admin: User = Depends(require_admin),
) -> dict:
    """Persist tier routing config and update in-memory cache."""
    # Validate that all provider ids are known
    valid_ids = {p["id"] for p in PROVIDERS_META}
    for tier_id, tier_entry in body.config.items():
        for prov_id in tier_entry.providers:
            if prov_id not in valid_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown provider '{prov_id}' in tier '{tier_id}'.",
                )

    serializable = {
        tier_id: {"providers": entry.providers, "fallback_enabled": entry.fallback_enabled}
        for tier_id, entry in body.config.items()
    }

    await set_config(
        "tier_routing_config",
        json.dumps(serializable),
        is_secret=False,
        description="Tier routing configuration (provider chains per complexity tier)",
    )

    # Hot-reload in memory
    set_tier_config(serializable)

    logger.info("Tier routing config updated by admin %s", admin.id)
    return {"ok": True, "config": serializable}
