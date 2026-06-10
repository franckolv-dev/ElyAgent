# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/transcribe.py
# @brief      Speech-to-text endpoint using faster-whisper (local, CPU).
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Speech-to-text endpoint using faster-whisper (local, CPU)."""
import asyncio

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.auth.dependencies import get_current_user

router = APIRouter()

_model = None

# Whisper int8 on CPU saturates a core per decode: bound concurrent
# transcriptions (semaphore shared by REST /api/transcribe and WS /ws/voice).
TRANSCRIBE_SEMAPHORE = asyncio.Semaphore(2)


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # tiny model: ~75MB, fast on CPU, good enough for short voice commands
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


def _transcribe_sync(tmp_path: str):
    """Blocking transcription — call via asyncio.to_thread.

    The segments generator is lazy (decoding happens while iterating), so it
    must be consumed here, inside the worker thread — not on the event loop.
    """
    model = _get_model()
    segments, info = model.transcribe(tmp_path, language="fr", beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, info


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Transcribe uploaded audio to text. Accepts webm/ogg/wav/mp3."""
    import tempfile
    import os

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(400, "Audio file too large (max 10 MB)")

    suffix = ".webm"
    if file.filename:
        suffix = os.path.splitext(file.filename)[1] or ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        async with TRANSCRIBE_SEMAPHORE:
            text, info = await asyncio.to_thread(_transcribe_sync, tmp_path)
        return {"text": text, "language": info.language}
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {exc}")
    finally:
        os.unlink(tmp_path)
