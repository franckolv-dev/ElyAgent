"""Router — LLM provider / model / API-key management.

Endpoints
---------
GET  /api/settings/llm               — any authenticated user
PUT  /api/settings/llm               — admin only
PUT  /api/settings/llm/keys/{provider} — admin only
"""
from __future__ import annotations

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
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
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
        "anthropic": "anthropic_api_key",
        "mistral":   "mistral_api_key",
        "gemini":    "gemini_api_key",
        "deepseek":  "deepseek_api_key",
        "zhipu":     "zhipu_api_key",
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

    # Validate model belongs to this provider
    meta = next(p for p in PROVIDERS_META if p["id"] == body.provider)
    if body.model not in meta["models"]:
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
