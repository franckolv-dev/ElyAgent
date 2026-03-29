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
    MEDIUM = "medium"    # Tier 2 — Mistral mistral-small-latest
    COMPLEX = "complex"  # Tier 3 — Claude → Gemini → Mistral (fallback chain)
    IMAGE = "image"      # Tier 4 — Gemini → Mistral (fallback)


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
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=_key("anthropic", settings.anthropic_api_key),
            max_tokens=4096,
            temperature=0.7,
        )

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
        # DeepSeek exposes an OpenAI-compatible API
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
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=_key("anthropic", settings.anthropic_api_key),
            max_tokens=4096,
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

    Tier routing:
        SIMPLE  → Ollama qwen2.5:7b-instruct (local, zero latency)
        MEDIUM  → Mistral mistral-small-latest
        COMPLEX → Claude claude-sonnet-4-6 → Gemini gemini-2.0-flash → Mistral (fallback)
        IMAGE   → Gemini gemini-2.0-flash → Mistral (fallback)

    Falls back gracefully: if a required API key is unavailable, the next
    option in the chain is tried.  If all fail, get_llm() (global default) is returned.
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
        # Gemini first for MEDIUM: Mistral has a bug where it rejects AIMessage history
        # entries that have content="" AND tool_calls present (langchain_mistralai
        # serializes content="" instead of null when the `if tool_calls and content`
        # condition at line 418 is skipped because "" is falsy). Gemini handles this
        # correctly and is equally fast/cheap for MEDIUM tasks.
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
                logger.warning("Tier MEDIUM: Gemini unavailable (%s) — trying Mistral", exc)
        else:
            logger.debug("Tier MEDIUM: no Gemini key — trying Mistral")
        # Mistral as fallback (single-turn queries only — no tool-call history)
        mistral_key = _key("mistral", settings.mistral_api_key)
        if mistral_key:
            try:
                from langchain_mistralai import ChatMistralAI
                return ChatMistralAI(
                    model="mistral-small-latest",
                    api_key=mistral_key,
                    max_tokens=4096,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier MEDIUM: Mistral unavailable (%s) — falling back to global LLM", exc)
        return get_llm()

    if tier == ComplexityTier.COMPLEX:
        # Try Claude first
        anthropic_key = _key("anthropic", settings.anthropic_api_key)
        if anthropic_key:
            try:
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model="claude-sonnet-4-6",
                    api_key=anthropic_key,
                    max_tokens=8192,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier COMPLEX: Claude unavailable (%s) — trying Gemini", exc)

        # Try Gemini as first fallback
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
                logger.warning("Tier COMPLEX: Gemini unavailable (%s) — trying Mistral", exc)

        # Final fallback: Mistral
        mistral_key = _key("mistral", settings.mistral_api_key)
        if mistral_key:
            try:
                from langchain_mistralai import ChatMistralAI
                return ChatMistralAI(
                    model="mistral-small-latest",
                    api_key=mistral_key,
                    max_tokens=4096,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier COMPLEX: Mistral unavailable (%s) — falling back to global LLM", exc)

        logger.warning("Tier COMPLEX: all providers unavailable — using global LLM")
        return get_llm()

    if tier == ComplexityTier.IMAGE:
        # Try Gemini first (supports image generation)
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
                logger.warning("Tier IMAGE: Gemini unavailable (%s) — trying Mistral", exc)

        # Fallback: Mistral
        mistral_key = _key("mistral", settings.mistral_api_key)
        if mistral_key:
            try:
                from langchain_mistralai import ChatMistralAI
                return ChatMistralAI(
                    model="mistral-small-latest",
                    api_key=mistral_key,
                    max_tokens=4096,
                    temperature=0.7,
                )
            except Exception as exc:
                logger.warning("Tier IMAGE: Mistral unavailable (%s) — using global LLM", exc)

        logger.warning("Tier IMAGE: all providers unavailable — using global LLM")
        return get_llm()

    # Should never reach here
    return get_llm()
