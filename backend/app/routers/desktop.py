# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/desktop.py
# @brief      ELY Desktop router
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""ELY Desktop router.

Endpoints
---------
WS  /ws/desktop                — daemon WebSocket connection  (ws_router)
GET /api/desktop/status         — connection status            (api_router)
GET /api/desktop/config         — get sandbox_dirs config      (api_router)
PUT /api/desktop/config         — save sandbox_dirs config     (api_router)
GET /api/desktop/download-config— generate ely-config.json     (api_router)
GET /api/desktop/binaries       — list available binaries      (api_router)
GET /api/desktop/binaries/{filename} — download one binary     (api_router)

Two separate APIRouter instances are exported so main.py can mount them under
the correct prefixes (/ws and /api respectively).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.auth.jwt import decode_token
from app.config import get_settings
from app.database import async_session
from app.models.user import User
from app.services import desktop_registry
from app.services.system_config import get_config, set_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple rate limiter for WebSocket connection attempts (SEC-15)
# Protects against brute-force token guessing on the WS endpoint.
# ---------------------------------------------------------------------------
import time as _time
import threading as _threading
from collections import defaultdict as _defaultdict

_ws_attempts: dict[str, list[float]] = _defaultdict(list)
_ws_lock = _threading.Lock()
_WS_MAX_ATTEMPTS = 10   # max connection attempts
_WS_WINDOW_SEC   = 60   # per minute per IP


def _ws_rate_check(ip: str) -> bool:
    """Return True if the IP is within the allowed rate, False if exceeded."""
    now = _time.monotonic()
    with _ws_lock:
        attempts = _ws_attempts[ip]
        # Keep only timestamps within the window
        _ws_attempts[ip] = [t for t in attempts if now - t < _WS_WINDOW_SEC]
        if len(_ws_attempts[ip]) >= _WS_MAX_ATTEMPTS:
            return False
        _ws_attempts[ip].append(now)
        return True


# WS routes — mounted under /ws
ws_router = APIRouter()

# REST routes — mounted under /api
api_router = APIRouter()

# Keep a default `router` alias pointing to api_router for backward compatibility
router = api_router

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DesktopConfigRequest(BaseModel):
    sandbox_dirs: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sandbox_dirs_key(user_id: str) -> str:
    return f"desktop_sandbox_dirs_{user_id}"


async def _get_sandbox_dirs(user_id: str) -> list[str]:
    raw = await get_config(_sandbox_dirs_key(user_id), fallback="[]")
    try:
        dirs = json.loads(raw)
        if isinstance(dirs, list):
            return dirs
    except (json.JSONDecodeError, ValueError):
        pass
    return []


# ---------------------------------------------------------------------------
# WS /ws/desktop  — daemon connection
# ---------------------------------------------------------------------------

@ws_router.websocket("/desktop")
async def websocket_desktop(websocket: WebSocket):
    """WebSocket endpoint for the ELY Desktop daemon.

    Auth pattern mirrors /ws/chat:
      accept() → receive JSON handshake → decode_token → process or close 4001
    """
    # Rate-limit connection attempts per IP (SEC-15)
    client_ip = (websocket.client.host if websocket.client else "unknown")
    if not _ws_rate_check(client_ip):
        await websocket.accept()
        await websocket.close(code=4029, reason="Too many connection attempts")
        logger.warning("[desktop-ws] rate limit exceeded for %s", client_ip)
        return

    await websocket.accept()
    logger.debug("[desktop-ws] connection accepted, waiting for handshake…")

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        data = json.loads(raw)
        token = data.get("token", "")
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("[desktop-ws] handshake failed: %s", exc)
        await websocket.close(code=1008)
        return

    if not token:
        logger.warning("[desktop-ws] empty token")
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        logger.warning("[desktop-ws] token invalid or wrong type")
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        logger.warning("[desktop-ws] no sub in token")
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            logger.warning("[desktop-ws] user %s not found or inactive", user_id)
            await websocket.close(code=4001, reason="User not found")
            return

    # Register connection — merges handshake fields (platform, version, sandbox_dirs)
    desktop_registry.register(user_id, websocket, data)
    logger.info("[desktop-ws] registered user=%s platform=%s", user_id, data.get("platform"))

    try:
        await websocket.send_text(json.dumps({"type": "connected", "user_id": user_id}))
        logger.debug("[desktop-ws] ack sent, entering read loop for user %s", user_id)

        while True:
            raw_msg = await websocket.receive_text()
            try:
                message = json.loads(raw_msg)
            except json.JSONDecodeError:
                logger.warning(
                    "Desktop daemon: malformed JSON from user %s (ignored)", user_id
                )
                continue

            # Results from the daemon (responses to our commands)
            if "cmd_id" in message:
                desktop_registry.deliver_result(user_id, message)
            else:
                logger.debug(
                    "Desktop daemon: unhandled message type from user %s: %s",
                    user_id,
                    message.get("type", "unknown"),
                )

    except WebSocketDisconnect:
        logger.info("[desktop-ws] daemon disconnected for user %s", user_id)
    except Exception as exc:
        logger.error("[desktop-ws] unexpected error for user %s: %s", user_id, exc, exc_info=True)
    finally:
        # ws= : si le daemon s'est déjà reconnecté (reset Cloudflare + retour
        # en ~2 s), ce vieux handler ne doit pas éjecter la connexion fraîche.
        desktop_registry.unregister(user_id, ws=websocket)
        logger.debug("[desktop-ws] unregistered user %s", user_id)


# ---------------------------------------------------------------------------
# GET /api/desktop/status
# ---------------------------------------------------------------------------

@api_router.get("/desktop/status")
async def desktop_status(current_user: User = Depends(get_current_user)) -> dict:
    """Return connection status of the ELY Desktop daemon for the current user."""
    conn = desktop_registry.get(current_user.id)
    if conn is None:
        return {"connected": False}
    return {
        "connected": True,
        "platform": conn.platform,
        "version": conn.version,
        "sandbox_dirs": conn.sandbox_dirs,
        "connected_at": conn.connected_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/desktop/config
# ---------------------------------------------------------------------------

@api_router.get("/desktop/config")
async def desktop_get_config(current_user: User = Depends(get_current_user)) -> dict:
    """Return sandbox_dirs config from system_config table."""
    dirs = await _get_sandbox_dirs(current_user.id)
    return {"sandbox_dirs": dirs}


# ---------------------------------------------------------------------------
# PUT /api/desktop/config
# ---------------------------------------------------------------------------

@api_router.put("/desktop/config")
async def desktop_put_config(
    body: DesktopConfigRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Save sandbox_dirs to system_config table."""
    await set_config(
        _sandbox_dirs_key(current_user.id),
        json.dumps(body.sandbox_dirs),
        is_secret=False,
        description=f"ELY Desktop sandbox directories for user {current_user.id}",
    )
    return {"saved": True, "sandbox_dirs": body.sandbox_dirs}


# ---------------------------------------------------------------------------
# GET /api/desktop/download-config
# ---------------------------------------------------------------------------

@api_router.get("/desktop/download-config")
async def desktop_download_config(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Generate and return ely-config.json with a 30-day JWT token."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt

    settings = get_settings()

    # Build a 30-day token with client claim
    data = {
        "sub": current_user.id,
        "type": "access",
        "client": "desktop",
        "username": current_user.username,
    }
    expire = datetime.now(timezone.utc) + timedelta(days=30)
    data["exp"] = expire
    long_lived_token = jwt.encode(
        data, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

    sandbox_dirs = await _get_sandbox_dirs(current_user.id)

    # Determine base URL
    vps_url = settings.backend_url or str(request.base_url).rstrip("/")

    config_payload = {
        "vps_url": vps_url,
        "token": long_lived_token,
        "sandbox_dirs": sandbox_dirs,
        # Opt-in : le daemon (>= 1.2.0) n'ouvre l'UI web au démarrage que si
        # true — l'utilisateur a déjà un onglet ouvert quand il télécharge ce
        # fichier, l'auto-open dupliquait l'onglet à chaque relance.
        "open_browser": False,
        "version": "1.0.0",
    }

    return JSONResponse(
        content=config_payload,
        headers={
            "Content-Disposition": 'attachment; filename="ely-config.json"',
            "Content-Type": "application/json",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/desktop/binaries
# ---------------------------------------------------------------------------

_BINARY_CATALOG = [
    {"os": "linux",   "arch": "amd64", "filename": "ely-desktop-linux-amd64",       "installer_filename": "install.sh"},
    {"os": "macos",   "arch": "amd64", "filename": "ely-desktop-macos-amd64",       "installer_filename": "install.sh"},
    {"os": "macos",   "arch": "arm64", "filename": "ely-desktop-macos-arm64",       "installer_filename": "install.sh"},
    {"os": "windows", "arch": "amd64", "filename": "ely-desktop-windows-amd64.exe", "installer_filename": "install.bat"},
]

# Allowlist stricte de GET /desktop/binaries/{filename} : uniquement les
# fichiers du catalogue (binaires + installeurs), rien d'autre du dossier.
_DOWNLOADABLE_FILENAMES = frozenset(
    entry["filename"] for entry in _BINARY_CATALOG
) | frozenset(entry["installer_filename"] for entry in _BINARY_CATALOG)


def _desktop_static_dir() -> Path:
    # Le volume Docker pointe sur backend/static/desktop côté container,
    # qui est lui-même monté sur ./desktop/dist côté host.
    # Si le dossier n'existe pas (très early dev), on évite le crash.
    static_dir = Path("/app/static/desktop")
    if not static_dir.is_dir():
        # Fallback dev local hors Docker
        static_dir = Path(__file__).resolve().parents[3] / "desktop" / "dist"
    return static_dir


@api_router.get("/desktop/binaries")
async def desktop_binaries(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return available binary download URLs.

    Filtre les binaires à ceux qui existent réellement sur disque (montés
    depuis ./desktop/dist). Sans ce filtre, un self-hoster qui clone le
    repo sans avoir buildé voyait 4 liens cliquables qui retournaient une
    404 HTML — l'utilisateur téléchargeait alors un fichier `.html` au
    lieu du binaire (ticket mai 2026).

    Renvoie aussi un champ `build_help` quand AUCUN binaire n'est dispo,
    pour que l'UI puisse afficher des instructions de build au lieu de
    boutons cassés.
    """
    settings = get_settings()
    base = settings.backend_url or str(request.base_url).rstrip("/")

    static_dir = _desktop_static_dir()

    binaries = []
    for entry in _BINARY_CATALOG:
        bin_path = static_dir / entry["filename"]
        if not bin_path.is_file():
            continue  # build manquant — on n'expose pas un lien cassé
        installer_path = static_dir / entry["installer_filename"]
        binaries.append({
            **entry,
            "size_bytes": bin_path.stat().st_size,
            "url": f"{base}/api/desktop/binaries/{entry['filename']}",
            "installer": f"{base}/api/desktop/binaries/{entry['installer_filename']}" if installer_path.is_file() else None,
        })

    response: dict = {"binaries": binaries}
    if not binaries:
        # Message d'aide pour les self-hosters qui n'ont pas encore buildé
        response["build_help"] = {
            "message": "Aucun binaire ELY Desktop n'est buildé. Pour les construire, va à la racine du projet et lance: `bash desktop/build.sh` (Go requis) ou via Docker: `docker run --rm -v $(pwd)/desktop:/src -w /src golang:1.23-alpine sh -lc 'apk add --no-cache bash && bash build.sh'`",
            "github_release": "https://github.com/franckolv-dev/PhysicalAgent/releases/latest",
            "build_doc": "/docs/SETUP_DESKTOP.md",
        }
    return response


# ---------------------------------------------------------------------------
# GET /api/desktop/binaries/{filename}
# ---------------------------------------------------------------------------

@api_router.get("/desktop/binaries/{filename}")
async def desktop_binary_download(filename: str) -> FileResponse:
    """Sert un binaire/installeur ELY Desktop en téléchargement forcé.

    Servis par le mount statique /static/desktop, les binaires sans
    extension (ely-desktop-macos-arm64, …) recevaient un MIME deviné
    text/plain → Safari/Chrome enregistraient « ely-desktop-macos-arm64.txt »
    (ticket juin 2026). Ici : application/octet-stream + Content-Disposition
    attachment, qui force le nom exact côté navigateur.

    Pas d'authentification : l'UI déclenche le téléchargement via un
    <a href> brut qui ne porte pas le header Authorization — parité avec
    le mount statique public que cette route remplace (les binaires sont
    de toute façon publiés sur les GitHub Releases).
    """
    if filename not in _DOWNLOADABLE_FILENAMES:
        raise HTTPException(status_code=404, detail="Fichier inconnu")

    path = _desktop_static_dir() / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Binaire non buildé")

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
    )
