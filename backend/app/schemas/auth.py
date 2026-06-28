# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/schemas/auth.py
# @brief      Authentication and JWT endpoints
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
import re
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Règles CNIL / RGPD pour les mots de passe ─────────────────────────────────
# Référentiel CNIL : 12 car. min + majuscule + minuscule + chiffre + spécial
_PASSWORD_MIN_LEN = 12

def _check_password_strength(v: str) -> str:
    errors = []
    if len(v) < _PASSWORD_MIN_LEN:
        errors.append(f"Au moins {_PASSWORD_MIN_LEN} caractères")
    if not re.search(r"[A-Z]", v):
        errors.append("Au moins une lettre majuscule")
    if not re.search(r"[a-z]", v):
        errors.append("Au moins une lettre minuscule")
    if not re.search(r"\d", v):
        errors.append("Au moins un chiffre")
    if not re.search(r"[^a-zA-Z0-9]", v):
        errors.append("Au moins un caractère spécial (!@#$%^&*...)")
    if errors:
        raise ValueError(" · ".join(errors))
    return v


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str = Field(..., min_length=_PASSWORD_MIN_LEN, description="Minimum 12 characters")
    role: str = "user"  # admin peut spécifier "admin" ou "user"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=_PASSWORD_MIN_LEN)

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=_PASSWORD_MIN_LEN)

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
