# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/vision_injection.py
# @brief      Inject screenshots into agent context for vision-capable LLMs
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Vision injection — let vision-capable LLMs SEE the screenshot they just took.

Inspired by OpenClaw's multimodal tool-result pattern (audit P1 2026-05-06).

Problem
-------
``browser_screenshot`` returns a JSON string containing ``data`` (base64
PNG). For non-vision models, the model only sees the JSON metadata
(local_path, prompt) — fine. But for vision-capable models (Pixtral,
Kimi-VL, Qwen-VL, Claude 3+, GPT-4o, Gemini), we waste their main
strength: they could ANALYSE the screenshot if it were available as an
image content block.

Solution
--------
After the ToolNode runs, **before** the next agent_node turn, scan the
recent ToolMessages. If one carries base64 image data AND the active
model supports vision, append a synthetic HumanMessage with the image
as ``image_url`` content. The model now sees the picture and can decide
the next step with full visual context.

This is non-invasive: the original ToolMessage is preserved (so non-vision
models still get text-only), and the synthetic HumanMessage is dropped
from any further turn (we only inject for the immediate next inference).

Token cost
----------
A 1280×800 PNG is ~50–150 kB base64 → ~30–80k tokens for a vision model.
Significant. We therefore inject AT MOST the last screenshot (not the
whole history) and only when the model is vision-capable.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# OPT-IN by default. Re-injecting screenshots into the model context is
# powerful for vision-capable models with large windows, but it OVERFLOWS
# typical 8K local context (Qwen3-VL-8B in LM Studio crashes with
# « TruncateMiddle context overflow policy is not currently supported for
# prompts with images »). Hermes and OpenClaw don't do this either —
# they rely on tool-result text + MEDIA: sentinels for delivery, and let
# the model decide chaining without seeing the pixels.
#
# Enable via env var ELY_VISION_INJECTION=1 once you have a model with
# ≥32K context configured (Pixtral 12B Mistral, Qwen-VL-Max, GPT-4o,
# Claude 3.5 Sonnet).
_ENABLED: bool = os.getenv("ELY_VISION_INJECTION", "0").strip() in ("1", "true", "yes", "on")


# Max width/height for the re-injected image (px). Larger inputs are
# resized down — Qwen3-VL-8B's default context (8K) overflows on 1280×720
# PNGs, and LM Studio refuses to truncate prompts containing images.
# 800-max JPEG q70 fits comfortably under 50 kB base64 for typical
# screenshots (< 8K tokens).
_MAX_INJECTION_DIM: int = 800
_JPEG_QUALITY: int = 70

# Hard ceiling on the re-injected image size. If the downsized output is
# still above this threshold, we SKIP injection — better to lose vision
# than to overflow the model context and get a hard error from LM Studio.
_MAX_INJECTION_BYTES_B64: int = 80 * 1024  # 80 kB base64 ≈ ~28k tokens


def _downsize_for_injection(mime: str, b64: str) -> tuple[str, str]:
    """Resize and re-encode the image so the multimodal prompt stays under
    typical local-model context windows. Returns ``(new_mime, new_b64)``.

    Falls back to the original (mime, b64) on any failure — better to risk
    a context overflow than to skip the image entirely.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.debug("vision_injection: PIL not available — skipping downsize")
        return mime, b64

    try:
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw))
        # Convert to RGB (JPEG can't handle RGBA / palette modes)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Resize keeping aspect ratio
        if max(img.size) > _MAX_INJECTION_DIM:
            img.thumbnail(
                (_MAX_INJECTION_DIM, _MAX_INJECTION_DIM),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        logger.info(
            "vision_injection: downsized image %d kB → %d kB (size=%s)",
            len(b64) // 1024, len(new_b64) // 1024, img.size,
        )
        return "image/jpeg", new_b64
    except Exception as exc:
        logger.warning("vision_injection: downsize failed (%s) — using original", exc)
        return mime, b64


def _extract_image_from_tool_msg(content: Any) -> tuple[str, str] | None:
    """Return ``(mime, base64)`` if the ToolMessage content embeds an image,
    else None. Handles both string-JSON and list-of-blocks shapes."""
    # String-JSON shape (current browser_screenshot return)
    if isinstance(content, str):
        s = content.strip()
        if not s.startswith("{"):
            return None
        try:
            parsed = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        if parsed.get("type") != "image":
            return None
        b64 = parsed.get("data")
        mime = parsed.get("mime") or "image/png"
        if not b64 or not isinstance(b64, str):
            return None
        return mime, b64
    # List-of-blocks shape (future-proof — already used by some providers)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image":
                b64 = block.get("data") or (block.get("image_url") or {}).get("url", "")
                # data:image/png;base64,xxx → strip prefix if present
                if isinstance(b64, str) and b64.startswith("data:"):
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                if b64:
                    return block.get("mime") or "image/png", b64
    return None


def maybe_inject_screenshot(messages: list, llm) -> list:
    """If the most recent ToolMessage carries an image AND the LLM supports
    vision, return a NEW message list with a synthetic HumanMessage added
    so the model can see the screenshot at the next turn.

    Idempotent : if no recent screenshot OR model doesn't support vision,
    returns the list unchanged. Caller must use the returned list for the
    immediate ``ainvoke`` call only — don't persist it to graph state.
    """
    if not _ENABLED:
        # Disabled by default — see module docstring. Hermes/OpenClaw
        # don't re-inject screenshots and they work fine.
        return messages
    try:
        from app.services.llm_provider import supports_vision
        if not supports_vision(llm):
            return messages
    except Exception as exc:
        logger.debug("vision_injection: capability check failed (%s)", exc)
        return messages

    # Walk backwards through messages to find the most recent tool result
    # carrying an image. Stop at the first non-tool message — we only
    # inject the latest screenshot, not all of them, to control token cost.
    extracted: tuple[str, str] | None = None
    for msg in reversed(messages):
        # Tolerate both LangChain message objects and dicts
        msg_type = getattr(msg, "type", None) or (
            msg.get("role") if isinstance(msg, dict) else None
        )
        content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
        if msg_type == "tool":
            extracted = _extract_image_from_tool_msg(content)
            if extracted:
                break
            # Continue scanning earlier tool messages? No — only latest counts.
            continue
        # Non-tool message: stop scanning (we only handle the trailing tool burst)
        break

    if not extracted:
        return messages

    mime, b64 = extracted
    # Downsize for context-window-friendly injection. Qwen3-VL-8B on 8K
    # overflows on full-resolution screenshots; LM Studio refuses to
    # TruncateMiddle when the prompt contains images.
    mime, b64 = _downsize_for_injection(mime, b64)
    # Hard cap : if still too large after resize, skip injection to avoid
    # context overflow errors from the local LLM.
    if len(b64) > _MAX_INJECTION_BYTES_B64:
        logger.warning(
            "vision_injection: downsized image still %d kB > %d kB cap — "
            "SKIPPING injection (model would overflow context)",
            len(b64) // 1024, _MAX_INJECTION_BYTES_B64 // 1024,
        )
        return messages
    # Build a HumanMessage with multimodal content
    from langchain_core.messages import HumanMessage
    synthetic = HumanMessage(
        content=[
            {
                "type": "text",
                "text": (
                    "[contexte visuel injecté automatiquement] Voici la "
                    "capture d'écran que tu viens de prendre. Tu peux "
                    "l'analyser pour décider de la suite (la transmettre, "
                    "la sauvegarder, l'annoter…)."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ]
    )
    logger.info(
        "vision_injection: injected screenshot (%s, %d kB base64) for vision model",
        mime, len(b64) // 1024,
    )
    return list(messages) + [synthetic]
