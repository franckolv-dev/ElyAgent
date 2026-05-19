# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/tts.py
# @brief      Text-to-Speech endpoint using edge-tts (Microsoft Edge voices, free)
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
"""Text-to-Speech endpoint using edge-tts (Microsoft Edge voices, free).

POST /tts/speak  {"text": "Bonjour", "voice": "fr-FR-DeniseNeural"}
→ returns audio/mpeg stream
"""
import io
import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["tts"])

DEFAULT_VOICE = "fr-FR-DeniseNeural"
DEFAULT_RATE = "+20%"   # slightly faster than natural pace — more pleasant for a personal assistant


class TTSRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    rate: str = DEFAULT_RATE   # edge-tts format: "+20%" = 20% faster, "-10%" = 10% slower


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax so TTS reads natural spoken French."""
    # Code blocks (``` ... ```)
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Inline code (`code`)
    text = re.sub(r"`[^`]+`", "", text)
    # Headers (## Title → Title)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Bold/italic (***x***, **x**, *x*, __x__, _x_)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Links [label](url) → label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Images ![alt](url) → ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    # Bullet list markers (- item / * item / • item)
    text = re.sub(r"^[\-\*\•]\s+", "", text, flags=re.MULTILINE)
    # Numbered list markers (1. item → item)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # Blockquotes (> text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines into one
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _require_edge_tts() -> None:
    if not _EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="TTS service unavailable")


@router.post("/speak")
async def speak(req: TTSRequest):
    _require_edge_tts()
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    try:
        clean_text = _strip_markdown(req.text)
        if not clean_text:
            raise HTTPException(status_code=400, detail="Empty text after markdown cleanup")
        communicate = edge_tts.Communicate(clean_text, req.voice, rate=req.rate)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/mpeg")
    except Exception as exc:
        logger.error("TTS synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail="TTS synthesis failed")


@router.get("/voices")
async def list_voices():
    """Return available French voices."""
    _require_edge_tts()
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith("fr-")]
