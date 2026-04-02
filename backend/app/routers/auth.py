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
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.models.user import User
from app.models.revoked_token import RevokedToken
from app.schemas.auth import (
    RegisterRequest, LoginRequest,
    TokenResponse, AccessTokenResponse, UserResponse,
    ChangePasswordRequest,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.auth.dependencies import get_current_user, get_optional_user, require_admin
from app.config import get_settings

router = APIRouter()

_COOKIE_NAME = "refresh_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
        secure=settings.cookie_secure,
        path="/",
    )


def _make_token_payload(user: User) -> dict:
    """JWT payload enrichi avec le rôle et le username (évite des appels /me)."""
    return {"sub": user.id, "role": user.role, "username": user.username, "email": user.email}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    caller: User | None = Depends(get_optional_user),
):
    """
    Premier utilisateur → devient admin sans auth (bootstrap).
    Utilisateurs suivants → réservé aux admins connectés.
    """
    count_result = await db.execute(select(func.count(User.id)))
    is_first = count_result.scalar_one() == 0

    if not is_first:
        if caller is None or caller.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La création de compte est réservée aux administrateurs.",
            )

    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already exists")

    hashed = await hash_password(req.password)
    role = req.role if (not is_first and caller and caller.role == "admin" and req.role in ("admin", "user")) else ("admin" if is_first else "user")
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hashed,
        role=role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    req: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if not user or not await verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    payload = _make_token_payload(user)
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token({"sub": user.id})

    # Refresh token stored in HttpOnly cookie — never exposed to JS
    _set_refresh_cookie(response, refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    """Issue a new access_token using the HttpOnly refresh cookie."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Check blacklist — reject if this token was revoked (ARCH-3)
    jti = payload.get("jti")
    if jti:
        revoked = await db.execute(
            select(RevokedToken).where(RevokedToken.jti == jti)
        )
        if revoked.scalar_one_or_none():
            raise HTTPException(status_code=401, detail="Token revoked")

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    new_access = create_access_token(_make_token_payload(user))

    # Rotate the refresh token — revoke old one, issue a fresh one (ARCH-3)
    if jti:
        from datetime import datetime
        exp_ts = payload.get("exp", 0)
        expires_at = datetime.utcfromtimestamp(exp_ts)
        db.add(RevokedToken(jti=jti, expires_at=expires_at))
        await db.commit()
    _set_refresh_cookie(response, create_refresh_token({"sub": user.id}))

    return AccessTokenResponse(access_token=new_access)


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the refresh token and clear the cookie (ARCH-3)."""
    # Revoke the current token so it can't be reused even if captured
    if refresh_token:
        payload = decode_token(refresh_token)
        jti = payload.get("jti") if payload else None
        if jti:
            from datetime import datetime
            exp_ts = payload.get("exp", 0)
            expires_at = datetime.utcfromtimestamp(exp_ts)
            db.add(RevokedToken(jti=jti, expires_at=expires_at))
            await db.commit()

    settings = get_settings()
    response.delete_cookie(
        key=_COOKIE_NAME,
        path="/",
        samesite="strict",
        secure=settings.cookie_secure,
        httponly=True,
    )
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permet à un utilisateur connecté de changer son mot de passe.
    Exige la saisie du mot de passe actuel (RGPD — contrôle d'identité).
    """
    if not await verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe actuel est incorrect.",
        )
    if req.current_password == req.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien.",
        )
    current_user.hashed_password = await hash_password(req.new_password)
    await db.commit()
    return {"message": "Mot de passe modifié avec succès."}
