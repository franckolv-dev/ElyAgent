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
"""Speech-to-text endpoint using faster-whisper (local, CPU)."""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.auth.dependencies import get_current_user

router = APIRouter()

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # tiny model: ~75MB, fast on CPU, good enough for short voice commands
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


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
        model = _get_model()
        segments, info = model.transcribe(tmp_path, language="fr", beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"text": text, "language": info.detected_language}
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {exc}")
    finally:
        os.unlink(tmp_path)
