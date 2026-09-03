# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/secrets_at_rest.py
# @brief      Chiffrement au repos des secrets d'instance
#             (revue multi-utilisateurs 2026-06-10, constat B-11).
# @license    MIT
# =============================================================================
"""At-rest encryption for install-level secrets.

Le flag ``is_secret`` de ``system_config`` ne faisait QUE masquer l'UI —
le Google client_secret, les clés provider ``api_key_*`` et les
``llm_instances.api_key`` étaient en CLAIR dans SQLite : une fuite du
fichier ``cyberentity.db`` (backup égaré, volume copié) exposait toutes
les clés de l'instance.

Schéma : AES-256-GCM (même primitive que le vault utilisateur), valeurs
préfixées ``enc:gcm:`` + base64(nonce ‖ ciphertext). Le préfixe rend le
déchiffrement auto-descriptif : ``decrypt()`` laisse passer les valeurs
legacy en clair telles quelles (migration paresseuse + un job de boot
chiffre l'existant en une passe).

Clé maître : ``ELY_SECRETS_KEY`` (recommandé en prod) ; à défaut, dérivée
du ``JWT_SECRET_KEY`` via HKDF-SHA256 avec un tag d'usage distinct —
chiffrement par défaut sans configuration, au prix d'un domaine de
compromission partagé avec le JWT (documenté).

À ne pas confondre avec ``vault_service`` : le vault protège les secrets
PAR UTILISATEUR avec une clé dérivée de SON mot de passe (zero-knowledge).
Ici on protège les secrets d'INSTANCE, que le serveur doit pouvoir lire
seul au boot.
"""
from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

_PREFIX = "enc:gcm:"
_NONCE_LEN = 12


@lru_cache(maxsize=1)
def _master_key() -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    from app.config import get_settings

    ikm = os.environ.get("ELY_SECRETS_KEY") or get_settings().jwt_secret_key
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"ely-secrets-at-rest-v1",
    ).derive(ikm.encode("utf-8"))


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """Chiffre ``plaintext``. Idempotent : une valeur déjà chiffrée ou vide
    est retournée telle quelle."""
    if not plaintext or is_encrypted(plaintext):
        return plaintext
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(value: str | None) -> str:
    """Déchiffre une valeur ``enc:gcm:`` ; passe-plat pour le legacy clair.

    Échec de déchiffrement (clé maître changée) → chaîne vide + log CRITIQUE
    plutôt qu'une exception qui empêcherait le boot : le provider concerné
    échouera explicitement à l'usage.
    """
    if not value:
        return ""
    if not is_encrypted(value):
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        blob = base64.b64decode(value[len(_PREFIX):])
        nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
        return AESGCM(_master_key()).decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        logger.critical(
            "secrets_at_rest: déchiffrement impossible — ELY_SECRETS_KEY / "
            "JWT_SECRET_KEY a-t-elle changé ? La valeur est inutilisable."
        )
        return ""
