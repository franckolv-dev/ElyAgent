"""Text-to-Speech endpoint using edge-tts (Microsoft Edge voices, free).

POST /tts/speak  {"text": "Bonjour", "voice": "fr-FR-DeniseNeural"}
→ returns audio/mpeg stream
"""
import io
import logging

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


class TTSRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE


def _require_edge_tts() -> None:
    if not _EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="TTS service unavailable")


@router.post("/speak")
async def speak(req: TTSRequest):
    _require_edge_tts()
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    try:
        communicate = edge_tts.Communicate(req.text, req.voice)
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
