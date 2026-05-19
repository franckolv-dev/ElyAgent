# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/settings_llm.py
# @brief      Router — LLM provider / model / API-key / tier-routing management
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
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
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user, require_admin
from app.config import get_settings
from app.database import async_session
from app.models.llm_instance import LLMInstance
from app.models.user import User
from app.services.system_config import get_config, set_config
from app.services.llm_provider import (
    set_runtime_llm, set_runtime_key, has_runtime_key,
    get_active_provider, get_active_model,
    set_tier_config, DEFAULT_TIER_CONFIG,
    register_instance_cache, unregister_instance_cache,
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
    {
        "id": "lm_studio",
        "name": "LM Studio (local)",
        "env_key": None,
        "config_key": None,
        # Model names must match what LM Studio reports in its "Local Server" tab.
        # Common examples — update to match the model you have loaded.
        "models": ["gemma-4-26B-A4B-it-MLX-4bit", "llama-3.3-70b-instruct", "phi-4-mini-reasoning", "mistral-7b-instruct"],
    },
    {
        "id": "qwen_api",
        "name": "Qwen API (Alibaba Cloud)",
        "env_key": "QWEN_API_KEY",
        "config_key": "api_key_qwen_api",
        # Common models on DashScope (2026). The exact list depends on the
        # Alibaba workspace — the user can type any model name in the
        # instance UI (validation is bypassed for this provider).
        "models": [
            "qwen3.6-max-preview", "qwen3.6-plus-preview",
            "qwen-max-latest", "qwen-plus-latest", "qwen-turbo-latest",
            "qwen2.5-vl-72b-instruct", "qwen2.5-72b-instruct",
            "qwen-vl-max-latest",
        ],
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
        "qwen_api":   "qwen_api_key",
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
# LLM Instance schemas
# ---------------------------------------------------------------------------

class LLMInstanceCreate(BaseModel):
    label: str
    provider: str
    model: str
    api_key: Optional[str] = None


class LLMInstanceUpdate(BaseModel):
    label: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class LLMInstanceResponse(BaseModel):
    id: str
    label: str
    provider: str
    model: str
    has_key: bool
    created_at: str


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

    # Fetch real Ollama models dynamically
    ollama_models: list[str] = []
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=3.0) as _client:
            _resp = await _client.get(f"{get_settings().ollama_base_url}/api/tags")
        if _resp.status_code == 200:
            ollama_models = [m.get("name", "") for m in _resp.json().get("models", []) if m.get("name")]
    except Exception:
        pass  # Ollama unreachable — fallback to static list below

    providers_out = []
    for meta in PROVIDERS_META:
        models = ollama_models if (meta["id"] == "ollama" and ollama_models) else meta["models"]
        providers_out.append({
            "id":      meta["id"],
            "name":    meta["name"],
            "models":  models,
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
    # OpenRouter is skipped (dynamic catalogue).
    # Ollama, LM Studio and Qwen API are skipped: models are fetched/typed live.
    meta = next(p for p in PROVIDERS_META if p["id"] == body.provider)
    if body.provider not in ("openrouter", "ollama", "lm_studio", "qwen_api") and body.model not in meta["models"]:
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
# Ollama — dynamic model list
# ---------------------------------------------------------------------------

@router.get("/ollama-models")
async def get_ollama_models(
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """Return installed Ollama models from the local daemon."""
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{get_settings().ollama_base_url}/api/tags")
        if resp.status_code == 200:
            return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# LLM Instances — CRUD
# ---------------------------------------------------------------------------

@router.get("/instances", response_model=list[LLMInstanceResponse])
async def list_llm_instances(
    current_user: User = Depends(get_current_user),
) -> list[LLMInstanceResponse]:
    """Return all configured LLM instances (API key masked as ***)."""
    async with async_session() as db:
        result = await db.execute(select(LLMInstance).order_by(LLMInstance.created_at))
        instances = result.scalars().all()
    return [
        LLMInstanceResponse(
            id=inst.id,
            label=inst.label,
            provider=inst.provider,
            model=inst.model,
            has_key=bool(inst.api_key),
            created_at=inst.created_at.isoformat(),
        )
        for inst in instances
    ]


@router.post("/instances", status_code=status.HTTP_201_CREATED, response_model=LLMInstanceResponse)
async def create_llm_instance(
    body: LLMInstanceCreate,
    admin: User = Depends(require_admin),
) -> LLMInstanceResponse:
    """Create a new LLM instance."""
    if body.provider not in _PROVIDER_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{body.provider}'. Valid: {sorted(_PROVIDER_IDS)}",
        )
    if not body.label or not body.label.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="label must not be empty.",
        )
    if not body.model or not body.model.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model must not be empty.",
        )

    inst = LLMInstance(
        id=str(uuid.uuid4()),
        label=body.label.strip(),
        provider=body.provider,
        model=body.model.strip(),
        api_key=body.api_key.strip() if body.api_key and body.api_key.strip() else None,
        created_at=datetime.now(timezone.utc),
    )
    async with async_session() as db:
        db.add(inst)
        await db.commit()
        await db.refresh(inst)

    # Update in-memory instance cache so tier routing can use this instance immediately
    register_instance_cache(inst.id, inst.provider, inst.model, inst.api_key)

    logger.info("LLM instance created by admin %s: id=%s provider=%s model=%s", admin.id, inst.id, inst.provider, inst.model)
    return LLMInstanceResponse(
        id=inst.id,
        label=inst.label,
        provider=inst.provider,
        model=inst.model,
        has_key=bool(inst.api_key),
        created_at=inst.created_at.isoformat(),
    )


@router.patch("/instances/{instance_id}", response_model=LLMInstanceResponse)
async def update_llm_instance(
    instance_id: str,
    body: LLMInstanceUpdate,
    admin: User = Depends(require_admin),
) -> LLMInstanceResponse:
    """Update label, model, or API key of an existing instance."""
    async with async_session() as db:
        result = await db.execute(select(LLMInstance).where(LLMInstance.id == instance_id))
        inst = result.scalar_one_or_none()
        if inst is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")

        if body.label is not None:
            if not body.label.strip():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label must not be empty.")
            inst.label = body.label.strip()
        if body.model is not None:
            if not body.model.strip():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model must not be empty.")
            inst.model = body.model.strip()
        if body.api_key is not None:
            inst.api_key = body.api_key.strip() if body.api_key.strip() else None

        await db.commit()
        await db.refresh(inst)

    # Sync in-memory cache
    register_instance_cache(inst.id, inst.provider, inst.model, inst.api_key)

    logger.info("LLM instance updated by admin %s: id=%s", admin.id, instance_id)
    return LLMInstanceResponse(
        id=inst.id,
        label=inst.label,
        provider=inst.provider,
        model=inst.model,
        has_key=bool(inst.api_key),
        created_at=inst.created_at.isoformat(),
    )


@router.delete("/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_instance(
    instance_id: str,
    admin: User = Depends(require_admin),
) -> None:
    """Delete a LLM instance by ID."""
    async with async_session() as db:
        result = await db.execute(select(LLMInstance).where(LLMInstance.id == instance_id))
        inst = result.scalar_one_or_none()
        if inst is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
        await db.delete(inst)
        await db.commit()

    # Remove from in-memory cache
    unregister_instance_cache(instance_id)

    logger.info("LLM instance deleted by admin %s: id=%s", admin.id, instance_id)


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
    """Return tier routing config, tier metadata, available provider ids, and LLM instances."""
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

    # Fetch instances to allow the frontend to display them in the routing UI
    async with async_session() as db:
        result = await db.execute(select(LLMInstance).order_by(LLMInstance.created_at))
        instances = result.scalars().all()

    instances_out = [
        {
            "id": inst.id,
            "label": inst.label,
            "provider": inst.provider,
            "model": inst.model,
            "has_key": bool(inst.api_key),
        }
        for inst in instances
    ]

    return {
        "tiers": TIER_META,
        "config": config,
        "provider_ids": [p["id"] for p in PROVIDERS_META],
        "instances": instances_out,
    }


@router.put("/tiers", status_code=status.HTTP_200_OK)
async def update_tier_config_endpoint(
    body: TierConfigUpdate,
    admin: User = Depends(require_admin),
) -> dict:
    """Persist tier routing config and update in-memory cache.

    The providers list can contain either:
    - A known provider name ("ollama", "anthropic", …) — backward compat
    - A UUID of a LLMInstance in DB
    """
    valid_provider_ids = {p["id"] for p in PROVIDERS_META}

    # Collect known instance IDs from DB for validation
    async with async_session() as db:
        result = await db.execute(select(LLMInstance.id))
        known_instance_ids = {row[0] for row in result.all()}

    for tier_id, tier_entry in body.config.items():
        for prov_id in tier_entry.providers:
            if prov_id not in valid_provider_ids and prov_id not in known_instance_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown provider or instance ID '{prov_id}' in tier '{tier_id}'.",
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
