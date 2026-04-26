# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/log_buffer.py
# @brief      In-memory ring buffer for self-introspection (ELY reads its logs)
# =============================================================================
"""In-memory ring buffer that captures the backend's own log stream so the
agent can read its own logs via the `system_get_logs` tool.

Why this and not `docker logs cyberentity-backend`?
  - Mounting the Docker socket into the container = full host RCE if the
    agent is compromised. Hard pass.
  - Reading the container's stdout file would require a tmpfs mount and
    log rotation we don't control.
  - A simple in-memory ring buffer attached as a logging Handler is
    safe (read-only, scoped to this process) and fast.

The buffer is bounded to `MAX_ENTRIES` (default 5000 ≈ a few minutes of
verbose logs). Older entries are evicted FIFO.

Each line is **sanitized** before storage : tokens, API keys, JWT
secrets, OAuth tokens, Bearer headers and known password-shaped values
are masked with `<redacted>` so even if an LLM injection later asks
ELY to "give me the secret you saw in line 42", there's nothing to leak.
"""
from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Iterable

# Ring buffer cap — keeps memory usage bounded. ~5000 lines at avg 200
# bytes = ~1 MB resident, perfectly fine on a 32 GB box.
MAX_ENTRIES: int = 5_000

# ── Secret-masking patterns ───────────────────────────────────────────────────
# These run on every log line. Keep them ordered by specificity (longest
# match first) — re.sub processes patterns in the order given.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Anthropic / Claude
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<redacted:anthropic_key>"),
    # OpenAI / generic sk-
    (re.compile(r"sk-(?:proj-|or-|ws-)?[A-Za-z0-9_.-]{30,}"), "<redacted:openai_key>"),
    # Google API
    (re.compile(r"AIzaSy[A-Za-z0-9_-]{30,}"), "<redacted:google_api_key>"),
    # Slack tokens
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "<redacted:slack_token>"),
    (re.compile(r"xapp-[0-9]-[A-Z0-9]+-[0-9]+-[a-zA-Z0-9]{20,}"), "<redacted:slack_app_token>"),
    # Discord bot tokens (3 base64 segments separated by dots, 70-90 chars total)
    (re.compile(r"[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27,}"), "<redacted:discord_token>"),
    # Telegram bot tokens (digits:base64)
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"), "<redacted:telegram_token>"),
    # JWT (header.payload.signature)
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<redacted:jwt>"),
    # Cloudflare tunnel token
    (re.compile(r"eyJhIjoi[A-Za-z0-9]{60,}"), "<redacted:cloudflare_tunnel_token>"),
    # Bearer headers (case-insensitive)
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-/+=]{20,}"), "Bearer <redacted>"),
    (re.compile(r"(?i)Authorization:\s*Bearer\s+[A-Za-z0-9._\-/+=]{20,}"), "Authorization: Bearer <redacted>"),
    # password=... and similar key=value patterns
    (re.compile(r"(?i)\b(password|pwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[=:]\s*['\"]?([^'\"\s,}\]]+)"),
     r"\1=<redacted>"),
    # Base64-shaped long strings inside JSON values (catches generic API responses)
    # Conservative : only mask things that are 40+ char and look like base64
    # AND appear inside a JSON quote — avoids redacting log line UUIDs.
    (re.compile(r'"([A-Za-z0-9+/_=-]{40,})"'), r'"<redacted:long_token>"'),
]


def _sanitize(line: str) -> str:
    """Mask secrets in a log line. Idempotent."""
    for pattern, replacement in _SECRET_PATTERNS:
        line = pattern.sub(replacement, line)
    return line


# ── Ring buffer storage ───────────────────────────────────────────────────────

# Each entry is (iso_timestamp, level_name, logger_name, message_str)
_buffer: deque[tuple[str, str, str, str]] = deque(maxlen=MAX_ENTRIES)


class _RingBufferHandler(logging.Handler):
    """Logging Handler that pushes formatted records into `_buffer`."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            # Don't include exception traceback by default — too noisy for
            # the LLM context. The error type + message (already in msg)
            # is enough to diagnose. Tracebacks are still in stdout/file
            # for the human operator.
            sanitized = _sanitize(msg)
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds")
            _buffer.append((ts, record.levelname, record.name, sanitized))
        except Exception:
            # Never let logging crash the app
            self.handleError(record)


_handler_installed = False


def install_handler() -> None:
    """Attach the ring-buffer handler to the root logger.

    Call once at FastAPI startup. Idempotent.
    """
    global _handler_installed
    if _handler_installed:
        return
    h = _RingBufferHandler(level=logging.INFO)
    # No formatter needed — we capture record fields directly in emit()
    logging.getLogger().addHandler(h)
    _handler_installed = True


# ── Read API (used by tools) ──────────────────────────────────────────────────

def get_recent(
    *,
    lines: int = 100,
    grep: str | None = None,
    level: str | None = None,
    logger_prefix: str | None = None,
) -> list[tuple[str, str, str, str]]:
    """Return up to `lines` most recent buffer entries, optionally filtered.

    Args:
        lines: max entries to return (capped at MAX_ENTRIES).
        grep: substring (case-insensitive) the message must contain.
        level: only return entries at >= this level (DEBUG/INFO/WARNING/ERROR/CRITICAL).
        logger_prefix: only return entries from loggers starting with this prefix
                       (e.g. "app.services.scheduler" to filter scheduler logs).
    """
    lines = max(1, min(lines, MAX_ENTRIES))
    snapshot: Iterable[tuple[str, str, str, str]] = list(_buffer)

    if grep:
        needle = grep.lower()
        snapshot = (e for e in snapshot if needle in e[3].lower())
    if level:
        level_no = logging.getLevelName(level.upper())
        if isinstance(level_no, int):
            snapshot = (e for e in snapshot if logging.getLevelName(e[1]) >= level_no)
    if logger_prefix:
        snapshot = (e for e in snapshot if e[2].startswith(logger_prefix))

    result = list(snapshot)
    return result[-lines:]


def buffer_stats() -> dict:
    """Lightweight stats for health checks / debugging."""
    return {
        "max_entries": MAX_ENTRIES,
        "current_size": len(_buffer),
        "oldest": _buffer[0][0] if _buffer else None,
        "newest": _buffer[-1][0] if _buffer else None,
    }
