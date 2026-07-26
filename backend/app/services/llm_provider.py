# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/llm_provider.py
# @brief      LLM provider abstraction and routing
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DeepSeek thinking-mode workaround
# ---------------------------------------------------------------------------
# DeepSeek v4-flash and v4-pro have « thinking mode » ENABLED by default.
# When on, the API response includes a `reasoning_content` field that, in
# multi-turn flows WITH tool_calls, MUST be replayed verbatim on every
# subsequent request — see https://api-docs.deepseek.com/guides/thinking_mode :
#
#   « With tool calls: the intermediate assistant's reasoning_content
#     must participate in the context concatenation and must be passed
#     back to the API »
#
# LangChain doesn't preserve this DeepSeek-specific field, so turn 2 fails
# with HTTP 400 « The reasoning_content in the thinking mode must be
# passed back to the API » — exact symptom Franck observed 2026-05-09.
#
# DeepSeek documents the official disable mechanism:
#
#   extra_body={"thinking": {"type": "disabled"}}
#
# Passing this turns thinking off for the call without changing the model
# identifier. We use this approach (preserves the model name end-to-end —
# HUD, dashboard stats, pricing analytics all stay accurate) for the
# v4-* identifiers. `deepseek-reasoner` is left alone — picking it
# explicitly opts in to thinking and accepts the multi-turn limitation.
# `deepseek-chat` doesn't have thinking by default so the param is a no-op
# but harmless to pass.

_DEEPSEEK_THINKING_DEFAULT_MODELS = frozenset({
    "deepseek-v4-flash",
    "deepseek-v4-pro",
})


def _deepseek_disable_thinking(model: str) -> bool:
    """Return True if we should pass `thinking={"type": "disabled"}` for
    this model identifier — i.e. the user picked one of the v4-* aliases
    where thinking is on by default and would break multi-turn tool_calls.

    Returns False for `deepseek-reasoner` (explicit opt-in to thinking)
    and `deepseek-chat` (already non-thinking, no need to override).
    Unknown identifiers also return False — better to surface a real
    DeepSeek error than to inject params blindly.
    """
    return model in _DEEPSEEK_THINKING_DEFAULT_MODELS


def _deepseek_extra_body(model: str) -> dict:
    """Return the `extra_body` dict to pass to ChatOpenAI for this DeepSeek
    model. Empty dict if no override is needed (caller can spread `**` it
    safely)."""
    if _deepseek_disable_thinking(model):
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


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
    # Tier S — génération d'outils et de compétences (services/learning/*).
    # Ajouté le 22/07/2026 : cette voie avait sa PROPRE chaîne codée en dur
    # (anthropic → Opus 4.5) qui ignorait cette config et n'apparaissait nulle
    # part dans l'UI. Défaut volontairement NON-anthropic, pour ne pas
    # réintroduire une facturation que l'admin n'a pas choisie.
    "skill":       {"providers": ["deepseek"],                      "fallback_enabled": True},
}

_tier_config: dict[str, dict] = {}   # empty = use DEFAULT_TIER_CONFIG

# Bumped every time `set_tier_config()` runs. Downstream caches (notably
# `_tier_llm_cache` in `app/agent/nodes.py` and any per-tier client cache
# in sub-agent factories) MUST check this version and invalidate when it
# changes. Without this, swapping a model in Settings → Routing has no
# runtime effect — the previous client object stays in cache and continues
# to be served on every agent_node call. (Audit C-4, fixed 2026-05-06.)
_tier_config_version: int = 0


def set_tier_config(config: dict) -> None:
    """Replace the in-memory tier routing config (called on startup + after PUT /tiers).

    Also bumps `_tier_config_version` so that any downstream LLM cache
    keyed on tier identity will rebuild its clients on next use.
    """
    global _tier_config, _tier_config_version
    _tier_config = config
    _tier_config_version += 1
    logger.info(
        "Tier config updated (v=%d): %s",
        _tier_config_version, list(config.keys()),
    )


def get_tier_config() -> dict[str, dict]:
    """Return the active tier routing config (DB override or defaults).

    PII sovereignty (2026-06-07): when the current asyncio task has
    ``SOVEREIGNTY_STRICT`` set (the calling user opted in), cloud tiers
    (MEDIUM, COMPLEX) are rewritten to the Mistral EU chain. SIMPLE +
    MAINTENANCE keep their local providers; IMAGE is unchanged. If no
    Mistral instance is configured, the original config is returned
    untouched (graceful fallback with a one-time warning from
    sovereignty.get_sovereign_provider_ids).
    """
    base = _tier_config if _tier_config else DEFAULT_TIER_CONFIG
    try:
        from app.services.sovereignty import (
            SOVEREIGNTY_STRICT,
            sovereign_chain_for_tier,
        )
        if not SOVEREIGNTY_STRICT.get():
            return base
    except Exception:  # noqa: BLE001 — never crash routing on a stray import
        return base

    overridden = dict(base)  # shallow copy — we only swap a couple of tier entries
    for tier_name in ("medium", "complex"):
        chain = sovereign_chain_for_tier(tier_name)
        if chain:
            overridden[tier_name] = {"providers": chain, "fallback_enabled": True}
    return overridden


def get_tier_config_version() -> int:
    """Monotonic version counter — bumped on every `set_tier_config()`.

    Caches downstream (see `app/agent/nodes.py:_tier_llm_cache`) check this
    to know when to invalidate their precomputed `bind_tools()` clients.
    """
    return _tier_config_version


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
            "qwen_api":    "api_key_qwen_api",
            "openai":      "api_key_openai",
            "moonshot":    "api_key_moonshot",
        }
        for prov, cfg_key in key_map.items():
            val = await get_config(cfg_key, "")
            if val:
                _runtime[f"key_{prov}"] = val

        # Load Qwen API base_url (region-scoped DashScope endpoint)
        qwen_base = await get_config("qwen_api_base_url", "")
        if qwen_base:
            _runtime["qwen_api_base_url"] = qwen_base

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

        # Load LLM instances into in-memory cache
        await load_llm_instances_from_db()

    except Exception as exc:
        logger.warning("load_llm_settings_from_db failed (will use env defaults): %s", exc)


def get_slm() -> BaseChatModel:
    """Return the local Small Language Model for simple requests.

    Uses the SIMPLE tier configured in Settings → Routage (honored via
    instance cache) rather than the static slm_model setting — so users
    can swap their local model without restarting the backend.
    Falls back to settings.slm_model via Ollama if no SIMPLE tier instance
    is configured (preserves the legacy behavior).
    """
    # Prefer the user's configured SIMPLE tier so we respect the same
    # model they selected in the UI (avoids pointing at a deleted Ollama model).
    try:
        llm = get_llm_for_tier(ComplexityTier.SIMPLE)
        return llm
    except Exception:
        pass

    settings = get_settings()
    from langchain_ollama import ChatOllama
    return ChatOllama(model=settings.slm_model,
        base_url=settings.ollama_base_url,
        temperature=0.7, keep_alive="24h",
        async_client_kwargs=_local_ollama_limits())


# ── A-5 (revue 2026-06-10) — porte de concurrence LLM local ─────────────
# LM Studio / MLX sur Mac ne sert qu'UNE requête à la fois : N requêtes
# simultanées (N users, ou chat + cron MAINTENANCE) s'empilent côté serveur
# sans aucun signal, chacune payant le prompt processing complet des
# précédentes, jusqu'au timeout 900 s. On borne au niveau TRANSPORT : un
# httpx.AsyncClient PARTAGÉ par base_url avec max_connections=N — la N+1ᵉ
# requête attend une connexion du pool (file d'attente côté client) au lieu
# de s'empiler côté serveur. Couvre ainvoke/astream/bind_tools sans wrapper.
# Env : LOCAL_LLM_MAX_CONCURRENCY (défaut 1 — c'est la réalité du serveur).

_LOCAL_HTTPX_CLIENTS: dict[str, "httpx.AsyncClient"] = {}

# B-1 — référence forte sur le chargement paresseux des settings LLM
# (programmé en fond par get_llm_for_tier quand le cache est froid).
_lazy_settings_task = None


def _local_llm_async_client(base_url: str) -> "httpx.AsyncClient":
    import os

    import httpx

    client = _LOCAL_HTTPX_CLIENTS.get(base_url)
    if client is None or client.is_closed:
        n = max(1, int(os.environ.get("LOCAL_LLM_MAX_CONCURRENCY", "1")))
        client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=n, max_keepalive_connections=n),
            # pool=900 : une requête en file peut attendre jusqu'au deadline
            # global — c'est voulu, la file est bornée par le timeout requête.
            timeout=httpx.Timeout(900.0, connect=10.0),
        )
        _LOCAL_HTTPX_CLIENTS[base_url] = client
    return client


def _local_ollama_limits() -> dict:
    """``async_client_kwargs`` pour ChatOllama — même borne que LM Studio.

    Scope par-instance (le client ollama construit son propre httpx.Client),
    donc moins strict que le client partagé LM Studio, mais borne quand même
    l'empilement d'une instance donnée. La stack locale documentée est
    LM Studio ; Ollama reste un chemin legacy/fallback.
    """
    import os

    import httpx

    n = max(1, int(os.environ.get("LOCAL_LLM_MAX_CONCURRENCY", "1")))
    return {
        "limits": httpx.Limits(max_connections=n, max_keepalive_connections=n),
    }


def _make_lm_studio(model: str, base_url: str, max_tokens: int = 4096, temperature: float = 0.1) -> BaseChatModel:
    """Instantiate a model served by LM Studio (OpenAI-compatible local API).

    LM Studio exposes an OpenAI-compatible endpoint at http://localhost:1234/v1
    (accessible from Docker via host.docker.internal).  No real API key is
    required; we pass the conventional dummy value "lm-studio" that LM Studio
    itself suggests in its documentation.

    The model name must match exactly what LM Studio shows in its
    "Local Server" tab (e.g. "gemma-4-26b-a4b-it-mlx").

    ┌─ Note perf (2026-04-23) ─────────────────────────────────────────────┐
    │ Defaults optimized for local tool-calling:                           │
    │ - temperature=0.1 (was 0.7): drastically reduces JSON hallucinations │
    │   on tool_call outputs. Gemma 4 MLX follows schemas much better at   │
    │   low T. User can still bump it via LM Studio UI for chat-only work. │
    │ - No streaming=False override: langchain_openai picks the right mode │
    │   based on the caller.                                               │
    └──────────────────────────────────────────────────────────────────────┘
    """
    from langchain_openai import ChatOpenAI
    # ── Thinking disabled for Qwen 3.5+ ────────────────────────────────
    # Qwen 3.5 does NOT honor the `/no_think` marker (unlike Qwen 3).
    # Its thinking must be disabled at API level via
    # `chat_template_kwargs.enable_thinking=False` in the request body.
    # Without this flag, the model burns 100 % of its `max_tokens` inside
    # the <think> block and never emits the real answer (content="" +
    # finish_reason="length"). Confirmed on `qwen3.5-9b-mlx` 2026-04-23.
    #
    # We inject `enable_thinking=False` unconditionally for LM Studio
    # because :
    #   - Qwen 2.5 : parameter is ignored (no thinking concept) → harmless
    #   - Qwen 3   : parameter is ignored, `/no_think` in content still works
    #   - Qwen 3.5+: parameter is the ONLY way to disable thinking
    #   - Gemma / Mistral / Llama served via LM Studio : ignored → harmless
    # If a user genuinely wants thinking on for a reasoning model, they can
    # override via the LM Studio UI (system prompt).
    # Stop tokens — anti-self-dialogue (audit 2026-05-07).
    # Small models (Ministral 3 8B, Mistral 7B…) often "continue" the
    # conversation by hallucinating both sides of the dialogue
    # ("C'est ça ? \n Oui exactement. Toi… / Moi…"). Adding model-family
    # stop tokens forces the inference to halt at the natural turn boundary.
    # We only add stops that NEVER appear in legitimate tool calls or
    # markdown output to avoid cutting valid responses.
    _model_lc = (model or "").lower()
    _stops: list[str] = []
    if "mistral" in _model_lc or "ministral" in _model_lc:
        # Mistral instruct format: next-turn opens with [INST]
        _stops.extend(["[INST]", "</s>"])
    if "qwen" in _model_lc or "llama" in _model_lc:
        # ChatML format used by many Qwen/Llama variants
        _stops.extend(["<|im_end|>", "<|im_start|>user"])
    if "gemma" in _model_lc:
        _stops.append("<end_of_turn>")
    if "gpt-oss" in _model_lc or "gpt_oss" in _model_lc or _model_lc.startswith("openai/gpt-oss"):
        # OpenAI gpt-oss uses the « Harmony » response format with these
        # control tokens. Without them the model can run past its turn
        # boundary and emit malformed continuations.
        _stops.extend(["<|return|>", "<|endoftext|>"])

    _kwargs = {
        "model": model,
        "api_key": "lm-studio",       # LM Studio ignores the key — required by LangChain
        "base_url": base_url,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # FIX 2026-05-06: timeout explicite à 15 min. Sans ça, le client httpx
        # tombait sur ~300s (défaut openai SDK) → "Client disconnected" alors
        # que LM Studio finissait son prompt processing 30s plus tard sur du
        # local lent (gros prompt + Mac Studio sous charge). 900s couvre les
        # pires cas pratiques tout en évitant les leaks de connexion en cas
        # de bug LM Studio. Voir audit H-4.
        "timeout": 900.0,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        # A-5 — client async partagé par base_url, max_connections borné :
        # la concurrence vers le serveur local mono-requête est sérialisée
        # côté client au lieu de s'empiler côté LM Studio.
        "http_async_client": _local_llm_async_client(base_url),
    }
    if _stops:
        _kwargs["model_kwargs"] = {"stop": _stops}
    return ChatOpenAI(**_kwargs)


def _make_qwen_api(
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> BaseChatModel:
    """Instantiate a Qwen model served by Alibaba Cloud DashScope (cloud API).

    The endpoint is OpenAI-compatible, so we use `ChatOpenAI`. The typical
    base_url is region-scoped, e.g.:
      - EU : https://ws-<id>.eu-central-1.maas.aliyuncs.com/compatible-mode/v1
      - CN : https://dashscope.aliyuncs.com/compatible-mode/v1

    Models available (2026) : qwen3.6-plus, qwen3.6-max, qwen-plus-latest,
    qwen-max-latest, qwen2.5-vl-72b-instruct, qwen-turbo-latest, etc.

    Like LM Studio we inject `chat_template_kwargs.enable_thinking=False`
    to tame Qwen 3.5/3.6 thinking mode — Alibaba's API honors this flag
    (unlike LM Studio which has a known bug).

    Temperature default 0.1 for function-calling stability.
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
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


def _make_moonshot(model: str, api_key: str, base_url: str = "", max_tokens: int = 4096, temperature: float = 0.7) -> BaseChatModel:
    """Instantiate Kimi (Moonshot AI) via leur endpoint OpenAI-compatible.

    Moonshot publie Kimi K1.5, K2, K2.6 — modèles taillés pour l'agentique
    (long contexte, function calling natif solide). Endpoint international :
    https://api.moonshot.ai/v1 — région CN : https://api.moonshot.cn/v1
    Doc : https://platform.moonshot.ai/docs/api/chat

    Kimi K2.x sont des modèles **reasoning** : l'API renvoie une 400
    « invalid temperature: only 1 is allowed for this model » si on essaie
    d'envoyer autre chose que ``temperature=1``. On force donc 1 pour ces
    modèles (la valeur ``temperature`` passée par le tier router est ignorée
    de toute façon par le sampler côté Moonshot — pas de perte de qualité).
    """
    from langchain_openai import ChatOpenAI
    # Kimi K2.x = reasoning model → temperature forcée à 1
    _model_lower = (model or "").lower()
    if "k2" in _model_lower or "k1.5" in _model_lower or "thinking" in _model_lower:
        temperature = 1.0
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url or "https://api.moonshot.ai/v1",
        max_tokens=max_tokens,
        temperature=temperature,
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
            max_tokens=_output_cap(model),
            temperature=0.7,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model,
            base_url=settings.ollama_base_url,
            temperature=0.7, keep_alive="24h",
            async_client_kwargs=_local_ollama_limits())

    elif provider == "lm_studio":
        return _make_lm_studio(model=model, base_url=settings.lm_studio_base_url)

    elif provider == "qwen_api":
        return _make_qwen_api(
            model=model,
            api_key=_key("qwen_api", settings.qwen_api_key),
            base_url=_runtime.get("qwen_api_base_url") or settings.qwen_api_base_url,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_key("deepseek", settings.deepseek_api_key),
            base_url="https://api.deepseek.com/v1",
            max_tokens=_output_cap(model),
            temperature=0.7,
        )

    elif provider == "moonshot":
        return _make_moonshot(
            model=model,
            api_key=_key("moonshot", settings.moonshot_api_key),
            base_url=settings.moonshot_base_url,
        )

    elif provider == "openrouter":
        return _make_openrouter(
            model=model,
            api_key=_key("openrouter", settings.openrouter_api_key),
        )

    elif provider == "openai":
        # Real OpenAI (GPT-4o, GPT-4o-mini, GPT-5.x, o1, o3, …).
        # Native function-calling, vision support, exceptional instruction
        # following — strong fit for tier MEDIUM/COMPLEX and the diag agent.
        # `openai_base_url` lets users target Azure OpenAI or a private proxy.
        # FIX 2026-05-06 (audit C-1): use hardcoded defaults consistent with
        # the other branches in get_llm() — previously referenced
        # `max_tokens` / `temperature` from an outer scope that does not
        # exist here, causing NameError on first call.
        from langchain_openai import ChatOpenAI
        _base = _runtime.get("openai_base_url") or settings.openai_base_url or None
        kw = {
            "model": model,
            "api_key": _key("openai", settings.openai_api_key),
            "max_tokens": 4096,
            "temperature": 0.7,
        }
        if _base:
            kw["base_url"] = _base
        return ChatOpenAI(**kw)

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=_key("gemini", settings.gemini_api_key),
            max_output_tokens=_output_cap(model),
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

    # PERF/UX: the user may have configured keys only via the Settings UI
    # (stored in llm_instances.api_key). Those keys don't live in
    # settings.* or _runtime. Pick them up so fallbacks work when only
    # instance-based config is present (typical after UI-driven setup).
    def _instance_key_for(provider_name: str) -> str:
        for inst in _instance_cache.values():
            if inst.get("provider") == provider_name and inst.get("api_key"):
                return inst["api_key"]
        warn_legacy_default("gemini", "gemini-2.5-flash")
        return ""

    gemini_key = _key("gemini", settings.gemini_api_key) or _instance_key_for("gemini")
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
                    max_output_tokens=_output_cap(model),
                    temperature=0.7,
                )))
            except Exception:
                pass

    anthropic_key = _key("anthropic", settings.anthropic_api_key) or _instance_key_for("anthropic")
    if anthropic_key and current_provider != "anthropic":
        # Prefer the exact model the user has configured in their instance
        # (e.g. claude-haiku-4-5) to avoid jumping to a more expensive Sonnet.
        _anthropic_model = "claude-haiku-4-5-20251001"
        for inst in _instance_cache.values():
            if inst.get("provider") == "anthropic" and inst.get("model"):
                _anthropic_model = inst["model"]
                break
        try:
            candidates.append((f"anthropic/{_anthropic_model}", _make_anthropic(
                model=_anthropic_model,
                api_key=anthropic_key,
            )))
        except Exception:
            pass

    # Mistral intentionally excluded from automatic fallback:
    # - Requires content="" sanitization on AIMessage (not None)
    # - Breaks on multi-step tool-calling history (error code 3240)
    # - Poor tool choice compliance with large tool lists
    # Mistral remains selectable manually via settings, but never used as auto-fallback.

    openrouter_key = _key("openrouter", settings.openrouter_api_key) or _instance_key_for("openrouter")
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
            candidates.append(("ollama/qwen2.5:7b-instruct", ChatOllama(model="qwen2.5:7b-instruct",
                base_url=settings.ollama_base_url,
                temperature=0.7, keep_alive="24h")))
        except Exception:
            pass

    return candidates


def get_llm_for_agent(config: "SubAgentConfig") -> BaseChatModel:  # type: ignore[name-defined]
    """Instantiate a LLM for a specific sub-agent.

    If ``config.llm_provider`` is None, delegates to ``get_llm()`` so that
    the globally-configured provider/model is used.  When a sub-agent carries
    its own provider/model, a dedicated instance is created from _runtime keys.
    """
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
            max_tokens=_output_cap(model),
            temperature=temperature,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature, keep_alive="24h")

    elif provider == "lm_studio":
        return _make_lm_studio(model=model, base_url=settings.lm_studio_base_url, temperature=temperature)

    elif provider == "qwen_api":
        return _make_qwen_api(
            model=model,
            api_key=_key("qwen_api", settings.qwen_api_key),
            base_url=_runtime.get("qwen_api_base_url") or settings.qwen_api_base_url,
            temperature=temperature,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=_key("deepseek", settings.deepseek_api_key),
            base_url="https://api.deepseek.com/v1",
            max_tokens=_output_cap(model),
            temperature=temperature,
        )

    elif provider == "moonshot":
        return _make_moonshot(
            model=model,
            api_key=_key("moonshot", settings.moonshot_api_key),
            base_url=settings.moonshot_base_url,
            temperature=temperature,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=_key("gemini", settings.gemini_api_key),
            max_output_tokens=_output_cap(model),
            temperature=temperature,
        )

    else:
        raise ValueError(f"Unknown LLM provider for sub-agent '{config.name}': {provider}")


# ---------------------------------------------------------------------------
# Low-level provider factory — shared by tier routing and fallback helpers
# ---------------------------------------------------------------------------

def _make_openai_codex(model: str, temperature: float) -> "BaseChatModel":
    """ChatOpenAI sur le backend codex (abonnement ChatGPT) — partagé par le
    chemin instances ET le chemin legacy du Routage (bug 12 juin : l'entrée
    legacy « openai_codex » du dropdown tombait dans _make_llm_for_provider
    qui ne la connaissait pas → skip silencieux vers le fallback du tier).

    Contraintes du backend codex, validées par spike live (12 juin) :
    stream=true OBLIGATOIRE, store=false OBLIGATOIRE (stateless),
    `instructions` top-level OBLIGATOIRE (les SystemMessage de la conv
    restent honorés en plus), max_output_tokens REJETÉ (ne pas passer
    max_tokens). temperature acceptée. output_version="v0" épure le
    content des blocs reasoning (sinon ils partent au TTS/sanitizer).

    Construit SANS vérifier la connexion (l'état vit en DB, illisible en
    sync) : si l'abonnement n'est pas connecté, CodexAuthError part au
    premier appel et classify_exception la route en AUTH → la chaîne du
    tier bascule proprement au lieu de tuer le tour.
    """
    import httpx as _httpx

    from langchain_openai import ChatOpenAI

    from app.services.openai_codex_auth import CODEX_BASE_URL, CodexBearerAuth
    _codex_auth = CodexBearerAuth()
    return ChatOpenAI(
        model=model,
        # Placeholder jamais accepté côté serveur : l'Authorization réelle
        # est posée (écrasée) par CodexBearerAuth à chaque requête. Requis
        # car le SDK refuse une clé vide.
        api_key="codex-subscription",
        base_url=CODEX_BASE_URL,
        use_responses_api=True,
        streaming=True,
        store=False,
        output_version="v0",
        temperature=temperature,
        # store=false → le serveur ne persiste RIEN : sans ceci, dès que le
        # modèle émet du reasoning (prompts lourds), le tour suivant rejoue
        # l'item par référence rs_… → 404 « Item not found » → bascule
        # fallback systématique (bug terrain 12 juin, repro + fix validés
        # live). Avec, le reasoning revient CHIFFRÉ et se rejoue complet,
        # sans persistance côté serveur.
        include=["reasoning.encrypted_content"],
        model_kwargs={
            "instructions": "Suis les messages système fournis dans la conversation.",
        },
        http_async_client=_httpx.AsyncClient(auth=_codex_auth, timeout=120.0),
        http_client=_httpx.Client(auth=_codex_auth, timeout=120.0),
    )


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
        return ChatOllama(model=settings.slm_model or "qwen2.5:7b-instruct",
            base_url=settings.ollama_base_url,
            temperature=temperature, keep_alive="24h")

    if provider_id == "lm_studio":
        # No key needed — use the model currently loaded in LM Studio.
        # The model name must match what LM Studio shows in its "Local Server" tab.
        return _make_lm_studio(model=settings.slm_model or "gemma-4-26B-A4B-it-MLX-4bit",
                               base_url=settings.lm_studio_base_url,
                               max_tokens=max_tokens, temperature=temperature)

    if provider_id == "openai_codex":
        # Abonnement ChatGPT — pas de clé API (connexion par import des
        # tokens du CLI, voir openai_codex_auth). Modèle par défaut du
        # provider ; pour en choisir un autre, créer une INSTANCE.
        warn_legacy_default("openai_codex", "gpt-5.5")
        return _make_openai_codex(model="gpt-5.5", temperature=temperature)

    if provider_id == "qwen_api":
        key = _key("qwen_api", settings.qwen_api_key)
        base_url = _runtime.get("qwen_api_base_url") or settings.qwen_api_base_url
        if not key or not base_url:
            return None
        warn_legacy_default("qwen_api", "qwen-plus-latest")
        return _make_qwen_api(
            model="qwen-plus-latest",  # safe default, can be overridden via instance
            api_key=key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider_id == "zhipu":
        key = _key("zhipu", settings.zhipu_api_key)
        if not key:
            return None
        warn_legacy_default("zhipu", "glm-4.7")
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
        warn_legacy_default("anthropic", "claude-sonnet-4-6")
        return _make_anthropic(model="claude-sonnet-4-6", api_key=key,
                               max_tokens=max_tokens, temperature=temperature)

    if provider_id == "mistral":
        key = _key("mistral", settings.mistral_api_key)
        if not key:
            return None
        from langchain_mistralai import ChatMistralAI
        warn_legacy_default("mistral", "mistral-small-latest")
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
        # Default to v4-flash (modern, 1M context) with thinking explicitly
        # disabled via extra_body — see _deepseek_extra_body() for the
        # multi-turn rationale. Override the model per-instance via the
        # LlmInstance.model field on the Paramètres → Modèles IA page.
        _default_model = "deepseek-v4-flash"
        return ChatOpenAI(
            model=_default_model,
            api_key=key,
            base_url="https://api.deepseek.com/v1",
            max_tokens=max_tokens,
            temperature=temperature,
            **_deepseek_extra_body(_default_model),
        )

    if provider_id == "moonshot":
        key = _key("moonshot", settings.moonshot_api_key)
        if not key:
            return None
        # Default model when the tier picks "moonshot" without specifying one.
        # Override per-instance via la table llm_instances depuis la page
        # « Modèles IA » des paramètres.
        return _make_moonshot(
            model="kimi-k2-0905-preview",
            api_key=key,
            base_url=settings.moonshot_base_url,
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

# ---------------------------------------------------------------------------
# In-memory instance cache — populated at startup and updated on CRUD ops.
# Shape: { "<uuid>": {"provider": str, "model": str, "api_key": str | None} }
# ---------------------------------------------------------------------------
_instance_cache: dict[str, dict] = {}


def register_instance_cache(instance_id: str, provider: str, model: str, api_key: Optional[str]) -> None:
    """Add or update an instance in the in-memory cache."""
    _instance_cache[instance_id] = {"provider": provider, "model": model, "api_key": api_key}


def unregister_instance_cache(instance_id: str) -> None:
    """Remove an instance from the in-memory cache."""
    _instance_cache.pop(instance_id, None)


def _apply_instance_overrides(instances) -> None:
    """Applique fenêtre, tarifs et plafond de sortie déclarés sur les instances.

    C'est ici, et seulement ici, que la configuration de l'utilisateur atteint
    le calcul de contexte et de coût. Ne lève jamais : un rafraîchissement est
    l'effet de bord d'un enregistrement réussi, il ne doit pas faire échouer la
    sauvegarde.
    """
    try:
        from app.services.context_manager import set_instance_overrides

        set_instance_overrides(
            windows={
                i.model: i.context_window
                for i in instances if i.model and i.context_window
            },
            outputs={
                i.model: i.max_output_tokens
                for i in instances if i.model and i.max_output_tokens
            },
            prices={
                i.model: (i.input_price_per_million, i.output_price_per_million)
                for i in instances
                if i.model
                and i.input_price_per_million is not None
                and i.output_price_per_million is not None
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("valeurs d'instance non appliquées : %s", exc)


async def refresh_instance_overrides() -> None:
    """Relit les instances et réapplique leurs valeurs.

    #272 ne peuplait le registre qu'au DÉMARRAGE : Franck saisissait ses
    tarifs, la base les gardait, l'écran les réaffichait — et Ely continuait de
    tronquer à 8 192 tokens en facturant un tarif générique jusqu'au prochain
    redémarrage. Les endpoints d'écriture appellent donc ceci.
    """
    try:
        from sqlalchemy import select as _select

        from app.database import async_session as _async_session
        from app.models.llm_instance import LLMInstance

        async with _async_session() as db:
            instances = (await db.execute(_select(LLMInstance))).scalars().all()
        _apply_instance_overrides(instances)
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh_instance_overrides échoué : %s", exc)


async def load_llm_instances_from_db() -> None:
    """Load all LLMInstance rows into the in-memory cache.  Called at startup."""
    try:
        from app.database import async_session as _async_session
        from app.models.llm_instance import LLMInstance
        from sqlalchemy import select as _select

        async with _async_session() as db:
            result = await db.execute(_select(LLMInstance))
            instances = result.scalars().all()

        for inst in instances:
            # B-11 — api_key chiffrée au repos depuis 2026-06-10 ;
            # decrypt() laisse passer le legacy en clair tel quel.
            from app.services.secrets_at_rest import decrypt as _decrypt_key
            register_instance_cache(
                inst.id, inst.provider, inst.model, _decrypt_key(inst.api_key)
            )

        _apply_instance_overrides(instances)

        logger.info("Loaded %d LLM instances from DB into cache", len(instances))
    except Exception as exc:
        logger.warning("load_llm_instances_from_db failed: %s", exc)


def _is_instance_id(value: str) -> bool:
    """Return True if value is a known instance UUID (present in cache)."""
    return value in _instance_cache


# ------------------------------------------------------------------ #
# Chemin historique : résolution par NOM de fournisseur               #
# ------------------------------------------------------------------ #
#
# Un tier peut référencer soit l'UUID d'une instance, soit le NOM d'un
# fournisseur. Le second cas emprunte une cascade de `if` où chaque
# fournisseur impose un modèle CODÉ EN DUR.
#
# Ce que ça a coûté (26/07/2026) : la config avait "openai_codex" en tête de
# medium/complex/image → gpt-5.5 imposé, l'instance gpt-5.6-terra jamais
# atteinte. Et gpt-5.5 n'ayant aucun tarif, `estimate_cost` lui appliquait
# 4,00 USD/million inventés sur la majorité du trafic, quand le modèle voulu
# est au forfait et coûte 0. Rien ne l'a signalé : le chemin marchait, il
# produisait un modèle valide, il était simplement le mauvais.
#
# On ne SUPPRIME pas ce chemin (des configs sans instance en dépendent) et on
# ne SUBSTITUE pas l'instance automatiquement (ambigu dès qu'un fournisseur en
# a plusieurs — deux DeepSeek, trois LM Studio ici). On le rend BRUYANT.

LEGACY_DEFAULT_MODELS: dict[str, str] = {
    "openai_codex": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "deepseek": "deepseek-chat",
    "mistral": "mistral-small-latest",
    "gemini": "gemini-2.5-flash",
    "zhipu": "glm-4.7",
    "qwen_api": "qwen-plus-latest",
}

# Un avertissement par couple (fournisseur, modèle) : le résolveur est appelé
# à chaque tour, et un signal répété se noie aussi sûrement qu'un silence.
_LEGACY_WARNED: set[tuple[str, str]] = set()


def warn_legacy_default(provider_id: str, model: str) -> None:
    """Annonce qu'un modèle est imposé faute d'instance référencée."""
    if (provider_id, model) in _LEGACY_WARNED:
        return
    _LEGACY_WARNED.add((provider_id, model))
    logger.warning(
        "[routage] un tier référence le fournisseur « %s » par son NOM : le "
        "modèle « %s » est imposé en dur, et toute INSTANCE configurée pour ce "
        "fournisseur est ignorée. Pour choisir le modèle, référence "
        "l'identifiant de l'instance dans le tier plutôt que le nom du "
        "fournisseur.",
        provider_id, model,
    )


def _output_cap(model: str, fallback: int = 4096) -> int:
    """Le plafond de sortie déclaré sur l'instance, sinon le repli historique.

    Valait 4 096 en dur à douze endroits, quand certains modèles en autorisent
    65 536 : une réponse longue était coupée net, sans erreur. On ne met PAS un
    plafond large uniforme — un fournisseur refuse une valeur au-dessus de sa
    limite, et sur les serveurs locaux le plafond est prélevé sur la fenêtre.
    """
    try:
        from app.services.context_manager import instance_max_output

        return instance_max_output(model) or fallback
    except Exception:  # noqa: BLE001 — jamais bloquant
        return fallback


def _make_llm_for_instance(instance_id: str, max_tokens: int = 4096, temperature: float = 0.7) -> Optional[BaseChatModel]:
    """Instantiate an LLM from the in-memory instance cache.

    Returns None if the instance is unknown or has no API key for a cloud provider.
    """
    inst = _instance_cache.get(instance_id)
    if inst is None:
        logger.warning("_make_llm_for_instance: instance '%s' not in cache", instance_id)
        return None

    settings = get_settings()
    provider = inst["provider"]
    model = inst["model"]
    # Instance key takes priority, then fall back to runtime/env key for the provider.
    api_key: Optional[str] = inst.get("api_key") or _runtime.get(f"key_{provider}") or None

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, base_url=settings.ollama_base_url, temperature=temperature, keep_alive="24h")

    if provider == "lm_studio":
        # api_key stored in the instance is ignored (LM Studio requires none)
        return _make_lm_studio(model=model, base_url=settings.lm_studio_base_url,
                               max_tokens=max_tokens, temperature=temperature)

    if provider == "qwen_api":
        # Alibaba Cloud DashScope — per-instance api_key overrides runtime/env.
        key = api_key or settings.qwen_api_key
        base_url = _runtime.get("qwen_api_base_url") or settings.qwen_api_base_url
        if not key or not base_url:
            return None
        return _make_qwen_api(
            model=model,
            api_key=key,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider == "anthropic":
        key = api_key or settings.anthropic_api_key
        if not key:
            return None
        return _make_anthropic(model=model, api_key=key, max_tokens=max_tokens, temperature=temperature)

    if provider == "zhipu":
        key = api_key or settings.zhipu_api_key
        if not key:
            return None
        return _make_glm(model=model, api_key=key, max_tokens=max_tokens, temperature=temperature)

    if provider == "gemini":
        key = api_key or settings.gemini_api_key
        if not key:
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=key, max_output_tokens=max_tokens, temperature=temperature)

    if provider == "deepseek":
        key = api_key or settings.deepseek_api_key
        if not key:
            return None
        from langchain_openai import ChatOpenAI
        # See module-level comment on `_deepseek_extra_body` for the
        # full thinking-mode story. Short version: v4-flash and v4-pro
        # have thinking on by default, which breaks multi-turn tool_calls.
        # `extra_body={"thinking": {"type": "disabled"}}` is the official
        # disable mechanism per DeepSeek docs.
        return ChatOpenAI(
            model=model,
            api_key=key,
            base_url="https://api.deepseek.com/v1",
            max_tokens=max_tokens,
            temperature=temperature,
            **_deepseek_extra_body(model),
        )

    if provider == "moonshot":
        key = api_key or settings.moonshot_api_key
        if not key:
            return None
        return _make_moonshot(model=model, api_key=key, base_url=settings.moonshot_base_url,
                              max_tokens=max_tokens, temperature=temperature)

    if provider == "mistral":
        key = api_key or settings.mistral_api_key
        if not key:
            return None
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=model, api_key=key, max_tokens=max_tokens, temperature=temperature)

    if provider == "openrouter":
        key = api_key or settings.openrouter_api_key
        if not key:
            return None
        return _make_openrouter(model=model, api_key=key, max_tokens=max_tokens, temperature=temperature)

    if provider == "openai":
        # Real OpenAI (api.openai.com). Per-instance api_key takes priority,
        # falls back to runtime/env. Optional `base_url` for Azure / proxy.
        key = api_key or settings.openai_api_key
        if not key:
            return None
        from langchain_openai import ChatOpenAI
        kw = {
            "model": model,
            "api_key": key,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        _base = _runtime.get("openai_base_url") or settings.openai_base_url or None
        if _base:
            kw["base_url"] = _base
        return ChatOpenAI(**kw)

    if provider == "openai_codex":
        # GPT-5.x via l'ABONNEMENT ChatGPT (forfait, 2026-06-12) — backend
        # Responses API de chatgpt.com/backend-api/codex. AUCUNE clé API :
        # connexion par import des tokens du CLI Codex officiel (Settings →
        # Admin → OpenAI Codex), Bearer injecté PAR REQUÊTE via httpx.Auth
        # avec refresh auto → l'instance reste cachable par tier sans
        # jamais servir un token périmé. Usage cible : GPT-5.5 primaire du
        # tier C, DeepSeek pro en fallback de chaîne (codex_rate_limited /
        # 429 classifiés recoverable par le FallbackManager).
        return _make_openai_codex(model=model, temperature=temperature)

    logger.warning("_make_llm_for_instance: unknown provider '%s' for instance '%s'", provider, instance_id)
    return None


def build_llm_for_provider(
    provider_id: str,
    tier: Optional[ComplexityTier] = None,
) -> Optional[BaseChatModel]:
    """Public wrapper around ``_make_llm_for_provider`` for the fallback manager.

    Used by the Hermes Chantier 4 fallback chain (services/fallback_manager.py)
    to materialise a specific provider mid-conversation when the primary
    plants. Applies the same per-tier hyperparameters as ``get_llm_for_tier``
    so the fallback runs with the right token budget and temperature.

    Returns None (does NOT raise) when the provider has no key configured —
    callers should detect this and ask the manager to advance to the next
    provider in the chain.

    Parameters
    ----------
    provider_id
        Provider name ("anthropic", "qwen_api", …) OR an LLMInstance UUID
        present in ``_instance_cache`` (named-instance routing).
    tier
        Tier to derive max_tokens / temperature from. Defaults to MEDIUM
        which is a safe agentic baseline.
    """
    settings = get_settings()
    _tier = tier or ComplexityTier.MEDIUM
    if _tier == ComplexityTier.IMAGE:
        temperature, max_tokens = 0.7, 4096
    elif _tier == ComplexityTier.SIMPLE:
        temperature, max_tokens = 0.1, 4096
    else:
        temperature, max_tokens = 0.1, 8192

    try:
        if _is_instance_id(provider_id):
            return _make_llm_for_instance(
                provider_id, max_tokens=max_tokens, temperature=temperature,
            )
        return _make_llm_for_provider(
            provider_id, settings,
            max_tokens=max_tokens, temperature=temperature,
        )
    except Exception as exc:
        logger.warning(
            "build_llm_for_provider(%r): instantiation failed (%s)",
            provider_id, exc,
        )
        return None


def get_llm_for_tier(tier: ComplexityTier) -> BaseChatModel:
    """Return the appropriate LLM for a given complexity tier.

    The provider chain for each tier is read from the in-memory tier config
    (loaded from DB on startup, editable via PUT /api/settings/llm/tiers).
    Falls back through the configured list; if fallback_enabled=False, only
    the first provider is tried.  If all fail, get_llm() is returned.

    Each entry in the providers list can be:
    - A known provider name ("ollama", "anthropic", …) — legacy behavior
    - A UUID of a LLMInstance present in _instance_cache — named-instance routing

    Defensive auto-load (Sprint 1, audit 2026-05-15)
    -------------------------------------------------
    If ``_instance_cache`` is empty AND ``_runtime`` looks unconfigured,
    we assume this function is being called outside the normal uvicorn
    lifespan (e.g. a `docker compose exec` script, a cron job, or an
    isolated test harness). In that case we trigger
    ``load_llm_settings_from_db()`` on the fly so the caller doesn't
    have to remember to do it. The cost is one DB read, cached forever
    after; in the normal serving path the cache is already warm and
    this branch is a no-op (the ``if`` short-circuits).
    """
    if not _instance_cache and not _runtime.get("provider"):
        # B-1 (revue 2026-06-10) — l'ancien code bloquait ici l'event loop
        # jusqu'à 10 s (`fut.result(timeout=10)` depuis du code sync exécuté
        # SUR la loop) : tous les WebSockets de tous les users gelaient,
        # précisément au cold start. Désormais : si une loop tourne, on
        # programme le chargement en tâche de fond (référence forte) et CE
        # tour utilise les défauts — le tour suivant a le cache chaud. Hors
        # loop (script `docker compose exec`, cron isolé), on charge en
        # synchrone comme avant.
        try:
            import asyncio
            try:
                asyncio.get_running_loop()
                _in_loop = True
            except RuntimeError:
                _in_loop = False

            if _in_loop:
                global _lazy_settings_task
                if _lazy_settings_task is None or _lazy_settings_task.done():
                    from app.services.background_tasks import spawn
                    _lazy_settings_task = spawn(
                        load_llm_settings_from_db(),
                        label="llm-settings-lazy-load",
                    )
                logger.warning(
                    "get_llm_for_tier: settings LLM pas encore chargés — "
                    "chargement lancé en fond, défauts utilisés pour ce tour"
                )
            else:
                asyncio.run(load_llm_settings_from_db())
                logger.info(
                    "get_llm_for_tier: lazily loaded LLM settings from DB "
                    "(cache had 0 instances, now %d)", len(_instance_cache),
                )
        except Exception as exc:
            logger.warning(
                "get_llm_for_tier: lazy load failed (will use defaults): %s",
                exc,
            )

    settings = get_settings()
    config = get_tier_config()
    tier_cfg = config.get(tier.value, DEFAULT_TIER_CONFIG.get(tier.value, {}))

    providers: list[str] = tier_cfg.get("providers", ["ollama"])
    fallback_enabled: bool = tier_cfg.get("fallback_enabled", True)

    # Per-tier hyperparameters — the previous hardcoded `temperature=0.7` for
    # ALL tiers caused massive non-determinism in tool selection and JSON
    # generation (April 2026 mission "Vide spam" fiasco : LLM hallucinated
    # email IDs because the sampler had too much variance).
    #   - SIMPLE / MEDIUM / COMPLEX : tool-calling + planning → low temp
    #     (Anthropic, OpenAI agentic guidelines all recommend 0.0–0.2).
    #   - MAINTENANCE              : structured summaries → low temp.
    #   - IMAGE                    : vision/creative → keep 0.7.
    # Token budget : MEDIUM / COMPLEX / MAINTENANCE need room for multi-step
    # plans and replans. SIMPLE stays small for cost.
    if tier == ComplexityTier.IMAGE:
        temperature = 0.7
        max_tokens = 4096
    elif tier == ComplexityTier.SIMPLE:
        temperature = 0.1
        max_tokens = 4096
    else:  # MEDIUM, COMPLEX, MAINTENANCE
        temperature = 0.1
        max_tokens = 8192

    last_exc: Optional[Exception] = None
    for i, provider_id in enumerate(providers):
        try:
            if _is_instance_id(provider_id):
                llm = _make_llm_for_instance(provider_id, max_tokens=max_tokens, temperature=temperature)
            else:
                llm = _make_llm_for_provider(provider_id, settings,
                                             max_tokens=max_tokens, temperature=temperature)
            if llm is not None:
                return llm
            # llm is None = no key for this provider/instance → skip silently
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


# ──────────────────────────────────────────────────────────────────────────────
# describe_llm — analytics helper
# ──────────────────────────────────────────────────────────────────────────────

def describe_llm(llm) -> tuple[str, str]:
    """Return ``(provider, model)`` strings for analytics/logging purposes.

    Many LangChain ChatModels share the same Python class (``ChatOpenAI``)
    while pointing at very different backends — Qwen API, LM Studio, OpenRouter,
    DeepSeek, Zhipu, even real OpenAI. The ``base_url`` of the underlying
    HTTP client is the only reliable disambiguator.

    Returns ("unknown", "?") if the LLM type cannot be identified, never
    raises — so it's safe to call in a hot logging path.
    """
    if llm is None:
        return "unknown", "?"
    cls = type(llm).__name__
    model = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or "?"
    )
    model = str(model)

    # Direct class-based providers
    if "Anthropic" in cls:
        return "anthropic", model
    if "Google" in cls or "Gemini" in cls or "VertexAI" in cls:
        return "google", model
    if "Ollama" in cls:
        return "ollama", model
    if "Mistral" in cls:
        return "mistral", model

    # ChatOpenAI is shared by ~6 providers — use base_url to tell them apart
    if "OpenAI" in cls:
        base_url = (
            getattr(llm, "openai_api_base", None)
            or getattr(llm, "base_url", None)
            or ""
        )
        # Some langchain clients hide base_url inside .client.base_url
        if not base_url:
            client = getattr(llm, "client", None)
            base_url = getattr(client, "base_url", "") or getattr(client, "_base_url", "")
        base_url = str(base_url).lower()
        if any(t in base_url for t in ("host.docker.internal", "127.0.0.1", "localhost", ":1234", "lm-studio", "lmstudio")):
            return "lm_studio", model
        if any(t in base_url for t in ("dashscope", "aliyuncs", "alibabacloud")):
            return "qwen_api", model
        if "openrouter" in base_url:
            return "openrouter", model
        if "deepseek" in base_url:
            return "deepseek", model
        if "moonshot" in base_url:
            return "moonshot", model
        if "zhipu" in base_url or "bigmodel" in base_url:
            return "zhipu", model
        if "openai.com" in base_url or not base_url:
            return "openai", model
        return "openai-compat", model

    return cls.lower().replace("chat", "").replace("model", "") or "unknown", model


# ──────────────────────────────────────────────────────────────────────────────
# Vision capability detection (for multimodal tool results, audit P1 2026-05-06)
# ──────────────────────────────────────────────────────────────────────────────

# Substrings that, if present in the model name (lowercased), indicate
# the model accepts image inputs in the chat completion API. Conservative
# allowlist — when in doubt we return False so the agent falls back to
# text-only tool results (always safe).
_VISION_MODEL_PATTERNS: tuple[str, ...] = (
    # Anthropic — all Claude 3+ models accept images
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    # Google
    "gemini-1.5", "gemini-2", "gemini-pro-vision", "gemini-flash",
    # OpenAI
    "gpt-4o", "gpt-4-vision", "gpt-4-turbo", "gpt-5",
    # Qwen vision — many naming variants
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen-3-vl", "qwen3-vl",
    "qwen-vl-max", "qwen-vl-plus",
    # Mistral
    "pixtral",
    # Moonshot Kimi vision
    "moonshot-v1-vision", "kimi-vl", "kimi-thinking-preview",
    # Meta vision (via OpenRouter)
    "llama-3.2-vision", "llama-3.2-90b-vision",
)

# Provider-level allowlists. If the provider always supports vision (rare),
# the lookup short-circuits without checking the model name.
_VISION_PROVIDER_ALLOWLIST: frozenset[str] = frozenset()


def supports_vision(llm) -> bool:
    """Best-effort check: does this LLM accept image_url content blocks?

    Used to decide whether tool results carrying base64 image data should
    be re-injected to the model as a multimodal HumanMessage at the next
    turn. Falls back to ``False`` on any uncertainty — text-only is safe.
    """
    if llm is None:
        return False
    try:
        provider, model = describe_llm(llm)
    except Exception:
        return False
    # Source of truth first (structured metadata: snapshot + models.dev).
    try:
        from app.services.model_metadata import vision_capability
        known = vision_capability(provider, model)
        if known is not None:
            return known
    except Exception:
        pass  # fall through to the heuristic
    # Heuristic fallback for models not covered by the metadata.
    if provider in _VISION_PROVIDER_ALLOWLIST:
        return True
    model_lc = (model or "").lower()
    return any(pat in model_lc for pat in _VISION_MODEL_PATTERNS)
