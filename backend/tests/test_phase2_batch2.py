# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase2_batch2.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 2 lot 2 — pins :
#             A-6a (rate limit branché), B-15 (cap runs/user),
#             B-3 (heartbeat missions équitable et non bloquant).
# @license    MIT
# =============================================================================
"""Phase 2 batch 2 pins (revue 2026-06-10)."""
from __future__ import annotations

import asyncio
import types

import pytest


# ─────────────────────────────────────────────────────────────────────────
# A-6a — le RATE_LIMIT de la config est enfin branché
# ─────────────────────────────────────────────────────────────────────────


def test_default_limits_parses_rate_limit_setting(monkeypatch) -> None:
    from app.middleware import rate_limit as rl

    monkeypatch.setattr(
        rl, "get_settings",
        lambda: types.SimpleNamespace(rate_limit="120/minute, 2000/hour"),
    )
    assert rl._default_limits() == ["120/minute", "2000/hour"]

    monkeypatch.setattr(
        rl, "get_settings", lambda: types.SimpleNamespace(rate_limit=""),
    )
    assert rl._default_limits() == []


def test_limiter_has_default_limits_wired() -> None:
    """Avant A-6a le Limiter était construit SANS default_limits : la
    config RATE_LIMIT (compose + settings) était morte et tout sauf 3
    endpoints d'auth était illimité."""
    from app.middleware.rate_limit import limiter

    assert limiter._default_limits, (
        "Limiter sans default_limits — la config RATE_LIMIT est de "
        "nouveau lettre morte (régression A-6a)"
    )


def test_rate_limit_enforced_and_health_exempt(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.middleware.rate_limit import limiter, setup_rate_limiter
    from app.routers import health as health_router

    app = FastAPI()
    setup_rate_limiter(app)
    app.include_router(health_router.router)

    @app.get("/limited")
    async def limited():
        return {"ok": True}

    client = TestClient(app)
    limiter.reset()
    try:
        # Le défaut configuré est 60/minute : la 61ᵉ doit prendre 429.
        statuses = [client.get("/limited").status_code for _ in range(61)]
        assert statuses[:60] == [200] * 60
        assert statuses[60] == 429, "la limite globale ne s'applique pas"

        # /health est exempté — sondé par le healthcheck Docker, un 429
        # ferait flapper le conteneur.
        health_statuses = {client.get("/health").status_code for _ in range(70)}
        assert health_statuses == {200}
    finally:
        limiter.reset()


# ─────────────────────────────────────────────────────────────────────────
# B-15 — cap de runs agent concurrents par user
# ─────────────────────────────────────────────────────────────────────────


def test_run_gate_semaphore_per_user(monkeypatch) -> None:
    from app.services import run_gate

    monkeypatch.setattr(run_gate, "_semaphores", {})

    sem_a = run_gate.get_user_run_semaphore("alice")
    sem_a2 = run_gate.get_user_run_semaphore("alice")
    sem_b = run_gate.get_user_run_semaphore("bob")

    assert sem_a is sem_a2, "même user → même sémaphore (sinon pas de cap)"
    assert sem_a is not sem_b, "le cap est PAR user — bob ne partage pas le slot d'alice"


@pytest.mark.asyncio
async def test_run_gate_bounds_concurrent_runs(monkeypatch) -> None:
    from app.services import run_gate

    monkeypatch.setattr(run_gate, "_semaphores", {})
    monkeypatch.setattr(run_gate, "MAX_RUNS_PER_USER", 2)

    sem = run_gate.get_user_run_semaphore("alice")
    await sem.acquire()
    await sem.acquire()
    assert sem.locked(), "le 3ᵉ run du même user doit attendre"
    sem.release()
    sem.release()


# ─────────────────────────────────────────────────────────────────────────
# B-3 — heartbeat missions : équité et dispatch non bloquant
# ─────────────────────────────────────────────────────────────────────────


def _mission(mid: str, user_id: str):
    return types.SimpleNamespace(
        id=mid, user_id=user_id, goal=f"goal-{mid}", status="running",
        tick_interval_seconds=60, title=f"m-{mid}", source="api", source_ref=None,
    )


def test_interleave_by_user_round_robin() -> None:
    """Sans round-robin, un user avec 5 missions dues monopolise le quota
    du beat (MAX_MISSIONS_PER_BEAT=5) et affame tous les autres."""
    from app.services.mission_heartbeat import _interleave_by_user

    missions = [
        _mission("a1", "alice"), _mission("a2", "alice"),
        _mission("a3", "alice"), _mission("b1", "bob"),
        _mission("c1", "carol"),
    ]
    ordered = [m.id for m in _interleave_by_user(missions)]
    assert ordered == ["a1", "b1", "c1", "a2", "a3"]


@pytest.mark.asyncio
async def test_heartbeat_dispatches_without_awaiting_ticks(monkeypatch) -> None:
    """Le beat doit rendre la main immédiatement : un tick lent (3 min
    avant B-3) ne bloque ni les autres missions ni les beats suivants."""
    import time

    from app.services import mission_heartbeat as hb
    from app.services import mission_service

    started: list[str] = []
    release = asyncio.Event()

    async def fake_process(mission):
        started.append(mission.id)
        try:
            await release.wait()  # tick volontairement interminable
        finally:
            hb._in_flight.discard(mission.id)

    async def fake_due():
        return [_mission("m1", "alice"), _mission("m2", "bob")]

    monkeypatch.setattr(mission_service, "list_due_missions", fake_due)
    monkeypatch.setattr(hb, "_process_one_mission", fake_process)
    hb._in_flight.clear()

    t0 = time.monotonic()
    await hb.heartbeat_tick()
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"le beat a attendu les ticks ({elapsed:.1f}s) — régression B-3"
    await asyncio.sleep(0.05)
    assert sorted(started) == ["m1", "m2"]

    # Beat suivant pendant que les ticks tournent encore : les missions en
    # vol sont SAUTÉES (pas de double tick), pas re-dispatchées.
    await hb.heartbeat_tick()
    await asyncio.sleep(0.05)
    assert sorted(started) == ["m1", "m2"], "double tick d'une mission en vol"

    release.set()
    await asyncio.sleep(0.05)
    assert not hb._in_flight, "les entrées _in_flight doivent être libérées"


@pytest.mark.asyncio
async def test_heartbeat_fairness_across_users(monkeypatch) -> None:
    """5 missions d'alice + 1 de bob, quota 5 par beat : bob doit passer
    dans CE beat (avant B-3 il attendait que les 5 d'alice soient faites)."""
    from app.services import mission_heartbeat as hb
    from app.services import mission_service

    dispatched: list[str] = []

    async def fake_process(mission):
        dispatched.append(f"{mission.user_id}:{mission.id}")
        hb._in_flight.discard(mission.id)

    async def fake_due():
        return [
            _mission("a1", "alice"), _mission("a2", "alice"),
            _mission("a3", "alice"), _mission("a4", "alice"),
            _mission("a5", "alice"), _mission("b1", "bob"),
        ]

    monkeypatch.setattr(mission_service, "list_due_missions", fake_due)
    monkeypatch.setattr(hb, "_process_one_mission", fake_process)
    monkeypatch.setattr(hb, "MAX_MISSIONS_PER_BEAT", 5)
    hb._in_flight.clear()

    await hb.heartbeat_tick()
    await asyncio.sleep(0.05)

    assert "bob:b1" in dispatched, (
        "la mission de bob est affamée par les 5 missions d'alice — "
        "régression B-3 (équité round-robin)"
    )
