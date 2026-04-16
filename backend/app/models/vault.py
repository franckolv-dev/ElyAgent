# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/models/vault.py
# @brief      Vault — encrypted secret storage
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
"""Vault — encrypted secret storage.

Two tables:
- ``vault_config`` : one row per user, stores the Argon2 salt used to
  derive the master AES key from the master password.
- ``vault``        : one row per secret, stores the AES-256-GCM
  ciphertext + nonce.  The master key (in RAM) is never persisted.

Security invariant: even with full database access, an attacker cannot
recover any secret without the master password (protected by Argon2id).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VaultConfig(Base):
    """Per-user vault configuration — notably the Argon2 salt."""
    __tablename__ = "vault_config"

    user_id    : str   = Column(String, ForeignKey("users.id"), primary_key=True)
    argon2_salt: bytes = Column(LargeBinary(16), nullable=False)  # 128-bit random salt
    created_at : datetime = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    entries = relationship("VaultEntry", back_populates="config",
                           cascade="all, delete-orphan", passive_deletes=True)


class VaultEntry(Base):
    """One encrypted secret per row."""
    __tablename__ = "vault"
    __table_args__ = (UniqueConstraint("user_id", "label", name="uq_vault_user_label"),)

    id              : str   = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id         : str   = Column(String, ForeignKey("vault_config.user_id",
                                                         ondelete="CASCADE"), nullable=False)
    label           : str   = Column(String(120), nullable=False)
    hint            : str   = Column(String(255), nullable=True)   # unencrypted memo
    encrypted_value : bytes = Column(LargeBinary, nullable=False)  # AES-GCM ciphertext + tag
    nonce           : bytes = Column(LargeBinary(12), nullable=False)  # 96-bit GCM nonce
    created_at      : datetime = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at      : datetime = Column(DateTime(timezone=True), default=_utcnow,
                                        onupdate=_utcnow, nullable=False)

    config = relationship("VaultConfig", back_populates="entries")
