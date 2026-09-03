# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_transcribe_event_loop.py
# @brief      Fix A-4 (revue 2026-06-10) — faster-whisper hors de l'event loop.
# @license    MIT
# =============================================================================
"""Pins:

  1. Une transcription lente ne gèle PAS l'event loop : une tâche
     concurrente continue de ticker pendant le decode.
  2. Le générateur lazy de faster-whisper est matérialisé DANS le worker
     thread (sinon le decode se rejoue sur la loop à l'itération).
  3. Les transcriptions concurrentes sont bornées à 2 par le sémaphore
     partagé entre POST /api/transcribe et WS /ws/voice.
  4. L'endpoint REST renvoie {"text", "language"} — ``info.language`` est
     le champ réel de TranscriptionInfo (``detected_language`` n'existe
     pas et faisait toujours tomber l'endpoint en 500).
"""
from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
import types

import pytest

from app.routers import transcribe as transcribe_mod
from app.routers import voice as voice_mod


class _FakeInfo:
    language = "fr"


def _make_slow_model(delay: float, seen_threads: list, gauge=None):
    """Fake WhisperModel whose decode cost lives in the LAZY generator,
    like the real faster-whisper."""

    class _SlowModel:
        def transcribe(self, path, **kwargs):
            def _segments():
                seen_threads.append(threading.current_thread())
                if gauge is not None:
                    gauge.enter()
                try:
                    time.sleep(delay)
                finally:
                    if gauge is not None:
                        gauge.leave()
                yield types.SimpleNamespace(text=" bonjour ")

            return _segments(), _FakeInfo()

    return _SlowModel()


@pytest.mark.asyncio
async def test_event_loop_responsive_during_transcription(monkeypatch):
    seen_threads: list = []
    monkeypatch.setattr(
        transcribe_mod, "_get_model", lambda: _make_slow_model(0.5, seen_threads)
    )

    ticks = 0

    async def _heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    hb = asyncio.create_task(_heartbeat())
    try:
        audio_b64 = base64.b64encode(b"fake-webm-bytes").decode()
        text = await voice_mod._transcribe_audio(audio_b64, "webm")
    finally:
        hb.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hb

    assert text == "bonjour"
    # Un decode bloquant de 0.5 s sur la loop laisserait ~0 tick ; en thread
    # on en attend ~25. Marge large pour CI chargée.
    assert ticks >= 5, f"event loop gelée pendant la transcription ({ticks} ticks)"
    # Le générateur lazy a bien été consommé hors du thread de la loop.
    assert seen_threads, "le générateur de segments n'a jamais été itéré"
    assert all(t is not threading.main_thread() for t in seen_threads), (
        "segments matérialisés sur l'event loop — le decode lazy doit rester "
        "dans asyncio.to_thread"
    )


@pytest.mark.asyncio
async def test_concurrent_transcriptions_bounded_by_semaphore(monkeypatch):
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    class _Gauge:
        def enter(self):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])

        def leave(self):
            with lock:
                state["current"] -= 1

    monkeypatch.setattr(
        transcribe_mod, "_get_model", lambda: _make_slow_model(0.2, [], _Gauge())
    )

    audio_b64 = base64.b64encode(b"fake-webm-bytes").decode()
    results = await asyncio.gather(
        *[voice_mod._transcribe_audio(audio_b64, "webm") for _ in range(4)]
    )

    assert results == ["bonjour"] * 4
    assert state["peak"] <= 2, f"{state['peak']} transcriptions simultanées (max 2)"


@pytest.mark.asyncio
async def test_transcribe_endpoint_returns_text_and_language(monkeypatch):
    from fastapi import UploadFile

    monkeypatch.setattr(
        transcribe_mod, "_get_model", lambda: _make_slow_model(0.0, [])
    )

    upload = UploadFile(file=io.BytesIO(b"fake-webm-bytes"), filename="note.webm")
    payload = await transcribe_mod.transcribe_audio(
        file=upload, current_user=types.SimpleNamespace(id="u1")
    )

    assert payload == {"text": "bonjour", "language": "fr"}
