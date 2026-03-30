# -----------------------------------------------------------------------------
# Copyright (c) 2024 Franck OLLIVIER
# Tous droits réservés.
#
# Ce logiciel est mis à disposition sous les termes de la licence
# PolyForm Strict License 1.0.0.
#
# RÉSUMÉ DES CONDITIONS :
# - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
# - INTERDIT : Toute utilisation commerciale sans accord préalable.
# - INTERDIT : Redistribution de versions modifiées de ce code.
#
# Pour consulter le texte intégral de la licence, veuillez vous référer au
# fichier LICENSE à la racine du projet ou visiter :
# https://polyformproject.org/licenses/strict/1.0.0/
# -----------------------------------------------------------------------------
"""Analytics API — usage statistics for the dashboard."""
from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_current_user
from app.services.analytics_service import (
    get_summary, get_daily_usage, get_skill_usage, get_hitl_stats
)

router = APIRouter()


@router.get("/summary")
async def analytics_summary(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    return await get_summary(current_user.id, days)


@router.get("/daily")
async def analytics_daily(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    return await get_daily_usage(current_user.id, days)


@router.get("/skills")
async def analytics_skills(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    return await get_skill_usage(current_user.id, days)


@router.get("/hitl")
async def analytics_hitl(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    return await get_hitl_stats(current_user.id, days)


@router.get("/providers")
async def analytics_providers(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    from app.services.analytics_service import get_provider_breakdown
    return await get_provider_breakdown(current_user.id, days)
