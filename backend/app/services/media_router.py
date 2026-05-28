# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/media_router.py
# @brief      Parse MEDIA:<path> sentinels in agent responses and convert them
#             into attachment payloads for the frontend.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Media router — bridge between LLM prose and frontend attachments.

Inspired by Hermes' MEDIA:<path> sentinel pattern (audit 2026-05-06).

Rationale
---------
LLMs that fail to call a delivery tool (`gmail_send_with_local_attachment`,
`drive_create_file`, etc.) often still mention the file path in prose
("I'll send you /tmp/ely-attachments/screenshot-abc.png"). This module
intercepts that prose and turns the path reference into an actual
attachment payload pushed via WebSocket — even when the LLM forgot to
trigger the proper tool.

Two extraction modes
--------------------
1. **Explicit sentinel** : ``MEDIA:/tmp/ely-attachments/screenshot-abc.png``
   is the canonical form documented in the ``browser_screenshot`` tool's
   docstring. Lines containing this token are stripped from the visible
   response and added to the attachment list.

2. **Bare path mention** : if a model writes a path under one of the
   whitelisted dirs as a "natural" reference (e.g. inside a sentence like
   « Le fichier est ``/tmp/ely-attachments/screenshot-xyz.png`` »), we
   still extract it as an attachment but **leave the prose intact**
   (the user can read it).

Security
--------
Only paths under whitelisted attachment dirs are exposed. Arbitrary
absolute paths in the response are NEVER returned (they'd leak server
filesystem structure if the LLM hallucinated one).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)


# Signed-URL TTL for attachment links (seconds). Long enough that a user
# can scroll back through a conversation and still see images, short enough
# that a leaked URL can't be reused indefinitely.
_SIGNED_URL_TTL: Final[int] = 24 * 3600  # 24h


# Whitelisted attachment directories. Mirror the list used by
# ``gmail_send_with_local_attachment`` to ensure end-to-end consistency.
_ALLOWED_DIRS: Final[tuple[str, ...]] = (
    "/tmp/ely-attachments",
    "/data/attachments",
    "/app/data/attachments",
)

# Allowed extensions — image, doc, basic data files. Anything else is
# rejected (defense against the LLM mentioning binaries or scripts).
_ALLOWED_EXTS: Final[frozenset[str]] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".txt", ".md", ".csv", ".json",
})

# Token regex: ``MEDIA:`` followed by an absolute path. Captures up to
# the next whitespace, comma, period-then-whitespace, or quote char.
_MEDIA_TOKEN_RE = re.compile(
    r"MEDIA\s*:\s*[\"'`]?(/[^\s,'\"`)]+\.[a-zA-Z0-9]+)[\"'`]?",
    re.IGNORECASE,
)

# Bare path detection — only triggers for whitelisted dirs.
_BARE_PATH_RE = re.compile(
    r"(?<![/\w])(/(?:tmp/ely-attachments|data/attachments|app/data/attachments)/[^\s,'\"`)<>]+\.[a-zA-Z0-9]+)"
)


@dataclass(frozen=True)
class MediaExtraction:
    """Result of extracting media references from an LLM response."""

    cleaned_text: str
    """The response text with ``MEDIA:`` sentinel lines stripped (bare path
    mentions are preserved for readability)."""

    attachments: list[dict]
    """List of attachment payloads ready to send via WebSocket. Each dict
    has keys: ``path`` (str), ``filename`` (str), ``mime`` (str), ``size`` (int)."""


def _is_allowed_path(path: str) -> bool:
    """True if path is under a whitelisted dir AND has an allowed extension
    AND actually exists on disk."""
    if not path or not isinstance(path, str):
        return False
    norm = os.path.normpath(path)
    # Reject path traversal attempts
    if ".." in norm.split(os.sep):
        return False
    if not any(norm.startswith(d + os.sep) or norm == d for d in _ALLOWED_DIRS):
        return False
    ext = os.path.splitext(norm)[1].lower()
    if ext not in _ALLOWED_EXTS:
        return False
    if not os.path.isfile(norm):
        return False
    return True


def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")


def _signing_key() -> bytes:
    """Derive an HMAC key from the JWT secret. Lazy-imported to avoid a
    circular config import at module load."""
    from app.config import get_settings
    return hashlib.sha256(
        ("ely-attachment-signing-v1:" + get_settings().jwt_secret_key).encode()
    ).digest()


def sign_path(path: str, ttl: int = _SIGNED_URL_TTL) -> tuple[str, int]:
    """Return (signature, expiry_unix_ts) for a given path.

    The frontend appends ``&exp=...&sig=...`` to the URL; the attachments
    router verifies both before serving.
    """
    exp = int(time.time()) + ttl
    msg = f"{path}|{exp}".encode()
    sig = hmac.new(_signing_key(), msg, hashlib.sha256).hexdigest()
    return sig, exp


def verify_signature(path: str, exp: int | str, sig: str) -> bool:
    """Constant-time verification. Returns True iff signature is valid AND
    not expired."""
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_int < int(time.time()):
        return False
    expected = hmac.new(
        _signing_key(),
        f"{path}|{exp_int}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig or "")


def _make_attachment(path: str) -> dict | None:
    if not _is_allowed_path(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    sig, exp = sign_path(path)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "mime_type": _guess_mime(path),  # match frontend Attachment interface
        "size": size,
        # Signed-URL parameters — frontend appends to /api/attachments/?path=...
        "exp": exp,
        "sig": sig,
    }


def extract_media(text: str) -> MediaExtraction:
    """Extract attachments from an LLM response.

    Strategy
    --------
    1. Scan for ``MEDIA:`` sentinels — strip the matching line/token from
       the visible text, register the path as an attachment (if valid).
    2. Scan for bare paths under whitelisted dirs — register as attachment
       but leave prose intact.
    3. De-duplicate by absolute path.
    """
    if not text or not isinstance(text, str):
        return MediaExtraction(cleaned_text=text or "", attachments=[])

    seen: set[str] = set()
    attachments: list[dict] = []

    def _add(p: str) -> None:
        norm = os.path.normpath(p)
        if norm in seen:
            return
        seen.add(norm)
        att = _make_attachment(norm)
        if att:
            attachments.append(att)
            logger.info("media_router: extracted attachment %s (%d bytes)",
                        norm, att["size"])
        else:
            logger.debug("media_router: rejected path %r (whitelist/exists check failed)", norm)

    # 1. MEDIA:<path> sentinels — strip from visible text
    cleaned = _MEDIA_TOKEN_RE.sub(
        lambda m: (_add(m.group(1)) or ""),
        text,
    )
    # Collapse blank lines left by sentinel removal
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned).strip()

    # 2. Bare paths in remaining prose
    for m in _BARE_PATH_RE.finditer(cleaned):
        _add(m.group(1))

    return MediaExtraction(cleaned_text=cleaned, attachments=attachments)
