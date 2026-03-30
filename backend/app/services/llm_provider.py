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
    SIMPLE = "simple"    # Tier 1 — Ollama local (qwen2.5:7b-instruct)
    MEDIUM = "medium"    # Tier 2 — GLM-4.7 → Gemini → Claude (fallback chain)
    COMPLEX = "complex"  # Tier 3 — GLM-4.7 → Claude → Gemini (fallback chain)
    IMAGE = "image"      # Tier 4 — Gemini → GLM (fallback)


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
            "anthropic": "api_key_anthropic",
            "mistral":   "api_key_mistral",
            "gemini":    "api_key_gemini",
            "deepseek":  "api_key_deepseek",
            "zhipu":     "api_key_zhipu",
        }
        for prov, cfg_key in key_map.items():
            val = await get_config(cfg_key, "")
            if val:
                _runtime[f"key_{prov}"] = val

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
    if gemini_key and current_provider != "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            candidates.append(("gemini/gemini-2.0-flash", ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
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

    mistral_key = _key("mistral", settings.mistral_api_key)
    if mistral_key and current_provider != "mistral":
        try:
            from langchain_mistralai import ChatMistralAI
            candidates.append(("mistral/mistral-small-latest", ChatMistralAI(
                model="mistral-small-latest",
                api_key=mistral_key,
                max_tokens=4096,
                temperature=0.7,
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
# Tier-based LLM selector
# ---------------------------------------------------------------------------

def get_llm_for_tier(tier: ComplexityTier) -> BaseChatModel:
    """Return the appropriate LLM for a given complexity tier.

    Tier routing (Mistral removed — replaced by GLM-4.7 as primary):
        SIMPLE  → Ollama qwen2.5:7b-instruct  (local, free, zero latency)
        MEDIUM  → GLM-4.7 → Gemini 2.0 Flash → Claude Sonnet (fallback chain)
        COMPLEX → GLM-4.7 → Claude Sonnet (prompt-caching) → Gemini (fallback)
        IMAGE   → Gemini 2.0 Flash → GLM (fallback)

    GLM-4.7 (Zhipu AI) advantages:
      - Excellent function-calling / tool-use for agentic tasks
      - Handles complex JSON schemas correctly
      - Automatic prefix caching (cached tokens billed at ~1/5 price)
      - OpenAI-compatible API — no content="" serialization bug

    Falls back gracefully: if a required API key is unavailable, the next
    option in the chain is tried.  If all fail, get_llm() is returned.
    """
    settings = get_settings()

    def _key(prov: str, env_val: str) -> Optional[str]:
        return _runtime.get(f"key_{prov}") or env_val or None

    if tier == ComplexityTier.SIMPLE:
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model="qwen2.5:7b-instruct",
                base_url=settings.ollama_base_url,
                temperature=0.5,
            )
        except Exception as exc:
            logger.warning("Tier SIMPLE: Ollama unavailable (%s) — falling back to global LLM", exc)
            return get_llm()

    if tier == ComplexityTier.MEDIUM:
        # GLM-4.7 — primary for MEDIUM: strong function-calling, automatic prefix caching,
        # no content="" serialization bug (unlike Mistral), affordable pricing.
        zhipu_key = _key("zhipu", settings.zhipu_api_key)
        if zhipu_key:
            try:
                return _make_glm(model="glm-4.7", api_key=zhipu_key)
            except Exception as exc:
                logger.warning("Tier MEDIUM: GLM-4.7 unavailable (%s) — trying Gemini", exc)
        else:
            logger.debug("Tier MEDIUM: no Zhipu key — trying Gemini")

        # Gemini as first fallback
        gemini_key = _key("gemini", settings.gemini_api_key)
        if gemini_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model="gemini-2.0-flash",
                    google_api_key=gemini_key,
                    max_output_tokens=4096,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier MEDIUM: Gemini unavailable (%s) — trying Claude", exc)

        # Claude as last resort for MEDIUM
        anthropic_key = _key("anthropic", settings.anthropic_api_key)
        if anthropic_key:
            try:
                return _make_anthropic(
                    model="claude-sonnet-4-6",
                    api_key=anthropic_key,
                    max_tokens=4096,
                )
            except Exception as exc:
                logger.warning("Tier MEDIUM: Claude unavailable (%s) — using global LLM", exc)

        return get_llm()

    if tier == ComplexityTier.COMPLEX:
        # GLM-4.7 — tested first even for COMPLEX: excels at multi-step tool use
        # and JSON schemas. Automatic prefix caching reduces cost on repeated system prompts.
        zhipu_key = _key("zhipu", settings.zhipu_api_key)
        if zhipu_key:
            try:
                return _make_glm(model="glm-4.7", api_key=zhipu_key, max_tokens=8192)
            except Exception as exc:
                logger.warning("Tier COMPLEX: GLM-4.7 unavailable (%s) — trying Claude", exc)
        else:
            logger.debug("Tier COMPLEX: no Zhipu key — trying Claude")

        # Claude as primary fallback — prompt caching enabled (system prompt cached,
        # up to 90 % cost reduction on subsequent turns with the same system prompt)
        anthropic_key = _key("anthropic", settings.anthropic_api_key)
        if anthropic_key:
            try:
                return _make_anthropic(
                    model="claude-sonnet-4-6",
                    api_key=anthropic_key,
                    max_tokens=8192,
                )
            except Exception as exc:
                logger.warning("Tier COMPLEX: Claude unavailable (%s) — trying Gemini", exc)

        # Gemini as final fallback
        gemini_key = _key("gemini", settings.gemini_api_key)
        if gemini_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model="gemini-2.0-flash",
                    google_api_key=gemini_key,
                    max_output_tokens=8192,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier COMPLEX: Gemini unavailable (%s) — using global LLM", exc)

        logger.warning("Tier COMPLEX: all providers unavailable — using global LLM")
        return get_llm()

    if tier == ComplexityTier.IMAGE:
        # Gemini first — best image understanding/generation support
        gemini_key = _key("gemini", settings.gemini_api_key)
        if gemini_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model="gemini-2.0-flash",
                    google_api_key=gemini_key,
                    max_output_tokens=4096,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier IMAGE: Gemini unavailable (%s) — trying GLM", exc)

        # GLM as fallback for IMAGE
        zhipu_key = _key("zhipu", settings.zhipu_api_key)
        if zhipu_key:
            try:
                return _make_glm(model="glm-4.7", api_key=zhipu_key)
            except Exception as exc:
                logger.warning("Tier IMAGE: GLM unavailable (%s) — using global LLM", exc)

        logger.warning("Tier IMAGE: all providers unavailable — using global LLM")
        return get_llm()

    # Should never reach here
    return get_llm()
