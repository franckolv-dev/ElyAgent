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
"""REST API for the secure community skill marketplace.

All write operations (install, approve, revoke, uninstall) are admin-only.
Skills must be reviewed and approved before their tools become available
to the agent — unlike OpenClaw's ClawHub which allows arbitrary code execution.

Endpoints
---------
GET    /api/marketplace/skills           List installed community skills
POST   /api/marketplace/skills/install   Install a skill from uploaded archive
POST   /api/marketplace/skills/{slug}/approve   Approve and grant permissions
POST   /api/marketplace/skills/{slug}/revoke    Revoke approval
DELETE /api/marketplace/skills/{slug}    Uninstall a skill
"""
from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_admin
from app.services.marketplace import get_marketplace_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Schemas                                                              #
# ------------------------------------------------------------------ #

class ApproveRequest(BaseModel):
    grant_permissions: list[str] = []


# ------------------------------------------------------------------ #
# Routes                                                               #
# ------------------------------------------------------------------ #

@router.get("/skills")
async def list_community_skills(
    current_user=Depends(get_current_user),
):
    """List all installed community skills."""
    marketplace = get_marketplace_service()
    return await marketplace.list_installed()


@router.post("/skills/install")
async def install_skill(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
):
    """Install a community skill from a ZIP archive.

    The archive must contain a manifest.yml at the root level.
    The skill is installed but NOT approved — admin must review the code
    and explicitly approve it before tools become available.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip archives are accepted",
        )

    # Size limit: 10 MB
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Archive too large (max 10 MB)",
        )

    marketplace = get_marketplace_service()

    # Extract to temp dir and install
    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "skill.zip"
        zip_path.write_bytes(content)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Security: check for path traversal
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Dangerous path in archive: {name}",
                        )
                zf.extractall(Path(tmp_dir) / "extracted")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP archive")

        extracted = Path(tmp_dir) / "extracted"

        # Find manifest — could be at root or in a subdirectory
        manifest_candidates = list(extracted.rglob("manifest.yml")) + \
                              list(extracted.rglob("manifest.yaml"))
        if not manifest_candidates:
            raise HTTPException(
                status_code=400,
                detail="No manifest.yml found in archive",
            )

        skill_dir = manifest_candidates[0].parent

        try:
            result = await marketplace.install_from_directory(
                source_dir=skill_dir,
                installed_by=current_user.username,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return result


@router.post("/skills/{slug}/approve")
async def approve_skill(
    slug: str,
    body: ApproveRequest,
    current_user=Depends(require_admin),
):
    """Approve a community skill and grant specific permissions.

    Only granted permissions (subset of declared) will be available
    to the skill at runtime.
    """
    marketplace = get_marketplace_service()
    try:
        result = await marketplace.approve_skill(slug, body.grant_permissions)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.post("/skills/{slug}/revoke")
async def revoke_skill(
    slug: str,
    current_user=Depends(require_admin),
):
    """Revoke approval — tools are immediately unloaded from the agent."""
    marketplace = get_marketplace_service()
    try:
        result = await marketplace.revoke_skill(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.delete("/skills/{slug}")
async def uninstall_skill(
    slug: str,
    current_user=Depends(require_admin),
):
    """Completely remove a community skill (files + DB record)."""
    marketplace = get_marketplace_service()
    try:
        result = await marketplace.uninstall_skill(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result
