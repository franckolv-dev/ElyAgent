# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/api_keys.py
# @brief      REST CRUD for personal API keys (MCP server + API auth).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# =============================================================================
"""Personal API key management endpoints.

A logged-in user mints, lists, and revokes long-lived API keys to be used
by non-browser clients — primarily ELY's own MCP server (Claude Desktop &
other MCP clients connect with ``Authorization: Bearer ely_api_…``).

Flow
----
1. User clicks "Generate" in Settings → Clés API.
2. Frontend hits ``POST /api/api-keys`` with a friendly name.
3. Server returns the plaintext key ONCE — the frontend shows a
   "copy now or lose it" box. Only the SHA-256 hash + last 4 chars persist.
4. The client sends the key as a bearer token to the MCP endpoint.
5. The user can list and revoke keys from the same UI.

``authenticate_api_key()`` is the reusable resolver used both here and by
the MCP server's ASGI auth layer (J2).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.user import User

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Public prefix identifying a personal API key at a glance. Lets the MCP
#: middleware distinguish it from a JWT, and lets secret-scanning tools
#: (GitHub, gitleaks…) detect accidental commits.
KEY_PREFIX = "ely_api_"

#: 32 random bytes → 64 hex chars = 256 bits of entropy.
KEY_ENTROPY_BYTES = 32

#: Hard cap per user so a runaway script can't flood the table.
MAX_ACTIVE_KEYS_PER_USER = 20


def _generate_plaintext() -> str:
    """Return a fresh ``ely_api_<64 hex chars>`` key string."""
    return KEY_PREFIX + secrets.token_hex(KEY_ENTROPY_BYTES)


def hash_key(plaintext: str) -> str:
    """SHA-256 the plaintext key. Returns the 64-char hex digest."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def authenticate_api_key(plaintext: str, db: AsyncSession) -> Optional[User]:
    """Resolve a plaintext API key to its (active) owning user, or ``None``.

    Reusable across the FastAPI dependency and the MCP server's ASGI auth
    middleware. Constant-time-ish: we hash then index-lookup by hash. Updates
    ``last_used_at`` best-effort. Returns ``None`` for empty/malformed/
    unknown/revoked keys, or an inactive user.
    """
    if not plaintext or not plaintext.startswith(KEY_PREFIX):
        return None
    digest = hash_key(plaintext)
    row = (await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == digest,
            ApiKey.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    user = (await db.execute(
        select(User).where(User.id == row.user_id, User.is_active == True)  # noqa: E712
    )).scalar_one_or_none()
    if user is None:
        return None
    # Best-effort last-used stamp — never block auth on a write failure.
    try:
        row.last_used_at = datetime.utcnow()
        db.add(row)
        await db.commit()
    except Exception:
        await db.rollback()
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class KeyCreateRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=100,
        description="Free-form label, e.g. 'Claude Desktop' or 'Laptop CLI'",
    )


class KeyCreateResponse(BaseModel):
    id: str
    name: str
    key: str  # plaintext — shown ONCE, never returned again
    last_4: str
    created_at: datetime


class KeyListItem(BaseModel):
    id: str
    name: str
    last_4: str
    created_at: datetime
    last_used_at: Optional[datetime]
    revoked: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=KeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a new personal API key",
)
async def create_key(
    body: KeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KeyCreateResponse:
    active = (await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == current_user.id,
            ApiKey.revoked_at.is_(None),
        )
    )).scalars().all()
    if len(active) >= MAX_ACTIVE_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Maximum {MAX_ACTIVE_KEYS_PER_USER} clés actives atteint. "
                "Révoquez-en une avant d'en créer une nouvelle."
            ),
        )

    plaintext = _generate_plaintext()
    row = ApiKey(
        user_id=str(current_user.id),
        name=body.name.strip(),
        key_hash=hash_key(plaintext),
        last_4=plaintext[-4:],
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return KeyCreateResponse(
        id=row.id,
        name=row.name,
        key=plaintext,  # ⚠️ only time the plaintext leaves the server
        last_4=row.last_4,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[KeyListItem],
    summary="List the caller's API keys (active + revoked)",
)
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KeyListItem]:
    rows = (await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
    )).scalars().all()

    return [
        KeyListItem(
            id=r.id,
            name=r.name,
            last_4=r.last_4,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked=r.revoked_at is not None,
        )
        for r in rows
    ]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
)
async def revoke_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = (await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clé introuvable")

    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.add(row)
        await db.commit()
    # 204 No Content — no body
