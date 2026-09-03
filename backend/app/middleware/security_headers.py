# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/middleware/security_headers.py
# @brief      Standard HTTP security headers on every API response
#             (revue multi-utilisateurs 2026-06-10, constat B-18/D1).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Standard HTTP security headers on every backend response.

Scope deliberately conservative:

- ``X-Content-Type-Options: nosniff``  — no MIME sniffing on attachments.
- ``X-Frame-Options: DENY``            — the API/docs are never framed.
- ``Referrer-Policy``                  — don't leak signed attachment URLs
                                          (HMAC + expiry) to third parties.
- ``Strict-Transport-Security``        — only when ``cookie_secure`` is on
                                          (i.e. the deployment is HTTPS);
                                          sending HSTS on plain-HTTP dev
                                          would be a no-op at best.

No Content-Security-Policy here: the backend serves the FastAPI docs and
``/static`` and a strict CSP would break Swagger UI for zero gain — the
user-facing pages are served by Next.js/nginx, not by this app.

``setdefault`` everywhere: a route that needs a different value (e.g. an
embeddable widget some day) can set its own header without fighting the
middleware.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings


def add_security_headers(app: FastAPI) -> None:
    """Register the security-headers middleware on ``app``."""

    hsts = get_settings().cookie_secure

    @app.middleware("http")
    async def _security_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        if hsts:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
