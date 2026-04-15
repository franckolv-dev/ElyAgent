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
"""Voice conversation service — manages voice mode settings and optimization."""
from __future__ import annotations

import logging

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

DEFAULT_VOICE: str = "fr-FR-DeniseNeural"
DEFAULT_RATE: str = "+20%"


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
