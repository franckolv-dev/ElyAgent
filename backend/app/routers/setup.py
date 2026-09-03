# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/setup.py
# @brief      Setup wizard API — first-launch configuration status and key validation
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
"""Setup wizard API — first-launch configuration status and key validation.

Endpoints
---------
GET  /setup/status         — current configuration state (no auth required for status)
POST /setup/validate-key   — validate an LLM API key with a real minimal test call
POST /setup/save-key       — save a validated LLM key (requires auth)
POST /setup/test-ollama    — test Ollama availability and list models
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_optional_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.llm_provider import set_runtime_key, has_runtime_key
from app.services.system_config import get_config, set_config


# ---------------------------------------------------------------------------
# Bootstrap guard
# ---------------------------------------------------------------------------
# The /setup wizard must work BEFORE the first admin user exists (otherwise
# you couldn't bootstrap a fresh install). But once at least one user
# exists, these endpoints are admin-only — otherwise an attacker on the
# open internet could (a) brute-force pasted API keys against external
# providers (cost weaponisation), (b) use the backend as an SSRF probe to
# whatever `ollama_base_url` resolves to, (c) fingerprint internal config.
#
# This helper allows the request only if either :
#   - the User table is empty (first launch, no admin yet)
#   - OR an authenticated admin is calling
#
# Use as a FastAPI dependency on every wizard endpoint.

async def require_bootstrap_or_admin(
    db: AsyncSession = Depends(get_db),
    caller: Optional[User] = Depends(get_optional_user),
) -> None:
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if count == 0:
        return  # bootstrap mode, no admin yet, allow
    if caller is None or caller.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette opération est réservée aux administrateurs après l'installation initiale.",
        )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ValidateKeyRequest(BaseModel):
    provider: str  # "mistral" | "anthropic" | "gemini" | "deepseek"
    key: str


class ValidateKeyResponse(BaseModel):
    valid: bool
    error: Optional[str] = None
    model_hint: Optional[str] = None


class SaveKeyRequest(BaseModel):
    provider: str
    key: str


class OllamaTestResponse(BaseModel):
    available: bool
    models: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER_CONFIG_KEYS = {
    "anthropic": "api_key_anthropic",
    "mistral":   "api_key_mistral",
    "gemini":    "api_key_gemini",
    "deepseek":  "api_key_deepseek",
}


async def _has_llm_key(provider: str) -> bool:
    """Return True if an API key is available for this provider."""
    cfg_key = _PROVIDER_CONFIG_KEYS.get(provider)
    if not cfg_key:
        return False
    if await get_config(cfg_key, ""):
        return True
    if has_runtime_key(provider):
        return True
    s = get_settings()
    env_map = {
        "anthropic": s.anthropic_api_key,
        "mistral":   s.mistral_api_key,
        "gemini":    s.gemini_api_key,
        "deepseek":  s.deepseek_api_key,
    }
    return bool(env_map.get(provider, ""))


async def _any_llm_configured() -> bool:
    """Return True if at least one LLM provider is configured."""
    for provider in ("anthropic", "mistral", "gemini", "deepseek"):
        if await _has_llm_key(provider):
            return True
    # Check Ollama (no key needed — just check if URL is set or configured)
    return False


# ---------------------------------------------------------------------------
# GET /setup/status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_setup_status():
    """Return what is configured vs missing. No auth required."""
    s = get_settings()

    # --- LLM providers ---
    llm_status: dict = {}
    for provider in ("anthropic", "mistral", "gemini", "deepseek"):
        llm_status[provider] = {"configured": await _has_llm_key(provider)}

    # Ollama — try a quick ping
    ollama_available = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{s.ollama_base_url}/api/tags")
            ollama_available = resp.status_code == 200
    except Exception:
        ollama_available = False
    llm_status["ollama"] = {"available": ollama_available}

    # --- Google ---
    google_connected = False
    # We cannot check Google per-user without auth, so we just check app config
    from app.services.system_config import get_config as gc
    has_gid = bool(await gc("google_client_id", fallback=s.google_client_id))
    has_gsecret = bool(await gc("google_client_secret", fallback=s.google_client_secret))
    google_app_configured = has_gid and has_gsecret

    # --- Telegram ---
    telegram_token = await gc("telegram_bot_token", fallback=s.telegram_bot_token)
    telegram_configured = bool(telegram_token)

    # --- First launch ---
    any_llm = await _any_llm_configured() or llm_status["ollama"]["available"]
    is_first_launch = not any_llm

    return {
        "google": {
            "configured": google_app_configured,
            "connected": False,  # requires user auth — always False here
        },
        "llm": llm_status,
        "telegram": {"configured": telegram_configured},
        "is_first_launch": is_first_launch,
    }


# ---------------------------------------------------------------------------
# GET /setup/status/me — authenticated version (includes per-user Google status)
# ---------------------------------------------------------------------------

@router.get("/status/me")
async def get_setup_status_me(current_user: User = Depends(get_current_user)):
    """Return setup status including per-user Google connection. Requires auth."""
    base = await get_setup_status()
    base["google"]["connected"] = current_user.google_credentials is not None
    return base


# ---------------------------------------------------------------------------
# POST /setup/validate-key
# ---------------------------------------------------------------------------

@router.post("/validate-key", response_model=ValidateKeyResponse)
async def validate_key(
    body: ValidateKeyRequest,
    _guard: None = Depends(require_bootstrap_or_admin),
) -> ValidateKeyResponse:
    """Validate an API key by making a real minimal test call to the provider.

    Open during bootstrap (no users yet); admin-only afterwards. Without
    this guard, a public clone exposes a free probe that an attacker can
    weaponise to brute-force pasted keys (real provider charges) or to
    SSRF whatever target a malicious payload aims at.
    """
    provider = body.provider.lower()
    key = body.key.strip()

    if not key:
        return ValidateKeyResponse(valid=False, error="Clé vide")

    if provider == "mistral":
        return await _validate_mistral(key)
    elif provider == "anthropic":
        return await _validate_anthropic(key)
    elif provider == "gemini":
        return await _validate_gemini(key)
    elif provider == "deepseek":
        return await _validate_deepseek(key)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fournisseur inconnu : {provider}",
        )


async def _validate_mistral(key: str) -> ValidateKeyResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-small-latest",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                },
            )
        if resp.status_code in (401, 403):
            return ValidateKeyResponse(valid=False, error="Clé invalide ou accès refusé")
        if resp.status_code == 200:
            return ValidateKeyResponse(valid=True, model_hint="mistral-small-latest")
        return ValidateKeyResponse(
            valid=False,
            error=f"Erreur Mistral : {resp.status_code}",
        )
    except httpx.TimeoutException:
        return ValidateKeyResponse(valid=False, error="Délai dépassé — réessayez")
    except Exception as e:
        logger.warning("Mistral key validation error: %s", e)
        return ValidateKeyResponse(valid=False, error="Erreur réseau")


async def _validate_anthropic(key: str) -> ValidateKeyResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                },
            )
        if resp.status_code in (401, 403):
            return ValidateKeyResponse(valid=False, error="Clé invalide ou accès refusé")
        if resp.status_code == 200:
            return ValidateKeyResponse(valid=True, model_hint="claude-haiku-4-5-20251001")
        return ValidateKeyResponse(
            valid=False,
            error=f"Erreur Anthropic : {resp.status_code}",
        )
    except httpx.TimeoutException:
        return ValidateKeyResponse(valid=False, error="Délai dépassé — réessayez")
    except Exception as e:
        logger.warning("Anthropic key validation error: %s", e)
        return ValidateKeyResponse(valid=False, error="Erreur réseau")


async def _validate_gemini(key: str) -> ValidateKeyResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": "Hi"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
        if resp.status_code in (400, 401, 403):
            data = resp.json()
            err_msg = data.get("error", {}).get("message", "")
            if "API_KEY_INVALID" in err_msg or resp.status_code in (401, 403):
                return ValidateKeyResponse(valid=False, error="Clé invalide ou accès refusé")
        if resp.status_code == 200:
            return ValidateKeyResponse(valid=True, model_hint="gemini-2.5-flash")
        return ValidateKeyResponse(
            valid=False,
            error=f"Erreur Gemini : {resp.status_code}",
        )
    except httpx.TimeoutException:
        return ValidateKeyResponse(valid=False, error="Délai dépassé — réessayez")
    except Exception as e:
        logger.warning("Gemini key validation error: %s", e)
        return ValidateKeyResponse(valid=False, error="Erreur réseau")


async def _validate_deepseek(key: str) -> ValidateKeyResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 1,
                },
            )
        if resp.status_code in (401, 403):
            return ValidateKeyResponse(valid=False, error="Clé invalide ou accès refusé")
        if resp.status_code == 200:
            return ValidateKeyResponse(valid=True, model_hint="deepseek-chat")
        return ValidateKeyResponse(
            valid=False,
            error=f"Erreur DeepSeek : {resp.status_code}",
        )
    except httpx.TimeoutException:
        return ValidateKeyResponse(valid=False, error="Délai dépassé — réessayez")
    except Exception as e:
        logger.warning("DeepSeek key validation error: %s", e)
        return ValidateKeyResponse(valid=False, error="Erreur réseau")


# ---------------------------------------------------------------------------
# POST /setup/save-key
# ---------------------------------------------------------------------------

@router.post("/save-key")
async def save_key(
    body: SaveKeyRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Save a validated LLM API key. Requires authentication."""
    provider = body.provider.lower()
    key = body.key.strip()

    cfg_key = _PROVIDER_CONFIG_KEYS.get(provider)
    if not cfg_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fournisseur inconnu : {provider}",
        )

    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La clé API ne peut pas être vide.",
        )

    provider_names = {
        "anthropic": "Anthropic Claude",
        "mistral":   "Mistral AI",
        "gemini":    "Google Gemini",
        "deepseek":  "DeepSeek",
    }

    await set_config(
        cfg_key,
        key,
        is_secret=True,
        description=f"API key for {provider_names.get(provider, provider)}",
    )

    # Update in-memory runtime immediately (no restart needed)
    set_runtime_key(provider, key)

    logger.info(
        "Setup wizard: API key saved for provider=%s by user=%s",
        provider,
        current_user.id,
    )
    return {"provider": provider, "saved": True}


# ---------------------------------------------------------------------------
# POST /setup/test-ollama
# ---------------------------------------------------------------------------

@router.post("/test-ollama", response_model=OllamaTestResponse)
async def test_ollama(
    _guard: None = Depends(require_bootstrap_or_admin),
) -> OllamaTestResponse:
    """Test if Ollama is reachable and return available models."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{s.ollama_base_url}/api/tags")
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            models = [m for m in models if m]
            return OllamaTestResponse(available=True, models=models)
        return OllamaTestResponse(available=False, models=[])
    except Exception:
        return OllamaTestResponse(available=False, models=[])


# ---------------------------------------------------------------------------
# POST /setup/validate-telegram
# ---------------------------------------------------------------------------

class TelegramValidateRequest(BaseModel):
    token: str


class TelegramValidateResponse(BaseModel):
    valid: bool
    bot_name: Optional[str] = None
    error: Optional[str] = None


@router.post("/validate-telegram", response_model=TelegramValidateResponse)
async def validate_telegram(
    body: TelegramValidateRequest,
    _guard: None = Depends(require_bootstrap_or_admin),
) -> TelegramValidateResponse:
    """Validate a Telegram bot token using the getMe API."""
    token = body.token.strip()
    if not token:
        return TelegramValidateResponse(valid=False, error="Token vide")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getMe"
            )
        if resp.status_code == 200:
            data = resp.json()
            bot = data.get("result", {})
            return TelegramValidateResponse(
                valid=True,
                bot_name=bot.get("username") or bot.get("first_name"),
            )
        return TelegramValidateResponse(
            valid=False,
            error="Token invalide — vérifiez que vous avez bien copié le token de BotFather",
        )
    except httpx.TimeoutException:
        return TelegramValidateResponse(valid=False, error="Délai dépassé — réessayez")
    except Exception as e:
        logger.warning("Telegram token validation error: %s", e)
        return TelegramValidateResponse(valid=False, error="Erreur réseau")


# ---------------------------------------------------------------------------
# POST /setup/save-telegram
# ---------------------------------------------------------------------------

class SaveTelegramRequest(BaseModel):
    token: str


@router.post("/save-telegram")
async def save_telegram(
    body: SaveTelegramRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Save a validated Telegram bot token. Requires authentication."""
    token = body.token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le token Telegram ne peut pas être vide.",
        )

    await set_config(
        "telegram_bot_token",
        token,
        is_secret=True,
        description="Telegram bot token",
    )

    logger.info(
        "Setup wizard: Telegram token saved by user=%s",
        current_user.id,
    )
    return {"saved": True}
