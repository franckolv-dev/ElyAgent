# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/middleware/rate_limit.py
# @brief      Rate limiting middleware
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
from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings


def _get_real_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For set by trusted proxies.

    Priority: CF-Connecting-IP > X-Forwarded-For (first entry) > remote addr.
    This prevents rate-limit bypass when the app runs behind NGINX/Caddy/Cloudflare.
    """
    # Cloudflare
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    # Standard proxy header (first entry = original client)
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # Direct connection fallback
    if request.client:
        return request.client.host
    return "unknown"


# A-6 (revue 2026-06-10) — settings.rate_limit (env RATE_LIMIT) existait
# depuis le début mais n'était JAMAIS branché sur le limiter : seuls 3
# endpoints d'auth portaient un @limiter.limit explicite, tout le reste
# était illimité. default_limits + SlowAPIMiddleware appliquent désormais
# la limite à toutes les routes HTTP (les WebSockets ne sont pas concernés
# — leur débit est borné par B-15, le cap de runs agent par user).
# RATE_LIMIT accepte plusieurs bornes séparées par des virgules
# (ex. « 120/minute,2000/hour »).


def _default_limits() -> list[str]:
    raw = get_settings().rate_limit or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


limiter = Limiter(key_func=_get_real_ip, default_limits=_default_limits())


def setup_rate_limiter(app: FastAPI):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
