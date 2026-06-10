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


@router.get("/health/deep")
@limiter.exempt
async def health_check_deep():
    """Sonde profonde (revue 2026-06-10 §4) — `/health` répondait « ok »
    même avec une DB corrompue ou un Qdrant mort. Teste réellement les
    deux dépendances ; 503 si l'une est down (le monitoring voit ENFIN
    un backend malade). Reste volontairement anonyme : booléens, aucun
    détail d'infra."""
    import asyncio

    from fastapi.responses import JSONResponse

    checks = {"db": False, "qdrant": False}

    try:
        from sqlalchemy import text

        from app.database import async_session
        async with async_session() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=5)
        checks["db"] = True
    except Exception:
        pass

    try:
        from app.services.memory_manager import get_memory_manager
        client = get_memory_manager()._infra.client
        await asyncio.wait_for(
            asyncio.to_thread(client.get_collections), timeout=5,
        )
        checks["qdrant"] = True
    except Exception:
        pass

    healthy = all(checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", **checks},
        status_code=200 if healthy else 503,
    )
