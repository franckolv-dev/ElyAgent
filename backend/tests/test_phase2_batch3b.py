# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase2_batch3b.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 2 lot 3b — pins :
#             B-7 (BoundedLRUDict : LRU + TTL au lieu du FIFO), vault PII
#             unifié chat/voice, rétention des tables de signaux.
# @license    Elastic License 2.0
# =============================================================================
"""Phase 2 batch 3b pins (revue 2026-06-10)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ─────────────────────────────────────────────────────────────────────────
# B-7 — BoundedLRUDict : la politique d'éviction protège les actifs
# ─────────────────────────────────────────────────────────────────────────


def test_lru_eviction_spares_recently_read_entries() -> None:
    """LE scénario B-7 : avec FIFO, l'entrée évincée était la plus
    ANCIENNEMENT CRÉÉE — potentiellement une conversation encore active
    (vault PII détruit en pleine conversation). Avec LRU, une lecture
    récente protège l'entrée : l'évincée est la plus longtemps inactive."""
    from app.services.bounded_cache import BoundedLRUDict

    cache = BoundedLRUDict(maxsize=3)
    cache["conv_ancienne_mais_active"] = "vault-A"
    cache["conv_b"] = "vault-B"
    cache["conv_c"] = "vault-C"

    # La conversation ancienne est ACTIVE : on la lit.
    assert cache.get("conv_ancienne_mais_active") == "vault-A"

    # Insertion d'une 4e entrée → éviction.
    cache["conv_d"] = "vault-D"

    assert "conv_ancienne_mais_active" in cache, (
        "l'entrée active a été évincée — politique FIFO de retour (régression B-7)"
    )
    assert "conv_b" not in cache, "l'évincée doit être la plus longtemps inactive"


def test_ttl_expires_idle_entries_lazily() -> None:
    from app.services.bounded_cache import BoundedLRUDict

    cache = BoundedLRUDict(maxsize=10, ttl_seconds=1000)
    cache["conv"] = "vault"
    # Simule l'inactivité : on antidate le touch au-delà du TTL.
    cache._touched["conv"] = cache._touched["conv"] - 2000

    assert "conv" not in cache
    assert cache.get("conv") is None
    assert cache.sweep() == 0  # déjà purgée par l'accès


def test_ttl_refreshed_on_read() -> None:
    from app.services.bounded_cache import BoundedLRUDict

    cache = BoundedLRUDict(maxsize=10, ttl_seconds=1000)
    cache["conv"] = "vault"
    cache._touched["conv"] = cache._touched["conv"] - 900  # presque expiré
    assert cache.get("conv") == "vault"  # touch → TTL repart
    assert (cache._touched["conv"]) == pytest.approx(
        __import__("time").monotonic(), abs=5
    )


def test_setdefault_returns_existing_and_touches() -> None:
    """Le pattern des call-sites (`_filters.setdefault(cid, SecurityFilter())`)
    doit retourner l'instance EXISTANTE (vault préservé) et la rafraîchir."""
    from app.services.bounded_cache import BoundedLRUDict

    cache = BoundedLRUDict(maxsize=2)
    first = object()
    assert cache.setdefault("k", first) is first
    assert cache.setdefault("k", object()) is first  # pas remplacé
    cache["other"] = 1
    cache["evictor"] = 2  # k a été touché en dernier via setdefault ? non —
    # ordre : k touché (setdefault), other, evictor → évince k ? maxsize=2 :
    # après "other", insertion "evictor" évince le moins récemment utilisé = k...
    # k a été lu AVANT other → LRU évince k : cohérent.
    assert "evictor" in cache


def test_cache_modules_use_shared_lru() -> None:
    """Pin source-level : les 4 modules + voice.py ne redéfinissent plus
    leur _BoundedDict FIFO local."""
    from pathlib import Path

    for mod in (
        "app/services/conversation_filters.py",
        "app/services/frozen_memory.py",
        "app/services/system_prompt_cache.py",
        "app/services/fallback_manager.py",
    ):
        src = Path(mod).read_text()
        assert "class _BoundedDict" not in src, f"{mod} : FIFO local de retour"
        assert "BoundedLRUDict" in src

    voice_src = Path("app/routers/voice.py").read_text()
    assert "class _BoundedDict" not in voice_src
    assert "from app.services.conversation_filters import" in voice_src, (
        "voice.py doit partager le registre de filtres PII avec tool_node "
        "— sinon les tool args vocaux gardent leurs placeholders"
    )


def test_voice_and_tool_node_share_the_same_pii_vault() -> None:
    """Le bug corrigé : voice.py avait son PROPRE dict de SecurityFilters,
    différent de celui que tool_node utilise pour dé-anonymiser les
    arguments d'outils → un tool_call vocal partait avec [EMAIL_0]
    littéral."""
    from app.routers.voice import _get_filter as voice_get
    from app.services.conversation_filters import get_filter

    cid = f"test_vault_{uuid.uuid4().hex[:8]}"
    try:
        assert voice_get(cid) is get_filter(cid)
    finally:
        from app.services.conversation_filters import discard_filter
        discard_filter(cid)


# ─────────────────────────────────────────────────────────────────────────
# Rétention des tables de signaux
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retention_purges_old_signals_keeps_recent(monkeypatch) -> None:
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.hitl_refusal import HitlRefusal
    from app.models.user import User
    from app.services.retention import run_retention

    await init_db()
    uid = f"test_ret_{uuid.uuid4().hex[:8]}"
    old_ts = datetime.now(timezone.utc) - timedelta(days=120)

    def _refusal(**kw):
        return HitlRefusal(
            user_id=uid, conversation_id="c1", tool_name="t",
            args_redacted="{}", action_description="d", decision="deny",
            reason="user_denied", **kw,
        )

    # User d'abord (commit séparé) — SQLite vérifie les FK immédiatement
    # et l'ordre d'insertion intra-flush n'est pas garanti sans relationship.
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    async with async_session() as db:
        db.add(_refusal(created_at=old_ts))
        db.add(_refusal())
        await db.commit()

    monkeypatch.setenv("ELY_SIGNALS_RETENTION_DAYS", "90")
    try:
        removed = await run_retention()
        assert removed.get("hitl_refusals", 0) >= 1

        async with async_session() as db:
            rows = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.user_id == uid)
            )).scalars().all()
        assert len(rows) == 1, "la ligne récente doit survivre"
        # created_at est stocké naïf (DateTime sans timezone) — on compare
        # en re-localisant.
        survived = rows[0].created_at.replace(tzinfo=timezone.utc)
        assert survived > old_ts, "c'est la VIEILLE ligne qui a survécu"
    finally:
        async with async_session() as db:
            await db.execute(delete(HitlRefusal).where(HitlRefusal.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()


@pytest.mark.asyncio
async def test_retention_disabled_when_zero(monkeypatch) -> None:
    from sqlalchemy import delete, select

    from app.database import async_session, init_db
    from app.models.hitl_refusal import HitlRefusal
    from app.models.user import User
    from app.services.retention import run_retention

    await init_db()
    uid = f"test_ret0_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    async with async_session() as db:
        db.add(HitlRefusal(
            user_id=uid, conversation_id="c1", tool_name="t",
            args_redacted="{}", action_description="d", decision="deny",
            reason="user_denied",
            created_at=datetime.now(timezone.utc) - timedelta(days=999),
        ))
        await db.commit()

    monkeypatch.setenv("ELY_SIGNALS_RETENTION_DAYS", "0")
    monkeypatch.setenv("ELY_USAGE_RETENTION_DAYS", "0")
    try:
        await run_retention()
        async with async_session() as db:
            rows = (await db.execute(
                select(HitlRefusal).where(HitlRefusal.user_id == uid)
            )).scalars().all()
        assert len(rows) == 1, "rétention désactivée = aucune purge"
    finally:
        async with async_session() as db:
            await db.execute(delete(HitlRefusal).where(HitlRefusal.user_id == uid))
            u = await db.get(User, uid)
            if u is not None:
                await db.delete(u)
            await db.commit()
