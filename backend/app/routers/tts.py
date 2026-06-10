# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/tts.py
# @brief      Text-to-Speech endpoint using edge-tts (Microsoft Edge voices, free)
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

from app.config import get_settings

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["tts"])

# Wired to settings.tts_voice (env TTS_VOICE) — the setting existed but was
# never read until 2026-06-10; the voice was silently pinned to DeniseNeural.
DEFAULT_VOICE = get_settings().tts_voice
DEFAULT_RATE = "+20%"   # slightly faster than natural pace — more pleasant for a personal assistant


class TTSRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    rate: str = DEFAULT_RATE   # edge-tts format: "+20%" = 20% faster, "-10%" = 10% slower


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax + technical noise so TTS reads natural
    spoken French.

    Filters out content that's painful to listen to spelled out
    character-by-character (the « slash, deux-points, slash, slash »
    treatment): URLs, raw JSON blocks, file paths, long IDs, markdown
    tables, XML-like tags, etc. Leaves the actual spoken sentences intact.

    User-driven additions (mai 2026, after Franck reported Éli reading
    aloud `<parameter=category>\\nspam\\n</parameter>` token by token).
    """
    # ── 1. Block-level structures (must come first — they may contain
    #       URL/JSON noise we don't want to scrub one rule at a time) ──
    # Code blocks (``` ... ```) — typically full of syntax noise
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Markdown tables — pipe-separated rows with a `---` separator line
    # are unintelligible spoken aloud. Match any block of 2+ lines
    # starting with `|` and drop them entirely.
    text = re.sub(
        r"(?:^\|[^\n]*\|[ \t]*\n){2,}",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Bare JSON blocks (3+ lines) like `{\n  "key": "value",\n  ...\n}`
    # — almost always tool call dumps the model accidentally pasted.
    text = re.sub(
        r"\{\s*\n(?:[^\n]*\n){2,}[^\n]*\}",
        "",
        text,
    )
    # XML / HTML / function-call tags `<tag>`, `</tag>`, `<tag attr=...>`
    text = re.sub(r"</?[a-zA-Z][^>\n]*>", "", text)

    # ── 2. URLs and file paths — keep the surrounding sentence,
    #       strip the unspeakable token. ──
    # Absolute URLs (http://, https://, ftp://, ws://, mailto:)
    text = re.sub(
        r"\b(?:https?|ftp|ws|wss|mailto):[^\s)\]\}]+",
        "[lien]",
        text,
    )
    # www.* fallback (no scheme)
    text = re.sub(r"\bwww\.[^\s)\]\}]+", "[lien]", text)
    # POSIX file paths (/foo/bar/baz)
    text = re.sub(r"(?:^|\s)(/[^\s/]+){2,}/?", " [chemin] ", text)
    # Long alphanumeric IDs (Drive file IDs, OAuth tokens, hex hashes…)
    # 20+ chars without spaces, mixing letters and digits → unreadable.
    text = re.sub(
        r"\b(?=\w*[A-Za-z])(?=\w*\d)[A-Za-z0-9_-]{20,}\b",
        "[identifiant]",
        text,
    )

    # ── 3. Inline markdown ──
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

    # ── 4. Whitespace cleanup ──
    # Collapse multiple blank lines into one
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of placeholder tokens we may have inserted next to each
    # other (e.g. « [lien] [lien] [lien] » → « [lien] »)
    text = re.sub(r"(\[(?:lien|chemin|identifiant)\])(?:\s+\1)+", r"\1", text)
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
