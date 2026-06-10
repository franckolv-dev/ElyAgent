# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase3_batch1.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 3 lot 1 — pins :
#             verrou mono-process (A-7), TTL sessions navigateur (B-17),
#             /health/deep, pool Postgres (B-5).
# @license    Elastic License 2.0
# =============================================================================
"""Phase 3 batch 1 pins (revue 2026-06-10)."""
from __future__ import annotations

import types

import pytest


# ─────────────────────────────────────────────────────────────────────────
# A-7 — verrou mono-process
# ─────────────────────────────────────────────────────────────────────────


def test_singleton_lock_blocks_second_holder(tmp_path, monkeypatch) -> None:
    """Deux process sur la même base = HITL split-brain, crons en double,
    create_all en race. Le 2e prétendant doit échouer au boot avec un
    message explicite, pas corrompre en silence."""
    import fcntl

    from app.services import singleton_guard as sg

    monkeypatch.delenv("ELY_ALLOW_MULTIPROCESS", raising=False)
    monkeypatch.setattr(sg, "_lock_path", lambda: tmp_path / "test.lock")

    assert sg.acquire_singleton_lock() is True
    try:
        # Simule un 2e process : flock sur un descripteur distinct.
        rival = open(tmp_path / "test.lock", "a+")
        with pytest.raises(OSError):
            fcntl.flock(rival.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        rival.close()
    finally:
        sg.release_singleton_lock()

    # Après libération, le verrou est reprenables.
    assert sg.acquire_singleton_lock() is True
    sg.release_singleton_lock()


def test_singleton_lock_escape_hatch(tmp_path, monkeypatch) -> None:
    from app.services import singleton_guard as sg

    monkeypatch.setenv("ELY_ALLOW_MULTIPROCESS", "true")
    monkeypatch.setattr(sg, "_lock_path", lambda: tmp_path / "test.lock")
    assert sg.acquire_singleton_lock() is False  # pas de verrou, pas d'erreur


# ─────────────────────────────────────────────────────────────────────────
# B-17 — sessions navigateur : TTL d'inactivité
# ─────────────────────────────────────────────────────────────────────────


class _FakeContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_browser_idle_sessions_are_evicted() -> None:
    """Avant B-17, un user qui touchait un tool browser_* gardait un
    contexte Chromium résident À VIE. L'éviction ferme les inactifs et
    épargne les actifs."""
    import time

    from app.services.browser_manager import BrowserManager, _Session

    bm = BrowserManager()
    idle_ctx, active_ctx = _FakeContext(), _FakeContext()
    bm._sessions["idle_user"] = _Session(
        context=idle_ctx, page=None, last_used=time.monotonic() - 3600,
    )
    bm._sessions["active_user"] = _Session(
        context=active_ctx, page=None, last_used=time.monotonic(),
    )

    closed = await bm.cleanup_idle_sessions(max_idle_seconds=900)

    assert closed == 1
    assert idle_ctx.closed and "idle_user" not in bm._sessions
    assert not active_ctx.closed and "active_user" in bm._sessions
    assert bm.session_count() == 1


# ─────────────────────────────────────────────────────────────────────────
# /health/deep — la sonde voit enfin un backend malade
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_deep_reports_db_ok_and_qdrant_down(monkeypatch) -> None:
    """`/health` superficiel répondait « ok » avec un Qdrant mort. La
    sonde profonde doit renvoyer 503 + le détail booléen."""
    import json

    from app.database import init_db
    from app.routers.health import health_check_deep

    await init_db()  # DB de test joignable → db=True

    class _DeadClient:
        def get_collections(self):
            raise ConnectionError("qdrant down")

    import app.services.memory_manager as mm
    monkeypatch.setattr(
        mm, "get_memory_manager",
        lambda: types.SimpleNamespace(
            _infra=types.SimpleNamespace(client=_DeadClient())
        ),
    )

    resp = await health_check_deep()
    payload = json.loads(resp.body)

    assert resp.status_code == 503
    assert payload["db"] is True
    assert payload["qdrant"] is False
    assert payload["status"] == "degraded"


# ─────────────────────────────────────────────────────────────────────────
# B-5 — pool Postgres dimensionné (pin source-level)
# ─────────────────────────────────────────────────────────────────────────


def test_non_sqlite_engine_pool_is_sized() -> None:
    """Le pool par défaut (5+10) serait le premier goulot invisible après
    une migration Postgres — gels de 30 s aléatoires sous charge."""
    from pathlib import Path

    src = Path("app/database.py").read_text()
    assert "pool_size=20" in src
    assert "max_overflow=30" in src
    assert "pool_pre_ping=True" in src
