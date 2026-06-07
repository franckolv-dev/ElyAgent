# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/sovereignty.py
# @brief      PII sovereignty routing — force tier B/C to the EU Mistral chain
#             when the calling user opted into "strict sovereignty".
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""PII sovereignty routing.

Decoupled module so we don't add complexity to ``llm_provider.py``. Three
moving parts:

  1. A ContextVar ``SOVEREIGNTY_STRICT`` (per asyncio task) that callers at
     the top of a turn set from ``User.sovereignty_strict``.
  2. ``sovereign_chain_for_tier(tier)`` builds an EU provider chain (Mistral
     Large → Medium → Small as IDs from ``_instance_cache``) for the tiers
     that actually call cloud LLMs (MEDIUM, COMPLEX). Other tiers are
     unchanged (SIMPLE/MAINTENANCE are already local; IMAGE is unrelated to
     PII risk).
  3. ``llm_provider.get_tier_config()`` consults the ContextVar and, when
     True, returns the overridden chain instead of the default config.

Best-effort by design: if **no** Mistral instance is configured, we fall
back to the default chain and log a warning (better than crashing or
silently dropping the request).
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Final

logger = logging.getLogger(__name__)

# Per-asyncio-task flag. The top-of-turn caller (chat.py / voice.py /
# telegram_bot.py) sets it from User.sovereignty_strict; downstream
# get_tier_config() reads it.
SOVEREIGNTY_STRICT: ContextVar[bool] = ContextVar("sovereignty_strict", default=False)


# Tiers that route to cloud LLMs and must therefore be overridden when
# sovereignty is strict. SIMPLE + MAINTENANCE are already local-only;
# IMAGE is a separate path (no PII concern for image generation prompts in
# our usage).
_SOVEREIGN_OVERRIDE_TIERS: Final[frozenset[str]] = frozenset({"medium", "complex"})

# Mistral models, in priority order: largest first, smallest last. Matched
# against the `model` field of LLMInstance rows.
_MISTRAL_MODELS_PRIORITY: Final[tuple[str, ...]] = (
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
)


def get_sovereign_provider_ids() -> list[str]:
    """Return the configured Mistral instance IDs, largest first.

    Reads from ``llm_provider._instance_cache`` so it sees exactly what the
    Settings UI saved. Returns ``[]`` if no Mistral instance is configured
    (caller decides whether to fall back gracefully or warn).
    """
    try:
        from app.services.llm_provider import _instance_cache  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.debug("sovereignty: instance_cache unreachable (%s)", exc)
        return []

    # _instance_cache is dict[str (id), dict (config)]. We index by model.
    by_model: dict[str, str] = {}
    for inst_id, cfg in _instance_cache.items():
        if (cfg.get("provider") or "").lower() != "mistral":
            continue
        model = (cfg.get("model") or "").strip()
        if model and model not in by_model:
            by_model[model] = inst_id

    ordered = [by_model[m] for m in _MISTRAL_MODELS_PRIORITY if m in by_model]
    if not ordered:
        logger.warning(
            "sovereignty: no Mistral instance configured — strict mode will "
            "fall back to the default chain for cloud tiers. Configure a "
            "Mistral instance in Settings → LLM to honour the sovereignty toggle."
        )
    return ordered


def sovereign_chain_for_tier(tier_name: str) -> list[str] | None:
    """Return the EU provider chain for ``tier_name`` when sovereignty applies,
    or ``None`` when the tier should keep its default routing.

    Tiers in ``_SOVEREIGN_OVERRIDE_TIERS`` get the Mistral chain; others are
    returned untouched (caller uses the default config).
    """
    if tier_name not in _SOVEREIGN_OVERRIDE_TIERS:
        return None
    chain = get_sovereign_provider_ids()
    if not chain:
        return None  # fall back gracefully — already warned
    return chain
