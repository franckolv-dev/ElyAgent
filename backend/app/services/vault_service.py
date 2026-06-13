# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/vault_service.py
# @brief      Vault service — AES-256-GCM encryption with Argon2id key derivation
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
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Vault service — AES-256-GCM encryption with Argon2id key derivation.

Architecture
------------
- One Argon2id salt per user (stored in vault_config).
- `unlock_vault()` derives the 32-byte AES key once and keeps it in RAM
  as a `bytearray` in `_keys[user_id]`.
- `lock_vault()` overwrites the bytearray with zeros before deleting it
  (best-effort secure erasure under CPython's memory model).
- Auto-lock after `AUTO_LOCK_MINUTES` of inactivity via background task.
- All secrets are encrypted individually with a unique 96-bit GCM nonce.
- The authentication tag (128-bit) is appended to the ciphertext by the
  `cryptography` library and verified on every decryption.

vault://label convention
------------------------
Tools can reference a secret by writing `vault://my_label` as an argument
value.  The tool_node in nodes.py resolves this to the plaintext before
calling the tool, so the LLM never sees the actual secret.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import time
from functools import lru_cache
from typing import Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Auto-lock after N minutes of inactivity (per user)
AUTO_LOCK_MINUTES: int = 30

# Argon2id parameters — calibrated for ~0.5s on a single core
_ARGON2_TIME_COST   = 3       # iterations
_ARGON2_MEMORY_COST = 65536   # 64 MB
_ARGON2_PARALLELISM = 4       # threads
_ARGON2_HASH_LEN    = 32      # 256-bit → AES-256 key

# M3 (audit 13/06) : valeur sentinelle chiffrée à l'init du vault pour
# vérifier le mot de passe maître même quand le vault est vide. Sa seule
# propriété requise est d'être constante et connue ; AES-GCM rejette déjà
# une mauvaise clé par échec du tag (la comparaison plaintext est une
# ceinture-bretelle). NE PAS modifier : changerait la validation des vaults
# existants.
_VAULT_VERIFIER_PLAINTEXT = "ELY_VAULT_VERIFIER_v1"


# ── Secure erase helper ────────────────────────────────────────────────────────

def _secure_zero(data: bytearray) -> None:
    """Overwrite a bytearray with zeros (mutates in-place)."""
    for i in range(len(data)):
        data[i] = 0


# ── Argon2id key derivation ────────────────────────────────────────────────────

def _derive_key(password: str, salt: bytes) -> bytearray:
    """Derive a 32-byte AES key from the master password using Argon2id.

    Uses argon2-cffi's low-level API for raw hash output (not a password hash
    string — we need raw bytes for AES).
    """
    try:
        from argon2.low_level import hash_secret_raw, Type
        raw = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=_ARGON2_TIME_COST,
            memory_cost=_ARGON2_MEMORY_COST,
            parallelism=_ARGON2_PARALLELISM,
            hash_len=_ARGON2_HASH_LEN,
            type=Type.ID,
        )
        return bytearray(raw)
    except ImportError:
        # Fallback to PBKDF2 if argon2-cffi not available (weaker — log warning)
        import hashlib
        logger.warning("argon2-cffi not available — falling back to PBKDF2-HMAC-SHA256 (weaker)")
        raw = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000, dklen=32)
        return bytearray(raw)


# ── AES-256-GCM helpers ────────────────────────────────────────────────────────

def _encrypt(key: bytearray, plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt *plaintext* → (nonce 12 bytes, ciphertext+tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    aesgcm = AESGCM(bytes(key))
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce, ciphertext


def _decrypt(key: bytearray, nonce: bytes, ciphertext: bytes) -> str:
    """Decrypt *ciphertext* → plaintext string. Raises on bad key / tampered data."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(bytes(key))
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ── VaultService ───────────────────────────────────────────────────────────────

class VaultService:
    """Thread-safe, per-user vault with AES-256-GCM + Argon2id."""

    def __init__(self) -> None:
        # user_id → bytearray key (mutable so we can zero it on lock)
        self._keys: dict[str, bytearray] = {}
        # user_id → last activity timestamp
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lock / unlock                                                        #
    # ------------------------------------------------------------------ #

    def is_locked(self, user_id: str) -> bool:
        return user_id not in self._keys

    async def unlock_vault(self, user_id: str, master_password: str) -> bool:
        """Derive the AES key and store it in RAM.

        Creates a new vault config (with fresh Argon2 salt) if none exists yet.
        Returns True on success, False if the password is wrong (for an existing vault).
        """
        from app.database import async_session
        from app.models.vault import VaultConfig

        async with self._lock:
            async with async_session() as db:
                cfg = await db.get(VaultConfig, user_id)
                is_new = cfg is None
                salt = os.urandom(16) if is_new else cfg.argon2_salt
                # Snapshot du vérificateur avant de quitter la session.
                v_blob = None if is_new else cfg.verifier
                v_nonce = None if is_new else cfg.verifier_nonce

            # Derive key (CPU-bound ~0.5s — run in thread pool)
            key = await asyncio.to_thread(_derive_key, master_password, salt)

            if is_new:
                # M3 (audit 13/06) : poser une sentinelle chiffrée DÈS l'init,
                # pour qu'un vault vide refuse un mauvais mot de passe au
                # prochain unlock (avant : rien à déchiffrer → tout passait).
                n, ct = _encrypt(key, _VAULT_VERIFIER_PLAINTEXT)
                async with async_session() as db:
                    cfg = VaultConfig(user_id=user_id, argon2_salt=salt,
                                      verifier=ct, verifier_nonce=n)
                    db.add(cfg)
                    await db.commit()
                logger.info("Vault initialised for user %s (verifier set)", user_id)
            elif v_blob is not None and v_nonce is not None:
                # Vault avec vérificateur : la vérité, fonctionne même vide.
                try:
                    if _decrypt(key, v_nonce, v_blob) != _VAULT_VERIFIER_PLAINTEXT:
                        raise ValueError("verifier mismatch")
                except Exception:
                    _secure_zero(key)
                    logger.warning("Wrong master password for vault of user %s", user_id)
                    return False
            else:
                # Vault LEGACY (sans vérificateur) : on retombe sur une entrée
                # existante. Un vault legacy VIDE reste non vérifiable (état
                # d'avant le fix) — mais dès qu'on valide le mot de passe, on
                # pose le vérificateur pour fermer le trou définitivement.
                async with async_session() as db:
                    from app.models.vault import VaultEntry
                    test_entry = (await db.execute(
                        select(VaultEntry).where(VaultEntry.user_id == user_id).limit(1)
                    )).scalar_one_or_none()

                if test_entry is not None:
                    try:
                        _decrypt(key, test_entry.nonce, test_entry.encrypted_value)
                    except Exception:
                        _secure_zero(key)
                        logger.warning("Wrong master password for vault of user %s", user_id)
                        return False
                    # Backfill : le mot de passe est validé → poser le
                    # vérificateur pour que les prochains unlocks soient
                    # protégés même si cette entrée est supprimée.
                    try:
                        n, ct = _encrypt(key, _VAULT_VERIFIER_PLAINTEXT)
                        async with async_session() as db:
                            c = await db.get(VaultConfig, user_id)
                            if c is not None:
                                c.verifier, c.verifier_nonce = ct, n
                                await db.commit()
                    except Exception:
                        logger.debug("Vault verifier backfill failed (non-fatal)")

            # Store key in RAM
            if user_id in self._keys:
                _secure_zero(self._keys[user_id])
            self._keys[user_id] = key
            self._last_used[user_id] = time.monotonic()
            logger.info("Vault unlocked for user %s", user_id)
            return True

    async def lock_vault(self, user_id: str) -> None:
        """Securely erase the in-memory key."""
        async with self._lock:
            if user_id in self._keys:
                _secure_zero(self._keys.pop(user_id))
                self._last_used.pop(user_id, None)
                logger.info("Vault locked for user %s", user_id)

    async def auto_lock_expired(self) -> None:
        """Lock all vaults that have been idle for AUTO_LOCK_MINUTES. Called by APScheduler."""
        now = time.monotonic()
        expired = [
            uid for uid, ts in list(self._last_used.items())
            if (now - ts) / 60 >= AUTO_LOCK_MINUTES
        ]
        for uid in expired:
            await self.lock_vault(uid)
            logger.info("Vault auto-locked (idle) for user %s", uid)

    # ------------------------------------------------------------------ #
    # CRUD operations                                                      #
    # ------------------------------------------------------------------ #

    def _require_key(self, user_id: str) -> bytearray:
        if user_id not in self._keys:
            raise PermissionError("Vault is locked — call unlock_vault() first")
        self._last_used[user_id] = time.monotonic()
        return self._keys[user_id]

    async def store_secret(
        self,
        user_id: str,
        label: str,
        value: str,
        hint: Optional[str] = None,
    ) -> None:
        """Encrypt and persist a secret. Creates or replaces the entry for *label*."""
        key = self._require_key(user_id)
        nonce, ciphertext = await asyncio.to_thread(_encrypt, key, value)

        from app.database import async_session
        from app.models.vault import VaultEntry
        from datetime import datetime, timezone

        async with async_session() as db:
            result = await db.execute(
                select(VaultEntry).where(
                    VaultEntry.user_id == user_id,
                    VaultEntry.label == label,
                )
            )
            entry = result.scalar_one_or_none()

            if entry is None:
                entry = VaultEntry(user_id=user_id, label=label)
                db.add(entry)

            entry.hint = hint
            entry.encrypted_value = ciphertext
            entry.nonce = nonce
            entry.updated_at = datetime.now(timezone.utc)
            await db.commit()

        logger.info("Secret '%s' stored for user %s", label, user_id)

    async def get_secret(self, user_id: str, label: str) -> str:
        """Decrypt and return the plaintext value of *label*.

        Raises KeyError if the label does not exist.
        Raises PermissionError if the vault is locked.
        """
        key = self._require_key(user_id)

        from app.database import async_session
        from app.models.vault import VaultEntry

        async with async_session() as db:
            result = await db.execute(
                select(VaultEntry).where(
                    VaultEntry.user_id == user_id,
                    VaultEntry.label == label,
                )
            )
            entry = result.scalar_one_or_none()

        if entry is None:
            raise KeyError(f"No secret with label '{label}' in vault of user {user_id}")

        return await asyncio.to_thread(_decrypt, key, entry.nonce, entry.encrypted_value)

    async def list_secrets(self, user_id: str) -> list[dict]:
        """Return labels and hints (never plaintext values)."""
        # Listing doesn't require unlock — labels/hints are not sensitive
        from app.database import async_session
        from app.models.vault import VaultEntry

        async with async_session() as db:
            result = await db.execute(
                select(VaultEntry).where(VaultEntry.user_id == user_id)
                .order_by(VaultEntry.label)
            )
            entries = result.scalars().all()

        return [
            {
                "label": e.label,
                "hint": e.hint,
                "locked": self.is_locked(user_id),
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in entries
        ]

    async def delete_secret(self, user_id: str, label: str) -> bool:
        """Delete a secret. Returns True if found and deleted."""
        self._require_key(user_id)

        from app.database import async_session
        from app.models.vault import VaultEntry

        async with async_session() as db:
            result = await db.execute(
                select(VaultEntry).where(
                    VaultEntry.user_id == user_id,
                    VaultEntry.label == label,
                )
            )
            entry = result.scalar_one_or_none()
            if entry is None:
                return False
            await db.delete(entry)
            await db.commit()

        logger.info("Secret '%s' deleted for user %s", label, user_id)
        return True

    # ------------------------------------------------------------------ #
    # Password change (re-encrypt all secrets)                            #
    # ------------------------------------------------------------------ #

    async def change_master_password(
        self, user_id: str, old_password: str, new_password: str
    ) -> bool:
        """Re-encrypt all secrets with a new master password.

        Steps:
        1. Verify old password by trying to decrypt a known secret.
        2. Decrypt all secrets with old key.
        3. Generate a fresh Argon2 salt + derive new key.
        4. Re-encrypt all secrets.
        5. Update VaultConfig in DB.
        Returns True on success, False if old_password is wrong.
        """
        from app.database import async_session
        from app.models.vault import VaultConfig, VaultEntry
        from datetime import datetime, timezone

        async with async_session() as db:
            cfg = await db.get(VaultConfig, user_id)
            if cfg is None:
                return False

            old_key = await asyncio.to_thread(_derive_key, old_password, cfg.argon2_salt)

            # Load all entries
            result = await db.execute(
                select(VaultEntry).where(VaultEntry.user_id == user_id)
            )
            entries = result.scalars().all()

        # Verify old password
        if entries:
            try:
                _decrypt(old_key, entries[0].nonce, entries[0].encrypted_value)
            except Exception:
                _secure_zero(old_key)
                return False

        # Decrypt all with old key
        plaintexts: dict[str, str] = {}
        for entry in entries:
            try:
                plaintexts[entry.label] = _decrypt(old_key, entry.nonce, entry.encrypted_value)
            except Exception as exc:
                _secure_zero(old_key)
                raise RuntimeError(f"Failed to decrypt '{entry.label}': {exc}") from exc

        _secure_zero(old_key)

        # New salt + key
        new_salt = os.urandom(16)
        new_key = await asyncio.to_thread(_derive_key, new_password, new_salt)

        # Re-encrypt and persist
        async with async_session() as db:
            cfg = await db.get(VaultConfig, user_id)
            cfg.argon2_salt = new_salt

            result = await db.execute(
                select(VaultEntry).where(VaultEntry.user_id == user_id)
            )
            db_entries = result.scalars().all()

            for entry in db_entries:
                pt = plaintexts.get(entry.label, "")
                nonce, ciphertext = await asyncio.to_thread(_encrypt, new_key, pt)
                entry.nonce = nonce
                entry.encrypted_value = ciphertext
                entry.updated_at = datetime.now(timezone.utc)

            await db.commit()

        # Update in-memory key
        async with self._lock:
            if user_id in self._keys:
                _secure_zero(self._keys[user_id])
            self._keys[user_id] = new_key
            self._last_used[user_id] = time.monotonic()

        logger.info("Master password changed for user %s (%d secrets re-encrypted)",
                    user_id, len(plaintexts))
        return True

    # ------------------------------------------------------------------ #
    # Export (encrypted backup)                                           #
    # ------------------------------------------------------------------ #

    async def export_vault(self, user_id: str) -> dict:
        """Export all secrets as a portable encrypted JSON structure.

        The export is still encrypted — the master password is required to
        import it on another machine.  The salt is included so the recipient
        can derive the same key.
        """
        self._require_key(user_id)

        from app.database import async_session
        from app.models.vault import VaultConfig, VaultEntry
        import base64

        async with async_session() as db:
            cfg = await db.get(VaultConfig, user_id)
            result = await db.execute(
                select(VaultEntry).where(VaultEntry.user_id == user_id)
            )
            entries = result.scalars().all()

        def b64(data: bytes) -> str:
            return base64.b64encode(data).decode()

        return {
            "version": 1,
            "argon2_salt": b64(cfg.argon2_salt),
            "argon2_params": {
                "time_cost": _ARGON2_TIME_COST,
                "memory_cost": _ARGON2_MEMORY_COST,
                "parallelism": _ARGON2_PARALLELISM,
            },
            "secrets": [
                {
                    "label": e.label,
                    "hint": e.hint,
                    "nonce": b64(e.nonce),
                    "ciphertext": b64(e.encrypted_value),
                }
                for e in entries
            ],
        }

    # ------------------------------------------------------------------ #
    # vault:// resolver — used by tool_node                               #
    # ------------------------------------------------------------------ #

    async def resolve_vault_refs(self, user_id: str, args: dict) -> tuple[dict, list[str]]:
        """Scan *args* for values starting with 'vault://' and resolve them.

        Returns (resolved_args, list_of_resolved_labels).
        If the vault is locked and a reference is found, raises PermissionError.
        """
        resolved = {}
        labels_used = []
        for k, v in args.items():
            if isinstance(v, str) and v.startswith("vault://"):
                label = v[len("vault://"):]
                resolved[k] = await self.get_secret(user_id, label)
                labels_used.append(label)
            else:
                resolved[k] = v
        return resolved, labels_used


@lru_cache(maxsize=1)
def get_vault_service() -> VaultService:
    return VaultService()
