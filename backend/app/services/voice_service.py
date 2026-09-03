# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/voice_service.py
# @brief      Voice conversation service — manages voice mode settings and optimization.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Voice conversation service — manages voice mode settings and optimization."""
from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice conversation constants
# ---------------------------------------------------------------------------

SILENCE_THRESHOLD_MS: int = 1500
"""Milliseconds of silence before the client should auto-send the recording."""

MAX_RECORDING_DURATION_S: int = 30
"""Maximum duration (seconds) for a single voice utterance."""

VOICE_PROMPT_HINT: str = (
    "L'utilisateur parle en mode vocal. Réponds de manière concise et naturelle, "
    "comme dans une conversation orale. Évite les listes à puces, les blocs de "
    "code et le formatage markdown. Limite tes réponses à 2-3 phrases maximum "
    "sauf si on te demande explicitement plus de détail."
)

# Wired to settings.tts_voice/tts_rate (env TTS_VOICE / TTS_RATE) — single
# source of truth shared with routers/tts.py since 2026-06-10 (voice and
# rate were pinned in separate hardcoded constants before that).
DEFAULT_VOICE: str = get_settings().tts_voice
DEFAULT_RATE: str = get_settings().tts_rate


# ---------------------------------------------------------------------------
# Voice config payload — sent to client on connection
# ---------------------------------------------------------------------------

def get_voice_config() -> dict:
    """Return the voice mode configuration for the client."""
    return {
        "silence_threshold_ms": SILENCE_THRESHOLD_MS,
        "max_recording_duration_s": MAX_RECORDING_DURATION_S,
        "voice": DEFAULT_VOICE,
    }


# ---------------------------------------------------------------------------
# Voice-optimized system prompt helper
# ---------------------------------------------------------------------------

def voice_system_hint() -> str:
    """Return the voice-mode system prompt hint to inject into the agent."""
    return VOICE_PROMPT_HINT
