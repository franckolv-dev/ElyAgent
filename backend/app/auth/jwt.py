# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/auth/jwt.py
# @brief      Jwt module
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings


def create_access_token(data: dict) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    """Create a refresh token with a unique jti claim for blacklist support (ARCH-3)."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),  # unique ID — stored on revocation
    })
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class TokenExpiredError(Exception):
    """Raised when the token signature is valid but the exp claim has passed."""


class TokenInvalidError(Exception):
    """Raised when the token cannot be decoded (bad signature, malformed, etc.)."""


def decode_token(token: str) -> dict | None:
    """Decode and verify a JWT. Returns payload or None (legacy callers).

    Prefer decode_token_strict() for new code that needs to distinguish
    expired vs. invalid tokens.
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def decode_token_strict(token: str) -> dict:
    """Decode and verify a JWT, raising a typed exception on failure (SEC-16).

    Raises:
        TokenExpiredError  — valid signature but token has expired
        TokenInvalidError  — bad signature, malformed, or any other JWTError
    """
    from jose.exceptions import ExpiredSignatureError
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except JWTError as exc:
        raise TokenInvalidError("Token is invalid") from exc
