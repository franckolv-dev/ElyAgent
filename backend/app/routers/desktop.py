"""ELY Desktop router.

Endpoints
---------
WS  /ws/desktop                — daemon WebSocket connection  (ws_router)
GET /api/desktop/status         — connection status            (api_router)
GET /api/desktop/config         — get sandbox_dirs config      (api_router)
PUT /api/desktop/config         — save sandbox_dirs config     (api_router)
GET /api/desktop/download-config— generate ely-config.json     (api_router)
GET /api/desktop/binaries       — list available binaries      (api_router)

Two separate APIRouter instances are exported so main.py can mount them under
the correct prefixes (/ws and /api respectively).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
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
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        data = json.loads(raw)
        token = data.get("token", "")
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError):
        await websocket.close(code=1008)
        return

    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

    # Register connection — merges handshake fields (platform, version, sandbox_dirs)
    desktop_registry.register(user_id, websocket, data)

    try:
        # Send acknowledgement
        await websocket.send_text(json.dumps({"type": "connected", "user_id": user_id}))

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
        logger.debug("Desktop daemon disconnected for user %s", user_id)
    except Exception as exc:
        logger.error(
            "Desktop daemon WebSocket error for user %s: %s", user_id, exc, exc_info=True
        )
    finally:
        desktop_registry.unregister(user_id)


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

@api_router.get("/desktop/binaries")
async def desktop_binaries(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return available binary download URLs."""
    settings = get_settings()
    base = settings.backend_url or str(request.base_url).rstrip("/")

    # These URLs point to where binaries would be hosted.
    # In production, replace base_url with the actual CDN / release URL.
    binaries = [
        {
            "os": "linux",
            "arch": "amd64",
            "filename": "ely-desktop-linux-amd64",
            "url": f"{base}/static/desktop/ely-desktop-linux-amd64",
        },
        {
            "os": "macos",
            "arch": "amd64",
            "filename": "ely-desktop-macos-amd64",
            "url": f"{base}/static/desktop/ely-desktop-macos-amd64",
        },
        {
            "os": "macos",
            "arch": "arm64",
            "filename": "ely-desktop-macos-arm64",
            "url": f"{base}/static/desktop/ely-desktop-macos-arm64",
        },
        {
            "os": "windows",
            "arch": "amd64",
            "filename": "ely-desktop-windows-amd64.exe",
            "url": f"{base}/static/desktop/ely-desktop-windows-amd64.exe",
        },
    ]

    return {"binaries": binaries}
