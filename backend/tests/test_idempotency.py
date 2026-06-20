# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_idempotency.py
# @brief      P1/J3 — store d'idempotence (« jamais deux fois par accident »).
# @license    Elastic License 2.0
# =============================================================================
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.idempotency_store import (
    check_idempotent,
    lookup,
    record,
    remember,
)


@pytest_asyncio.fixture
async def db_ready():
    from app.database import init_db
    await init_db()


async def _cleanup(key: str):
    from app.database import async_session
    from app.models.idempotency import IdempotencyRecord
    async with async_session() as db:
        rec = await db.get(IdempotencyRecord, key)
        if rec:
            await db.delete(rec)
            await db.commit()


# ── Store brut ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_then_lookup(db_ready):
    key = f"k_{uuid.uuid4().hex}"
    try:
        await record(key, "u1", "web_search", "résultat météo", ttl_seconds=600)
        assert await lookup(key) == "résultat météo"
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_lookup_unknown_is_none(db_ready):
    assert await lookup(f"absent_{uuid.uuid4().hex}") is None


@pytest.mark.asyncio
async def test_expired_record_is_purged(db_ready):
    key = f"k_{uuid.uuid4().hex}"
    try:
        await record(key, "u1", "web_search", "vieux", ttl_seconds=-5)  # déjà expiré
        assert await lookup(key) is None   # expiré → None (et purgé)
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_result_is_bounded(db_ready):
    key = f"k_{uuid.uuid4().hex}"
    try:
        await record(key, "u1", "web_search", "x" * 50_000, ttl_seconds=600)
        cached = await lookup(key)
        assert cached is not None and len(cached) <= 16 * 1024
    finally:
        await _cleanup(key)


# ── Garde pilotée par le manifeste ───────────────────────────────────────


@pytest.mark.asyncio
async def test_supported_tool_is_deduped(db_ready):
    # web_search → idempotency: supported
    key = f"k_{uuid.uuid4().hex}"
    try:
        await remember("web_search", key, "u1", "résultat A")
        assert await check_idempotent("web_search", key) == "résultat A"
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_non_idempotent_tool_is_never_deduped(db_ready):
    # gmail_send_email → idempotency: none → remember() n'enregistre pas, et
    # check_idempotent() ne court-circuite jamais (même si une clé existait).
    key = f"k_{uuid.uuid4().hex}"
    try:
        await remember("gmail_send_email", key, "u1", "envoyé")
        assert await lookup(key) is None              # rien enregistré
        # même si on force un enregistrement sous cette clé…
        await record(key, "u1", "gmail_send_email", "envoyé", ttl_seconds=600)
        assert await check_idempotent("gmail_send_email", key) is None  # …pas de court-circuit
    finally:
        await _cleanup(key)


@pytest.mark.asyncio
async def test_check_returns_none_without_fingerprint(db_ready):
    assert await check_idempotent("web_search", "") is None


# ── Bout-en-bout avec l'empreinte du plan (J2) ───────────────────────────


@pytest.mark.asyncio
async def test_roundtrip_with_action_fingerprint(db_ready):
    from app.services.action_plan import build_action_plan, fingerprint

    fp = fingerprint(build_action_plan("web_search", {"query": "météo Paris"}, "u1"))
    try:
        assert await check_idempotent("web_search", fp) is None   # rien encore
        await remember("web_search", fp, "u1", "21°C ensoleillé")
        assert await check_idempotent("web_search", fp) == "21°C ensoleillé"  # 2e fois → mémorisé
    finally:
        await _cleanup(fp)
