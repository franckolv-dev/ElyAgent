# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/health.py
# @brief      Health check endpoint
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    # LOW-1: Do not expose service name or version to unauthenticated callers
    return {"status": "ok"}
