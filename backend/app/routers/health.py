# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/health.py
# @brief      Health check endpoint
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
from fastapi import APIRouter

from app.middleware.rate_limit import limiter

router = APIRouter()


@router.get("/health")
@limiter.exempt
async def health_check():
    # LOW-1: Do not expose service name or version to unauthenticated callers
    # Exempté du rate limit global (A-6) : sondé par le healthcheck Docker
    # et le monitoring — un 429 ici ferait flapper le conteneur.
    return {"status": "ok"}
