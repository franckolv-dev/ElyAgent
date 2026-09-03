# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/translate_skill.py
# @brief      Translation skill — free text translation via MyMemory API
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Translation skill — free text translation via MyMemory API.

No API key required for the free tier (5 000 chars/day per IP).
Supports 50+ language pairs.  Common language codes:
  fr  français      en  anglais       es  espagnol
  de  allemand      it  italien       pt  portugais
  nl  néerlandais   ru  russe         zh  chinois
  ar  arabe         ja  japonais      ko  coréen
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)

# Friendly name → ISO 639-1 code map for the most common languages
_LANG_ALIASES: dict[str, str] = {
    "français": "fr", "french": "fr",
    "anglais": "en", "english": "en",
    "espagnol": "es", "spanish": "es",
    "allemand": "de", "german": "de",
    "italien": "it", "italian": "it",
    "portugais": "pt", "portuguese": "pt",
    "néerlandais": "nl", "dutch": "nl",
    "russe": "ru", "russian": "ru",
    "chinois": "zh", "chinese": "zh",
    "arabe": "ar", "arabic": "ar",
    "japonais": "ja", "japanese": "ja",
    "coréen": "ko", "korean": "ko",
}


def _normalize_lang(code: str) -> str:
    """Accept full language names (e.g. 'anglais') or ISO codes ('en')."""
    return _LANG_ALIASES.get(code.strip().lower(), code.strip().lower())


@tool
async def translate_text(
    text: str,
    target_language: str,
    source_language: str = "auto",
) -> str:
    """Translate text into another language.

    Args:
        text: The text to translate (up to 500 characters per call)
        target_language: Target language — ISO code ('en', 'es', 'de', 'it')
                         or full name in French/English ('anglais', 'english', etc.)
        source_language: Source language code or 'auto' for automatic detection
    """
    import httpx

    src = _normalize_lang(source_language)
    tgt = _normalize_lang(target_language)
    text = text[:500]  # free-tier safety cap

    if src == "auto":
        langpair = f"autodetect|{tgt}"
    else:
        langpair = f"{src}|{tgt}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": langpair},
                headers={"User-Agent": "ELY-Agent/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

        translated = data["responseData"]["translatedText"]
        match = data.get("responseDetails", "")

        # Detect quota exceeded
        if "LIMIT" in translated.upper() or "LIMIT" in str(match).upper():
            return "Quota de traduction gratuit atteint (5 000 car./jour). Réessaie demain."

        src_label = src if src != "autodetect" else "auto"
        return f"Traduction ({src_label} → {tgt}) :\n{translated}"

    except Exception as exc:
        logger.warning("translate_text failed: %s", exc)
        return f"Erreur de traduction : {exc}"


get_skill_registry().register(Skill(
    name="translate",
    display_name="Traduction",
    description="Traduire du texte dans plus de 50 langues via MyMemory (sans clé API, 5 000 car/jour gratuits)",
    icon="🌐",
    scopes=["internet"],
    domains=[Domain.RESEARCH],
    tools=[translate_text],
))
