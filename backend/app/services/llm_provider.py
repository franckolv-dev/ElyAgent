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
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Complexity tier enum
# ---------------------------------------------------------------------------

class ComplexityTier(str, Enum):
    """Message complexity tiers for LLM routing."""
    SIMPLE      = "simple"      # Tier A — fast, local (Ollama)
    MEDIUM      = "medium"      # Tier B — standard tasks, tools
    COMPLEX     = "complex"     # Tier C — deep reasoning, multi-step
    IMAGE       = "image"       # Tier IMG — multimodal / vision
    MAINTENANCE = "maintenance" # Tier SYS — background tasks (memory, scheduler)


# ---------------------------------------------------------------------------
# Complexity heuristic classifier (no LLM call — pure rule-based)
# ---------------------------------------------------------------------------

_COMPLEX_KEYWORDS = re.compile(
    r"\b(code|script|architecture|debug|analys[eo]|analyse|MCP|3D|docker|ssh|deploy|"
    r"implémente|impl[eé]mente|cr[eé][eé] un|développe|refactor|programme|"
    r"fonction|classe|module|algorithme|pipeline|infrastructure|kubernetes|"
    r"nginx|postgres|redis|elasticsearch)\b",
    re.IGNORECASE,
)

_IMAGE_KEYWORDS = re.compile(
    r"\b(image|génère une image|dessine|crée une illustration|illustration|"
    r"generate image|draw|imagine|visualise|photo réaliste)\b",
    re.IGNORECASE,
)

_SIMPLE_KEYWORDS = re.compile(
    r"\b(traduis|translate|traduction|weather|météo|résume|summarize|"
    r"c'est quoi|qu'est-ce que|what is|define|définition|définition de|"
    r"bonjour|merci|hello|salut|rappelle|note)\b",
    re.IGNORECASE,
)

# Writing / composition tasks that require some reasoning → MEDIUM
_MEDIUM_KEYWORDS = re.compile(
    r"\b(rédige|rédiger|rédaction|écris|écrire|compose|composé|emails?|"
    r"mail[sx]?|boite mail|boîte mail|boîte aux lettres|inbox|lettre|message|réponse|explique|expliquer|comment faire|"
    r"aide.moi|aide moi|help me|propose|suggestion|conseil|conseille|"
    r"planifie|organise|liste|compare|comparer|recherche|trouve|"
    r"calendrier|agenda|rendez.vous|tâche[sx]?|rappel|note[sx]?|contact[sx]?|"
    r"newsletter[sx]?|mailing[sx]?|spam|corbeille|archive[sz]?|promotionnel[sx]?|"
    r"gmail|drive|sheets?|docs?|google|workspace|fichier[sx]?|dossier[sx]?|"
    r"document[sx]?|tableur[sx]?|spreadsheet[sx]?|événement[sx]?|réunion[sx]?)\b",
    re.IGNORECASE,
)


def classify_complexity(message: str) -> ComplexityTier:
    """Classify a user message into a complexity tier using rule-based heuristics.

    No LLM call is made — this is a pure, synchronous, zero-latency function.
    """
    # Image tier: explicit image generation requests
    if _IMAGE_KEYWORDS.search(message):
        return ComplexityTier.IMAGE

    word_count = len(message.split())

    # Complex tier: code/infra keywords or very long messages
    if _COMPLEX_KEYWORDS.search(message) or word_count > 150:
        return ComplexityTier.COMPLEX

    # Simple tier: very short messages with explicit simple intent
    if word_count < 15 and _SIMPLE_KEYWORDS.search(message):
        return ComplexityTier.SIMPLE

    # Medium tier: writing/composition/research keywords
    if _MEDIUM_KEYWORDS.search(message):
        return ComplexityTier.MEDIUM

    # Short messages (< 40 words) with only simple keywords → SIMPLE
    if word_count < 40 and _SIMPLE_KEYWORDS.search(message):
        return ComplexityTier.SIMPLE

    # Short ambiguous messages → MEDIUM (safer default than SIMPLE)
    if word_count < 60:
        return ComplexityTier.MEDIUM

    # Everything else is MEDIUM
    return ComplexityTier.MEDIUM

# ---------------------------------------------------------------------------
# Module-level in-memory override dict (singleton per process).
# Keys: "provider", "model", "key_anthropic", "key_mistral", "key_gemini",
#       "key_deepseek"
# Populated by load_llm_settings_from_db() on startup and by the
# settings_llm router whenever an admin saves via the UI.
# ---------------------------------------------------------------------------
_runtime: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Tier routing config — persisted in DB, cached here in memory.
# Shape: { "simple": {"providers": ["ollama"], "fallback_enabled": true}, … }
# ---------------------------------------------------------------------------
DEFAULT_TIER_CONFIG: dict[str, dict] = {
    "simple":      {"providers": ["ollama"],                        "fallback_enabled": True},
    "medium":      {"providers": ["zhipu", "gemini", "anthropic"],  "fallback_enabled": True},
    "complex":     {"providers": ["zhipu", "anthropic", "gemini"],  "fallback_enabled": True},
    "image":       {"providers": ["gemini", "zhipu"],               "fallback_enabled": True},
    "maintenance": {"providers": ["ollama"],                        "fallback_enabled": False},
}

_tier_config: dict[str, dict] = {}   # empty = use DEFAULT_TIER_CONFIG


def set_tier_config(config: dict) -> None:
    """Replace the in-memory tier routing config (called on startup + after PUT /tiers)."""
    global _tier_config
    _tier_config = config
    logger.info("Tier config updated: %s", list(config.keys()))


def get_tier_config() -> dict[str, dict]:
    """Return the active tier routing config (DB override or defaults)."""
    return _tier_config if _tier_config else DEFAULT_TIER_CONFIG


def set_runtime_llm(provider: str, model: str) -> None:
    """Update active provider and model in memory."""
    _runtime["provider"] = provider
    _runtime["model"] = model


def set_runtime_key(provider: str, key: str) -> None:
    """Store an API key override in memory (keyed as 'key_<provider>')."""
    _runtime[f"key_{provider}"] = key


def get_runtime_key(provider: str) -> str:
    """LOW-4: Public accessor for a runtime API key (avoids exporting _runtime directly)."""
    return _runtime.get(f"key_{provider}", "")


def has_runtime_key(provider: str) -> bool:
    """LOW-4: Return True if a runtime API key is set for the given provider."""
    return bool(_runtime.get(f"key_{provider}", ""))


def get_active_provider() -> str:
    return _runtime.get("provider") or get_settings().active_llm_provider


def get_active_model() -> str:
    return _runtime.get("model") or get_settings().active_llm_model


async def load_llm_settings_from_db() -> None:
    """Read LLM settings from DB and populate _runtime.  Called at startup."""
    from app.services.system_config import get_config

    try:
        provider = await get_config("active_llm_provider", "")
        model    = await get_config("active_llm_model", "")
        if provider:
            _runtime["provider"] = provider
        if model:
            _runtime["model"] = model

        # Load API keys from DB into _runtime so get_llm() can use them.
        key_map = {
            "anthropic":   "api_key_anthropic",
            "mistral":     "api_key_mistral",
            "gemini":      "api_key_gemini",
            "deepseek":    "api_key_deepseek",
            "zhipu":       "api_key_zhipu",
            "openrouter":  "api_key_openrouter",
        }
        for prov, cfg_key in key_map.items():
            val = await get_config(cfg_key, "")
            if val:
                _runtime[f"key_{prov}"] = val

        # Load tier routing config
        import json as _json
        tier_raw = await get_config("tier_routing_config", "")
        if tier_raw:
            try:
                set_tier_config(_json.loads(tier_raw))
            except Exception as _tc_exc:
                logger.warning("Failed to parse tier_routing_config: %s", _tc_exc)

        logger.info(
            "LLM settings loaded from DB: provider=%s model=%s",
            _runtime.get("provider", "<env>"),
            _runtime.get("model", "<env>"),
        )
    except Exception as exc:
        logger.warning("load_llm_settings_from_db failed (will use env defaults): %s", exc)


def get_slm() -> BaseChatModel:
    """Return the local Small Language Model (Ollama) for simple requests.

    Raises ImportError if langchain-ollama is not installed.
    The caller is responsible for the asyncio.wait_for timeout and LLM fallback.
    """
    settings = get_settings()
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.slm_model,
        base_url=settings.ollama_base_url,
        temperature=0.7,
    )


def _make_openrouter(model: str, api_key: str, max_tokens: int = 4096, temperature: float = 0.7) -> BaseChatModel:
    """Instantiate a model via OpenRouter's OpenAI-compatible endpoint.

    OpenRouter is an AI gateway that provides access to 200+ models from various
    providers (Meta, Google, Mistral, Qwen, DeepSeek, etc.).  Many models are free.
    Context caching depends on the underlying model.
    https://openrouter.ai/docs
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        max_tokens=max_tokens,
        temperature=temperature,
        default_headers={
            "HTTP-Referer": "https://ely.catalogmaker.fr",
            "X-Title": "ELY Agent",
        },
    )


def _make_glm(model: str, api_key: str, max_tokens: int = 4096, temperature: float = 0.7) -> BaseChatModel:
    """Instantiate GLM-4.x via Zhipu AI's OpenAI-compatible endpoint.

    Context caching (prefix caching) is **automatic** on Zhipu's side — no extra
    configuration is needed.  Cached tokens appear in the response as
    ``usage.prompt_tokens_details.cached_tokens`` and are billed at ~1/5 of
    normal input token price, giving up to 80 % cost reduction on repeated prompts
    (e.g. long system prompts or repeated tool schemas).
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _make_anthropic(model: str, api_key: str, max_tokens: int = 8192, temperature: float = 0.7) -> BaseChatModel:
    """Instantiate Claude with prompt-caching beta enabled.

    The Anthropic API supports up to 4 cache breakpoints per request (ephemeral,
    5-min TTL).  The ``prompt-caching-2024-07-31`` beta header activates the
    feature; actual cache markers (cache_control blocks) are added by the agent
    factory on the system message to cache the long static system prompt.
    Cached tokens are billed at ~10 % of normal input price.
    """
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        model_kwargs={
            "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
        },
    )


def get_llm() -> BaseChatModel:
    # Settings are read inside the function so that the .env file is always
    # fully loaded before we access any values (avoids module-import-time
    # race when the working directory is not yet set).
    settings = get_settings()

    # _runtime overrides take precedence over env/settings.
    provider = _runtime.get("provider") or settings.active_llm_provider
    model    = _runtime.get("model")    or settings.active_llm_model

    def _key(prov: str, env_val: str) -> Optional[str]:
        """Return runtime key if present, else fall back to env value."""
        return _runtime.get(f"key_{prov}") or env_val or None

    if provider == "anthropic":
        return _make_anthropic(
            model=model,
            api_key=_key("anthropic", settings.anthropic_api_key),
        )

    elif provider == "zhipu":
        key = _key("zhipu", settings.zhipu_api_key)
        return _make_glm(model=model, api_key=key)

    elif provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=model,
            api_key=_key("mistral", settings.mistral_api_key),
            max_tokens=4096,
            temperature=0.7,
        )

    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=0.7,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_key("deepseek", settings.deepseek_api_key),
            base_url="https://api.deepseek.com/v1",
            max_tokens=4096,
            temperature=0.7,
        )

    elif provider == "openrouter":
        return _make_openrouter(
            model=model,
            api_key=_key("openrouter", settings.openrouter_api_key),
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=_key("gemini", settings.gemini_api_key),
            max_output_tokens=4096,
            temperature=0.7,
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def get_fallback_llms() -> list[tuple[str, BaseChatModel]]:
    """Return a list of (label, llm) tuples for all available providers,
    in priority order, excluding the currently active one.

    Used to retry a failed LLM call (e.g. 429 / quota exhausted) with the
    next available provider — without changing the user's saved settings.
    Priority: Gemini → Claude → Mistral → Ollama.
    """
    settings = get_settings()
    current_provider = _runtime.get("provider") or settings.active_llm_provider

    def _key(prov: str, env_val: str) -> Optional[str]:
        return _runtime.get(f"key_{prov}") or env_val or None

    candidates: list[tuple[str, BaseChatModel]] = []

    gemini_key = _key("gemini", settings.gemini_api_key)
    if gemini_key:
        current_model = _runtime.get("model") or settings.active_llm_model or ""
        # If current model IS gemini-2.5-flash, skip (no point retrying same model).
        # Otherwise always include gemini-2.5-flash as a reliable fallback.
        if current_provider != "gemini" or current_model != "gemini-2.5-flash":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                candidates.append(("gemini/gemini-2.5-flash", ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=gemini_key,
                    max_output_tokens=4096,
                    temperature=0.7,
                )))
            except Exception:
                pass

    anthropic_key = _key("anthropic", settings.anthropic_api_key)
    if anthropic_key and current_provider != "anthropic":
        try:
            candidates.append(("anthropic/claude-sonnet-4-6", _make_anthropic(
                model="claude-sonnet-4-6",
                api_key=anthropic_key,
            )))
        except Exception:
            pass

    # Mistral intentionally excluded from automatic fallback:
    # - Requires content="" sanitization on AIMessage (not None)
    # - Breaks on multi-step tool-calling history (error code 3240)
    # - Poor tool choice compliance with large tool lists
    # Mistral remains selectable manually via settings, but never used as auto-fallback.

    openrouter_key = _key("openrouter", settings.openrouter_api_key)
    if openrouter_key and current_provider != "openrouter":
        try:
            candidates.append(("openrouter/llama-3.3-70b:free", _make_openrouter(
                model="meta-llama/llama-3.3-70b-instruct:free",
                api_key=openrouter_key,
            )))
        except Exception:
            pass

    if current_provider != "ollama":
        try:
            from langchain_ollama import ChatOllama
            candidates.append(("ollama/qwen2.5:7b-instruct", ChatOllama(
                model="qwen2.5:7b-instruct",
                base_url=settings.ollama_base_url,
                temperature=0.7,
            )))
        except Exception:
            pass

    return candidates


def get_llm_for_agent(config: "SubAgentConfig") -> BaseChatModel:  # type: ignore[name-defined]
    """Instantiate a LLM for a specific sub-agent.

    If ``config.llm_provider`` is None, delegates to ``get_llm()`` so that
    the globally-configured provider/model is used.  When a sub-agent carries
    its own provider/model, a dedicated instance is created from _runtime keys.
    """
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from app.agent.sub_agents.config import SubAgentConfig  # noqa: F401

    if config.llm_provider is None:
        return get_llm()

    settings = get_settings()
    provider = config.llm_provider
    model = config.llm_model or get_active_model()
    temperature = config.llm_temperature

    def _key(prov: str, env_val: str) -> Optional[str]:
        return _runtime.get(f"key_{prov}") or env_val or None

    if provider == "anthropic":
        return _make_anthropic(
            model=model,
            api_key=_key("anthropic", settings.anthropic_api_key),
            temperature=temperature,
        )

    elif provider == "zhipu":
        return _make_glm(
            model=model,
            api_key=_key("zhipu", settings.zhipu_api_key),
            temperature=temperature,
        )

    elif provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=model,
            api_key=_key("mistral", settings.mistral_api_key),
            max_tokens=4096,
            temperature=temperature,
        )

    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_key("deepseek", settings.deepseek_api_key),
            base_url="https://api.deepseek.com/v1",
            max_tokens=4096,
            temperature=temperature,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=_key("gemini", settings.gemini_api_key),
            max_output_tokens=4096,
            temperature=temperature,
        )

    else:
        raise ValueError(f"Unknown LLM provider for sub-agent '{config.name}': {provider}")


# ---------------------------------------------------------------------------
# Low-level provider factory — shared by tier routing and fallback helpers
# ---------------------------------------------------------------------------

def _make_llm_for_provider(
    provider_id: str,
    settings,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> Optional[BaseChatModel]:
    """Instantiate an LLM for the given provider_id using runtime keys.

    Returns None (does NOT raise) when the provider has no key configured,
    so the tier loop can safely skip it.  Raises only on hard import/config
    errors that the caller should surface.
    """
    def _key(prov: str, env_val: str) -> Optional[str]:
        return _runtime.get(f"key_{prov}") or env_val or None

    if provider_id == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=settings.slm_model or "qwen2.5:7b-instruct",
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    if provider_id == "zhipu":
        key = _key("zhipu", settings.zhipu_api_key)
        if not key:
            return None
        return _make_glm(model="glm-4.7", api_key=key,
                         max_tokens=max_tokens, temperature=temperature)

    if provider_id == "gemini":
        key = _key("gemini", settings.gemini_api_key)
        if not key:
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=key,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

    if provider_id == "anthropic":
        key = _key("anthropic", settings.anthropic_api_key)
        if not key:
            return None
        return _make_anthropic(model="claude-sonnet-4-6", api_key=key,
                               max_tokens=max_tokens, temperature=temperature)

    if provider_id == "mistral":
        key = _key("mistral", settings.mistral_api_key)
        if not key:
            return None
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model="mistral-small-latest",
            api_key=key,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider_id == "deepseek":
        key = _key("deepseek", settings.deepseek_api_key)
        if not key:
            return None
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=key,
            base_url="https://api.deepseek.com/v1",
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider_id == "openrouter":
        key = _key("openrouter", settings.openrouter_api_key)
        if not key:
            return None
        # Default to a good free model when no specific model is set for the tier
        return _make_openrouter(
            model="meta-llama/llama-3.3-70b-instruct:free",
            api_key=key,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    logger.warning("_make_llm_for_provider: unknown provider '%s'", provider_id)
    return None


# ---------------------------------------------------------------------------
# Tier-based LLM selector — driven by dynamic DB config
# ---------------------------------------------------------------------------

def get_llm_for_tier(tier: ComplexityTier) -> BaseChatModel:
    """Return the appropriate LLM for a given complexity tier.

    The provider chain for each tier is read from the in-memory tier config
    (loaded from DB on startup, editable via PUT /api/settings/llm/tiers).
    Falls back through the configured list; if fallback_enabled=False, only
    the first provider is tried.  If all fail, get_llm() is returned.
    """
    settings = get_settings()
    config = get_tier_config()
    tier_cfg = config.get(tier.value, DEFAULT_TIER_CONFIG.get(tier.value, {}))

    providers: list[str] = tier_cfg.get("providers", ["ollama"])
    fallback_enabled: bool = tier_cfg.get("fallback_enabled", True)
    max_tokens = 8192 if tier in (ComplexityTier.COMPLEX, ComplexityTier.MAINTENANCE) else 4096

    last_exc: Optional[Exception] = None
    for i, provider_id in enumerate(providers):
        try:
            llm = _make_llm_for_provider(provider_id, settings,
                                         max_tokens=max_tokens, temperature=0.7)
            if llm is not None:
                return llm
            # llm is None = no key for this provider → skip silently
            logger.debug("Tier %s: no key for '%s' — skipping", tier.value, provider_id)
        except Exception as exc:
            last_exc = exc
            logger.warning("Tier %s: '%s' failed (%s)", tier.value, provider_id, exc)

        if not fallback_enabled:
            break   # stop after first attempt when fallback is disabled

    if last_exc:
        logger.warning("Tier %s: all providers failed, using global LLM", tier.value)
    else:
        logger.debug("Tier %s: no provider available, using global LLM", tier.value)

    return get_llm()
