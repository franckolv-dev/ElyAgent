# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/extension_tokens.py
# @brief      REST CRUD for long-lived browser-extension tokens (Sprint 0.5).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Browser-extension token management endpoints.

These endpoints let a logged-in user mint, list, and revoke long-lived
tokens to be pasted into the ELY browser extension.

Flow
----
1. User clicks "Generate token" in Settings → Extension.
2. Frontend hits ``POST /api/extension/tokens`` with a friendly name.
3. Server returns the plaintext token ONCE — the frontend shows it in a
   "copy now or lose it" UI. The plaintext is never persisted; only the
   SHA-256 hash and the last 4 chars (for later identification) are.
4. The extension then connects to ``/ws/browser-extension`` using that
   token in the ``hello`` envelope instead of the short-lived JWT.
5. The user can list and revoke tokens from the same UI.

The endpoint deliberately does NOT support updating an existing token
(name aside). Once minted, a token is either active or revoked.
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
from app.models.extension_token import ExtensionToken
from app.models.user import User

router = APIRouter(prefix="/api/extension/tokens", tags=["extension-tokens"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Public prefix that identifies an extension token at a glance. Helps the
#: backend distinguish it from a regular JWT during WS handshake, and helps
#: secret-scanning tools (GitHub, gitleaks…) detect accidental commits.
TOKEN_PREFIX = "ely_ext_"

#: Raw entropy of the token body. 24 random bytes → 48 hex chars = 192 bits.
#: Comfortably above the 128-bit minimum, well below any URL length issue.
TOKEN_ENTROPY_BYTES = 24

#: Hard cap per user so a runaway script can't flood the table.
MAX_ACTIVE_TOKENS_PER_USER = 20


def _generate_plaintext() -> str:
    """Return a fresh ``ely_ext_<48 hex chars>`` token string."""
    return TOKEN_PREFIX + secrets.token_hex(TOKEN_ENTROPY_BYTES)


def hash_token(plaintext: str) -> str:
    """SHA-256 the plaintext token. Returns the 64-char hex digest."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TokenCreateRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=100,
        description="Free-form label, e.g. 'Chrome Mac Studio' or 'Personal MacBook'",
    )


class TokenCreateResponse(BaseModel):
    id: str
    name: str
    token: str  # plaintext — shown ONCE, never returned again
    last_4: str
    created_at: datetime


class TokenListItem(BaseModel):
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
    response_model=TokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a new extension token",
)
async def create_token(
    body: TokenCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenCreateResponse:
    # Cap active tokens — encourages users to revoke stale ones.
    active_count = (await db.execute(
        select(ExtensionToken).where(
            ExtensionToken.user_id == current_user.id,
            ExtensionToken.revoked_at.is_(None),
        )
    )).scalars().all()
    if len(active_count) >= MAX_ACTIVE_TOKENS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Maximum {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached. "
                "Revoke an old one first."
            ),
        )

    plaintext = _generate_plaintext()
    token_hash = hash_token(plaintext)
    last_4 = plaintext[-4:]

    row = ExtensionToken(
        user_id=str(current_user.id),
        name=body.name.strip(),
        token_hash=token_hash,
        last_4=last_4,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return TokenCreateResponse(
        id=row.id,
        name=row.name,
        token=plaintext,  # ⚠️ only time the plaintext leaves the server
        last_4=row.last_4,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=list[TokenListItem],
    summary="List the caller's extension tokens (active + revoked)",
)
async def list_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TokenListItem]:
    rows = (await db.execute(
        select(ExtensionToken)
        .where(ExtensionToken.user_id == current_user.id)
        .order_by(ExtensionToken.created_at.desc())
    )).scalars().all()

    return [
        TokenListItem(
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
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an extension token",
)
async def revoke_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = (await db.execute(
        select(ExtensionToken).where(
            ExtensionToken.id == token_id,
            ExtensionToken.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.add(row)
        await db.commit()
    # 204 No Content — no body
