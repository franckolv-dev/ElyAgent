# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase3_batch2.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 3 lot 2 — pins :
#             B-11 (secrets chiffrés au repos) + B-12 (outils d'instance
#             réservés au rôle admin).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Phase 3 batch 2 pins (revue 2026-06-10)."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# B-11 — primitives de chiffrement
# ─────────────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip() -> None:
    from app.services.secrets_at_rest import decrypt, encrypt, is_encrypted

    secret = "sk-very-secret-api-key-123"
    stored = encrypt(secret)

    assert stored != secret
    assert is_encrypted(stored)
    assert secret not in stored, "le clair ne doit jamais apparaître dans le stocké"
    assert decrypt(stored) == secret


def test_decrypt_passes_legacy_plaintext_through() -> None:
    """Migration paresseuse : les valeurs legacy en clair restent lisibles."""
    from app.services.secrets_at_rest import decrypt

    assert decrypt("sk-legacy-plaintext") == "sk-legacy-plaintext"
    assert decrypt("") == ""
    assert decrypt(None) == ""


def test_encrypt_is_idempotent() -> None:
    from app.services.secrets_at_rest import decrypt, encrypt

    once = encrypt("valeur")
    twice = encrypt(once)
    assert once == twice, "re-chiffrer une valeur chiffrée la corromprait"
    assert decrypt(twice) == "valeur"


def test_decrypt_with_wrong_key_fails_closed(monkeypatch) -> None:
    """Clé maître changée → chaîne vide + log critique, jamais d'exception
    (le boot ne doit pas mourir sur un secret illisible)."""
    from app.services import secrets_at_rest as sar

    stored = sar.encrypt("secret")
    monkeypatch.setenv("ELY_SECRETS_KEY", "une-toute-autre-cle-maitre-32chars")
    sar._master_key.cache_clear()
    try:
        assert sar.decrypt(stored) == ""
    finally:
        monkeypatch.delenv("ELY_SECRETS_KEY")
        sar._master_key.cache_clear()


# ─────────────────────────────────────────────────────────────────────────
# B-11 — system_config : chiffré au repos, clair à la lecture
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_config_encrypted_at_rest() -> None:
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.system_config import SystemConfig
    from app.services.system_config import delete_config, get_config, set_config

    await init_db()
    key = f"test_secret_{uuid.uuid4().hex[:8]}"
    try:
        await set_config(key, "mon-client-secret", is_secret=True)

        # En base : chiffré (le flag is_secret ne fait plus que masquer l'UI)
        async with async_session() as db:
            raw = (await db.execute(
                select(SystemConfig.value).where(SystemConfig.key == key)
            )).scalar_one()
        assert raw.startswith("enc:gcm:")
        assert "mon-client-secret" not in raw

        # À la lecture applicative : clair
        assert await get_config(key) == "mon-client-secret"
    finally:
        await delete_config(key)


@pytest.mark.asyncio
async def test_non_secret_config_stays_plaintext() -> None:
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.system_config import SystemConfig
    from app.services.system_config import delete_config, set_config

    await init_db()
    key = f"test_plain_{uuid.uuid4().hex[:8]}"
    try:
        await set_config(key, "valeur-publique", is_secret=False)
        async with async_session() as db:
            raw = (await db.execute(
                select(SystemConfig.value).where(SystemConfig.key == key)
            )).scalar_one()
        assert raw == "valeur-publique"
    finally:
        await delete_config(key)


@pytest.mark.asyncio
async def test_boot_migration_encrypts_legacy_plaintext() -> None:
    """Les installs existantes ont des secrets en clair : la migration de
    boot les chiffre en une passe, idempotente."""
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.llm_instance import LLMInstance
    from app.models.system_config import SystemConfig
    from app.services.system_config import migrate_plaintext_secrets

    await init_db()
    cfg_key = f"test_mig_{uuid.uuid4().hex[:8]}"
    inst_id = str(uuid.uuid4())
    try:
        # Plante des valeurs EN CLAIR directement (état legacy pré-B-11)
        async with async_session() as db:
            db.add(SystemConfig(
                key=cfg_key, value="legacy-secret", is_secret=True,
                description="t",
            ))
            db.add(LLMInstance(
                id=inst_id, label="t", provider="deepseek", model="m",
                api_key="sk-legacy-key",
            ))
            await db.commit()

        migrated = await migrate_plaintext_secrets()
        assert migrated >= 2

        async with async_session() as db:
            raw_cfg = (await db.execute(
                select(SystemConfig.value).where(SystemConfig.key == cfg_key)
            )).scalar_one()
            raw_key = (await db.execute(
                select(LLMInstance.api_key).where(LLMInstance.id == inst_id)
            )).scalar_one()
        assert raw_cfg.startswith("enc:gcm:")
        assert raw_key.startswith("enc:gcm:")

        # Idempotence : un 2e passage ne migre rien
        assert await migrate_plaintext_secrets() == 0
    finally:
        async with async_session() as db:
            await db.execute(delete(SystemConfig).where(SystemConfig.key == cfg_key))
            await db.execute(delete(LLMInstance).where(LLMInstance.id == inst_id))
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# B-12 — outils d'instance réservés au rôle admin
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_and_user():
    from app.database import async_session, init_db
    from app.models.user import User

    await init_db()
    suffix = uuid.uuid4().hex[:8]
    admin_id, user_id = f"test_acl_a_{suffix}", f"test_acl_u_{suffix}"
    async with async_session() as db:
        db.add(User(
            id=admin_id, username=f"adm_{suffix}", email=f"a{suffix}@bench.local",
            hashed_password="x", role="admin",
        ))
        db.add(User(
            id=user_id, username=f"usr_{suffix}", email=f"u{suffix}@bench.local",
            hashed_password="x", role="user",
        ))
        await db.commit()
    yield admin_id, user_id
    from app.services.tool_acl import invalidate_role_cache
    invalidate_role_cache()
    async with async_session() as db:
        for uid in (admin_id, user_id):
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
        await db.commit()


def test_requires_admin_covers_ssh_not_mcp(monkeypatch) -> None:
    """J4 — les outils MCP ne sont plus admin-only EN BLOC : ils passent par
    l'ACL fine ``mcp_acl`` (propriété + permission par outil), via
    ``check_tool_access``, pas par ``requires_admin``. Ce dernier ne couvre
    plus que les ressources d'instance non-MCP (hôtes SSH)."""
    from app.services.tool_acl import requires_admin

    assert requires_admin("ssh_execute") is True
    assert requires_admin("gmail_send_email") is False
    # Un outil MCP namespacé n'est plus géré par requires_admin.
    assert requires_admin("mcp__some_srv__fetch_url") is False


@pytest.mark.asyncio
async def test_non_admin_blocked_on_instance_tools(admin_and_user) -> None:
    """Avant B-12, tout utilisateur routé sur le domaine infra exécutait
    les commandes SSH whitelistées AVEC LES CLÉS DE L'ADMIN."""
    from app.services.tool_acl import check_tool_access, invalidate_role_cache

    admin_id, user_id = admin_and_user
    invalidate_role_cache()

    refusal = await check_tool_access(user_id, "ssh_execute")
    assert refusal is not None and "admin" in refusal

    assert await check_tool_access(admin_id, "ssh_execute") is None
    # Les outils normaux passent pour tout le monde
    assert await check_tool_access(user_id, "gmail_send_email") is None


@pytest.mark.asyncio
async def test_unknown_user_fails_closed() -> None:
    from app.services.tool_acl import check_tool_access, invalidate_role_cache

    invalidate_role_cache()
    refusal = await check_tool_access("no-such-user", "ssh_execute")
    assert refusal is not None, "un user inconnu ne doit JAMAIS hériter du privilège"
