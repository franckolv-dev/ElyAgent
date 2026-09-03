# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/model_metadata.py
# @brief      Source de vérité des capacités modèles (vision/contexte/coût)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Métadonnées modèles — capacités (vision / tools), fenêtre de contexte, coût.

Remplace les heuristiques fragiles (allowlist + substring) de
``llm_provider.supports_vision`` par une source de vérité structurée.

Stratégie **offline-first** (comme models.dev de Hermes) :
  1. **Snapshot bundlé** (``_SNAPSHOT``) — fait foi pour les modèles qu'Ely
     utilise réellement (locaux compris : gemma, lfm2.5, devstral…). Toujours
     disponible, zéro réseau.
  2. **Overlay models.dev** (cache disque) — augmente le snapshot pour les
     modèles cloud arbitraires. Rafraîchi best-effort par
     ``refresh_from_models_dev`` ; absent/périmé = on retombe sur le snapshot.

Lookup : snapshot → overlay → ``None`` (l'appelant retombe alors sur son
heuristique). ``get_capabilities`` ne lève jamais.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "model_metadata"
_CACHE_FILE = _CACHE_DIR / "models_dev.json"
_REFRESH_TTL_S = 7 * 24 * 3600  # a week — model metadata changes slowly


@dataclass(frozen=True)
class ModelCapabilities:
    vision: bool | None = None
    tools: bool | None = None
    context_window: int | None = None
    input_per_m: float | None = None   # USD per 1M input tokens
    output_per_m: float | None = None  # USD per 1M output tokens
    source: str = "snapshot"


# ── Bundled snapshot ─────────────────────────────────────────────────────────
# Matched by normalized substring (robust to suffixes like @8bit, -mlx, dates).
# Order: most specific first. Capabilities curated for the families Ely routes.
_SNAPSHOT: tuple[tuple[str, ModelCapabilities], ...] = (
    # ── Anthropic Claude (all modern = vision + tools, 200k) ──
    ("claude", ModelCapabilities(vision=True, tools=True, context_window=200_000)),
    ("haiku", ModelCapabilities(vision=True, tools=True, context_window=200_000)),
    ("sonnet", ModelCapabilities(vision=True, tools=True, context_window=200_000)),
    ("opus", ModelCapabilities(vision=True, tools=True, context_window=200_000)),
    # ── Google Gemini (vision + tools, large context) ──
    ("gemini-2", ModelCapabilities(vision=True, tools=True, context_window=1_000_000)),
    ("gemini-1.5", ModelCapabilities(vision=True, tools=True, context_window=1_000_000)),
    ("gemini", ModelCapabilities(vision=True, tools=True, context_window=1_000_000)),
    # ── OpenAI / Codex (vision + tools) ──
    ("gpt-5", ModelCapabilities(vision=True, tools=True, context_window=256_000)),
    ("gpt-4o", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("gpt-4-turbo", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("gpt-4-vision", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    # ── Vision-specific variants (must precede their text families) ──
    ("pixtral", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("qwen-vl", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("qwen2.5-vl", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("qwen3-vl", ModelCapabilities(vision=True, tools=True, context_window=256_000)),
    ("kimi-vl", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("moonshot-v1-vision", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("llama-3.2-vision", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    # ── Gemma 3/4 — multimodal ──
    ("gemma-4", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    ("gemma-3", ModelCapabilities(vision=True, tools=True, context_window=128_000)),
    # ── Text-only families Ely uses (explicit vision=False) ──
    ("deepseek", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("devstral", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("lfm2", ModelCapabilities(vision=False, tools=True, context_window=32_000)),
    ("ministral", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("mistral-small", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("mistral-large", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("kimi-k2", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("qwen", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("gpt-oss", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
    ("glm", ModelCapabilities(vision=False, tools=True, context_window=128_000)),
)


def _normalize(model: str) -> str:
    """Lowercase, drop a provider prefix and quant/runtime suffixes."""
    m = (model or "").lower().strip()
    m = m.split("/")[-1]                 # "mistralai/devstral" → "devstral"
    m = re.split(r"[@:]", m)[0]          # "...@8bit" / "...:latest" → base
    return m.strip()


# ── models.dev disk-cache overlay (best-effort, augments the snapshot) ─────────
_overlay: dict[str, ModelCapabilities] = {}


def _load_overlay() -> None:
    global _overlay
    try:
        if _CACHE_FILE.exists():
            raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            models = raw.get("models", {}) if isinstance(raw, dict) else {}
            _overlay = {
                k: ModelCapabilities(
                    vision=v.get("vision"),
                    tools=v.get("tools"),
                    context_window=v.get("context_window"),
                    input_per_m=v.get("input_per_m"),
                    output_per_m=v.get("output_per_m"),
                    source="models.dev",
                )
                for k, v in models.items()
                if isinstance(v, dict)
            }
    except Exception as exc:
        logger.debug("model_metadata: overlay load failed (%s)", exc)
        _overlay = {}


_load_overlay()


def _snapshot_match(model_norm: str) -> ModelCapabilities | None:
    for pattern, caps in _SNAPSHOT:
        if pattern in model_norm:
            return caps
    return None


def get_capabilities(provider: str, model: str) -> ModelCapabilities | None:
    """Return capabilities for (provider, model), or None if truly unknown.
    Snapshot wins (curated for Ely); models.dev overlay augments unknowns."""
    norm = _normalize(model)
    if not norm:
        return None
    caps = _snapshot_match(norm)
    if caps is not None:
        return caps
    # Overlay: exact normalized key, then substring.
    if norm in _overlay:
        return _overlay[norm]
    for key, ov in _overlay.items():
        if key and (key in norm or norm in key):
            return ov
    return None


def vision_capability(provider: str, model: str) -> bool | None:
    caps = get_capabilities(provider, model)
    return None if caps is None else caps.vision


def context_window(provider: str, model: str) -> int | None:
    caps = get_capabilities(provider, model)
    return None if caps is None else caps.context_window


def _cache_age_s() -> float:
    try:
        return time.time() - _CACHE_FILE.stat().st_mtime
    except Exception:
        return float("inf")


async def refresh_from_models_dev(*, force: bool = False) -> int:
    """Best-effort fetch of models.dev → disk cache + reload overlay.

    No-op if the cache is fresh (< TTL) unless ``force``. Never raises;
    returns the number of models cached (0 on failure)."""
    if not force and _cache_age_s() < _REFRESH_TTL_S:
        return len(_overlay)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(MODELS_DEV_URL)
        if resp.status_code != 200:
            logger.info("model_metadata: models.dev HTTP %s — keeping snapshot", resp.status_code)
            return len(_overlay)
        data = resp.json()
    except Exception as exc:
        logger.info("model_metadata: models.dev fetch failed (%s) — keeping snapshot", exc)
        return len(_overlay)

    models = _parse_models_dev(data)
    if not models:
        return len(_overlay)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"models": models}, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("model_metadata: cache write failed (%s)", exc)
    _load_overlay()
    logger.info("model_metadata: refreshed %d models from models.dev", len(models))
    return len(models)


def _parse_models_dev(data: dict) -> dict[str, dict]:
    """Flatten models.dev's {provider: {models: {id: {...}}}} into our shape.
    Defensive: skips anything malformed."""
    out: dict[str, dict] = {}
    if not isinstance(data, dict):
        return out
    for _prov, pdata in data.items():
        if not isinstance(pdata, dict):
            continue
        models = pdata.get("models")
        if not isinstance(models, dict):
            continue
        for mid, m in models.items():
            if not isinstance(m, dict):
                continue
            try:
                modal_in = (m.get("modalities") or {}).get("input") or []
                limit = m.get("limit") or {}
                cost = m.get("cost") or {}
                out[_normalize(mid)] = {
                    "vision": ("image" in modal_in) if modal_in else None,
                    "tools": m.get("tool_call"),
                    "context_window": limit.get("context"),
                    "input_per_m": cost.get("input"),
                    "output_per_m": cost.get("output"),
                }
            except Exception:
                continue
    return out
