# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase1_batch2.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 1 lot 2 — pins :
#             B-1 (lazy-load LLM non bloquant), A-5 (porte de concurrence
#             LLM local au niveau transport httpx).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Phase 1 batch 2 pins (revue 2026-06-10)."""
from __future__ import annotations

import asyncio
import time

import pytest


# ─────────────────────────────────────────────────────────────────────────
# A-5 — porte de concurrence LLM local (httpx limits partagées)
# ─────────────────────────────────────────────────────────────────────────


def test_local_async_client_shared_per_base_url(monkeypatch) -> None:
    from app.services import llm_provider as lp

    lp._LOCAL_HTTPX_CLIENTS.clear()
    monkeypatch.delenv("LOCAL_LLM_MAX_CONCURRENCY", raising=False)

    a1 = lp._local_llm_async_client("http://localhost:1234/v1")
    a2 = lp._local_llm_async_client("http://localhost:1234/v1")
    b = lp._local_llm_async_client("http://localhost:1235/v1")

    assert a1 is a2, "le client doit être PARTAGÉ par base_url (sinon pas de borne)"
    assert a1 is not b


def test_local_async_client_bounded_to_one_connection(monkeypatch) -> None:
    """max_connections=1 par défaut : c'est la réalité du serveur MLX
    mono-requête. La 2ᵉ requête attend une connexion du pool côté client
    au lieu de s'empiler côté LM Studio (prompt processing payé à vide)."""
    from app.services import llm_provider as lp

    lp._LOCAL_HTTPX_CLIENTS.clear()
    monkeypatch.delenv("LOCAL_LLM_MAX_CONCURRENCY", raising=False)

    client = lp._local_llm_async_client("http://localhost:1234/v1")
    pool = client._transport._pool
    assert pool._max_connections == 1


def test_local_concurrency_env_override(monkeypatch) -> None:
    from app.services import llm_provider as lp

    lp._LOCAL_HTTPX_CLIENTS.clear()
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "2")
    client = lp._local_llm_async_client("http://localhost:9999/v1")
    assert client._transport._pool._max_connections == 2
    lp._LOCAL_HTTPX_CLIENTS.clear()


def test_lm_studio_llm_uses_shared_gated_client(monkeypatch) -> None:
    from app.services import llm_provider as lp

    lp._LOCAL_HTTPX_CLIENTS.clear()
    monkeypatch.delenv("LOCAL_LLM_MAX_CONCURRENCY", raising=False)

    url = "http://localhost:1234/v1"
    llm = lp._make_lm_studio(model="gemma-test", base_url=url)
    assert llm.http_async_client is lp._local_llm_async_client(url), (
        "ChatOpenAI LM Studio doit porter le client httpx partagé/borné — "
        "sinon la porte A-5 est contournée"
    )


# ─────────────────────────────────────────────────────────────────────────
# B-1 — get_llm_for_tier ne bloque plus l'event loop au cold start
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_start_lazy_load_does_not_block_event_loop(monkeypatch) -> None:
    """Avant B-1 : cache froid + loop active → `fut.result(timeout=10)`
    gelait TOUTE l'application jusqu'à 10 s. Désormais le chargement part
    en tâche de fond et l'appel rend la main immédiatement (défauts pour
    ce tour)."""
    from app.services import llm_provider as lp
    from app.services.llm_provider import ComplexityTier

    load_started = asyncio.Event()
    load_release = asyncio.Event()

    async def slow_loader():
        load_started.set()
        await load_release.wait()  # simule une DB lente — l'ancien code
        # aurait bloqué la loop dessus

    monkeypatch.setattr(lp, "load_llm_settings_from_db", slow_loader)
    monkeypatch.setattr(lp, "_instance_cache", {})
    monkeypatch.setattr(lp, "_runtime", {})
    monkeypatch.setattr(lp, "_lazy_settings_task", None)

    t0 = time.monotonic()
    llm = lp.get_llm_for_tier(ComplexityTier.SIMPLE)
    elapsed = time.monotonic() - t0

    try:
        assert llm is not None
        assert elapsed < 2.0, (
            f"get_llm_for_tier a mis {elapsed:.1f}s avec un loader lent — "
            "l'event loop est à nouveau bloqué (régression B-1)"
        )
        # Le chargement a bien été PROGRAMMÉ (pas oublié) :
        await asyncio.wait_for(load_started.wait(), timeout=2)
    finally:
        load_release.set()
        if lp._lazy_settings_task is not None:
            await lp._lazy_settings_task
