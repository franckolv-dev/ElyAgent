# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/youtube_tool.py
# @brief      YouTube tools — search videos and retrieve transcripts/captions
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""YouTube tools — search videos and retrieve transcripts/captions.

Uses:
- YouTube Data API v3 for search (requires YOUTUBE_API_KEY env var)
  Falls back to web scraping via Invidious public instances if no key.
- youtube-transcript-api for captions (no API key required).
"""
from __future__ import annotations

import logging
import re

import httpx
from langchain_core.tools import tool

from app.config import get_settings

logger = logging.getLogger(__name__)

_INVIDIOUS_INSTANCES = [
    "https://invidious.io.lol",
    "https://inv.tux.pizza",
    "https://yt.cdaut.de",
]


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@tool
async def youtube_search(
    query: str,
    max_results: int = 5,
) -> str:
    """Search YouTube videos and return titles, channels, durations and URLs.

    Args:
        query: Search query (e.g. 'tutoriel Python asyncio', 'recette ratatouille')
        max_results: Number of results to return (1-10, default 5)
    """
    max_results = max(1, min(int(max_results), 10))
    settings = get_settings()
    api_key = getattr(settings, "youtube_api_key", None) or ""

    # ── Official API path ────────────────────────────────────────────────────
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={
                        "part": "snippet",
                        "q": query,
                        "maxResults": max_results,
                        "type": "video",
                        "key": api_key,
                        "relevanceLanguage": "fr",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            items = data.get("items", [])
            if not items:
                return f"Aucun résultat YouTube pour « {query} »."

            lines = [f"Résultats YouTube pour « {query} » :"]
            for item in items:
                vid_id = item["id"]["videoId"]
                sn = item["snippet"]
                lines.append(
                    f"\n• {sn['title']}\n"
                    f"  Chaîne : {sn['channelTitle']}\n"
                    f"  URL    : {_video_url(vid_id)}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("YouTube API search failed: %s — falling back to Invidious", exc)

    # ── yt-dlp fallback ──────────────────────────────────────────────────────
    import urllib.parse
    try:
        import yt_dlp  # type: ignore

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": max_results,
        }
        search_url = f"ytsearch{max_results}:{query}"
        loop = __import__("asyncio").get_event_loop()

        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(search_url, download=False)

        info = await loop.run_in_executor(None, _search)
        entries = (info or {}).get("entries", [])
        if entries:
            lines = [f"Résultats YouTube pour « {query} » :"]
            for entry in entries[:max_results]:
                vid_id = entry.get("id", "")
                title = entry.get("title", "")
                author = entry.get("uploader") or entry.get("channel", "")
                dur_sec = entry.get("duration") or 0
                dur = f"{int(dur_sec) // 60}:{int(dur_sec) % 60:02d}" if dur_sec else "?"
                lines.append(
                    f"\n• {title}\n"
                    f"  Chaîne : {author}  |  Durée : {dur}\n"
                    f"  URL    : {_video_url(vid_id)}"
                )
            return "\n".join(lines)
    except Exception as exc:
        logger.warning("yt-dlp search failed: %s", exc)

    import urllib.parse
    return f"Impossible de chercher sur YouTube pour l'instant. Essaie directement sur https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"


@tool
async def youtube_transcript(
    video_url_or_id: str,
    language: str = "fr",
) -> str:
    """Retrieve the transcript / captions of a YouTube video.

    Works with any video that has auto-generated or manual captions.

    Args:
        video_url_or_id: YouTube URL (e.g. 'https://youtu.be/abc123') or video ID (e.g. 'abc123')
        language: Preferred language code (default 'fr'; falls back to 'en' if unavailable)
    """
    # Extract video ID
    vid_id = video_url_or_id.strip()
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pat in patterns:
        m = re.search(pat, vid_id)
        if m:
            vid_id = m.group(1)
            break

    if len(vid_id) != 11 or not re.match(r"^[A-Za-z0-9_-]{11}$", vid_id):
        return f"ID de vidéo YouTube invalide : « {video_url_or_id} »."

    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled  # type: ignore

        ytt_api = YouTubeTranscriptApi()

        # Build preferred language list
        langs = list(dict.fromkeys([language, "en", "fr"]))
        try:
            fetched = ytt_api.fetch(vid_id, languages=langs)
            lang_used = getattr(fetched, "language", language)
        except NoTranscriptFound:
            # Fallback: take whatever is available
            transcript_list = ytt_api.list(vid_id)
            first = next(iter(transcript_list), None)
            if first is None:
                return f"Aucune transcription disponible pour cette vidéo ({vid_id})."
            fetched = ytt_api.fetch(vid_id, languages=[first.language_code])
            lang_used = first.language

        entries = list(fetched)
        full_text = " ".join(
            e.get("text", "") if isinstance(e, dict) else str(getattr(e, "text", e))
            for e in entries
        )

        # Truncate to 4000 chars
        if len(full_text) > 4000:
            full_text = full_text[:4000] + "\n\n[… transcription tronquée]"

        return (
            f"Transcription de https://youtu.be/{vid_id} ({lang_used}) :\n\n"
            + full_text
        )

    except ImportError:
        return (
            "Le module youtube-transcript-api n'est pas installé. "
            "Ajoute 'youtube-transcript-api' dans pyproject.toml."
        )
    except Exception as exc:
        name = type(exc).__name__
        if "Disabled" in name or "disabled" in str(exc).lower():
            return f"Les sous-titres sont désactivés pour cette vidéo ({vid_id})."
        if "NoTranscript" in name:
            return f"Aucune transcription disponible pour cette vidéo ({vid_id})."
        return f"Erreur lors de la récupération de la transcription : {exc}"


@tool
async def youtube_video_info(video_url_or_id: str) -> str:
    """Get metadata about a YouTube video (title, description, channel, views, etc.).

    Args:
        video_url_or_id: YouTube URL or video ID
    """
    # Extract video ID
    vid_id = video_url_or_id.strip()
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pat in patterns:
        m = re.search(pat, vid_id)
        if m:
            vid_id = m.group(1)
            break

    settings = get_settings()
    api_key = getattr(settings, "youtube_api_key", None) or ""

    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "snippet,statistics,contentDetails",
                        "id": vid_id,
                        "key": api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                if not items:
                    return f"Vidéo introuvable : {vid_id}"

                item = items[0]
                sn = item["snippet"]
                stats = item.get("statistics", {})
                duration_raw = item.get("contentDetails", {}).get("duration", "")
                # Parse ISO8601 duration PT1H2M3S
                dur_m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_raw)
                if dur_m:
                    h, m, s = (int(x or 0) for x in dur_m.groups())
                    dur_str = f"{h}h {m}min {s}s" if h else f"{m}min {s}s"
                else:
                    dur_str = duration_raw

                desc = sn.get("description", "")[:300]
                if len(sn.get("description", "")) > 300:
                    desc += "…"

                return (
                    f"Titre : {sn['title']}\n"
                    f"Chaîne : {sn['channelTitle']}\n"
                    f"Durée : {dur_str}\n"
                    f"Vues : {int(stats.get('viewCount', 0)):,}\n"
                    f"Likes : {int(stats.get('likeCount', 0)):,}\n"
                    f"Publié : {sn['publishedAt'][:10]}\n"
                    f"URL : {_video_url(vid_id)}\n"
                    f"Description : {desc}"
                )
        except Exception as exc:
            logger.warning("YouTube video info API error: %s", exc)

    # Invidious fallback
    for instance in _INVIDIOUS_INSTANCES:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{instance}/api/v1/videos/{vid_id}")
                resp.raise_for_status()
                d = resp.json()

            length_sec = d.get("lengthSeconds", 0)
            dur_str = f"{length_sec // 3600}h {(length_sec % 3600) // 60}min" if length_sec >= 3600 else f"{length_sec // 60}min {length_sec % 60}s"
            desc = d.get("description", "")[:300]

            return (
                f"Titre : {d.get('title', '')}\n"
                f"Chaîne : {d.get('author', '')}\n"
                f"Durée : {dur_str}\n"
                f"Vues : {d.get('viewCount', 0):,}\n"
                f"Likes : {d.get('likeCount', 0):,}\n"
                f"Publié : {d.get('published', '')}\n"
                f"URL : {_video_url(vid_id)}\n"
                f"Description : {desc}{'…' if len(d.get('description',''))>300 else ''}"
            )
        except Exception:
            continue

    return f"Impossible de récupérer les infos pour la vidéo {vid_id}."
