# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase1_batch1.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 1 lot 1 — pins :
#             B-6 (ws_registry multi-sockets), B-8 (dédup webhook Telegram),
#             spawn() à références fortes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Phase 1 batch 1 pins (revue 2026-06-10)."""
from __future__ import annotations

import asyncio
import logging

import pytest


# ─────────────────────────────────────────────────────────────────────────
# B-6 — ws_registry : multi-sockets par user + bug des deux onglets
# ─────────────────────────────────────────────────────────────────────────


class _FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[str] = []
        self._fail = fail

    async def send_text(self, text: str) -> None:
        if self._fail:
            raise RuntimeError("socket closed")
        self.sent.append(text)


@pytest.fixture(autouse=True)
def _clean_registry():
    from app.services import ws_registry

    ws_registry._registry.clear()
    yield
    ws_registry._registry.clear()


def test_second_connection_does_not_replace_first() -> None:
    from app.services import ws_registry

    a, b = _FakeWS(), _FakeWS()
    ws_registry.register("u1", a)  # type: ignore[arg-type]
    ws_registry.register("u1", b)  # type: ignore[arg-type]
    assert set(ws_registry.get_all("u1")) == {a, b}


def test_closing_old_tab_keeps_new_tab_registered() -> None:
    """LE bug d'origine : onglet A se connecte, onglet B se connecte
    (remplaçait A), onglet A se ferme → l'ancien code faisait
    ``pop(user_id)`` et désinscrivait LA SOCKET DE B. L'utilisateur
    restait connecté mais injoignable (HITL, tâches planifiées)."""
    from app.services import ws_registry

    tab_a, tab_b = _FakeWS(), _FakeWS()
    ws_registry.register("u1", tab_a)  # type: ignore[arg-type]
    ws_registry.register("u1", tab_b)  # type: ignore[arg-type]

    ws_registry.unregister("u1", tab_a)  # type: ignore[arg-type]

    assert ws_registry.get_all("u1") == [tab_b], (
        "fermer l'onglet A a désinscrit l'onglet B — régression B-6"
    )


@pytest.mark.asyncio
async def test_send_text_all_fans_out_and_prunes_dead_sockets() -> None:
    from app.services import ws_registry

    ok1, dead, ok2 = _FakeWS(), _FakeWS(fail=True), _FakeWS()
    for ws in (ok1, dead, ok2):
        ws_registry.register("u1", ws)  # type: ignore[arg-type]

    delivered = await ws_registry.send_text_all("u1", "hello")

    assert delivered == 2
    assert ok1.sent == ["hello"] and ok2.sent == ["hello"]
    # La socket morte a été purgée — elle ne bloquera plus les suivants.
    assert dead not in ws_registry.get_all("u1")


# ─────────────────────────────────────────────────────────────────────────
# spawn() — références fortes + log des exceptions
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spawn_completes_and_releases_reference() -> None:
    from app.services.background_tasks import pending_count, spawn

    done = asyncio.Event()

    async def work():
        done.set()

    task = spawn(work())
    await asyncio.wait_for(done.wait(), timeout=2)
    await task
    await asyncio.sleep(0)  # le done-callback passe par call_soon → un tick
    assert pending_count() == 0


@pytest.mark.asyncio
async def test_spawn_logs_exception_instead_of_swallowing(caplog) -> None:
    from app.services.background_tasks import spawn

    async def boom():
        raise ValueError("kaboom")

    with caplog.at_level(logging.WARNING, logger="app.services.background_tasks"):
        task = spawn(boom(), label="test-boom")
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)  # laisse le done-callback tourner

    assert any("test-boom" in r.message for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────
# B-8 — webhook Telegram : dédup par update_id, traitement hors requête
# ─────────────────────────────────────────────────────────────────────────


class _StubBotApp:
    def __init__(self):
        self.bot = None  # Update.de_json accepte n'importe quel bot
        self.processed: list = []

    async def process_update(self, update) -> None:
        self.processed.append(update.update_id)


@pytest.mark.asyncio
async def test_duplicate_telegram_update_processed_once(monkeypatch) -> None:
    """Telegram REJOUE un update quand le webhook répond trop tard. Avant
    B-8 le run agent tournait inline (> 60 s) → la réponse partait après
    le timeout Telegram → le même message déclenchait l'agent 2-3 fois
    (actions et coûts dupliqués)."""
    from app.channels import telegram_bot as tb

    stub = _StubBotApp()
    monkeypatch.setattr(tb, "_bot_app", stub)
    tb._SEEN_UPDATE_IDS.clear()

    payload = {"update_id": 4242}
    await tb.receive_telegram_update(payload)
    await tb.receive_telegram_update(payload)  # replay Telegram
    await asyncio.sleep(0.05)  # laisse la tâche de fond tourner

    assert stub.processed == [4242], (
        f"update rejoué traité {len(stub.processed)} fois — régression B-8"
    )


@pytest.mark.asyncio
async def test_telegram_update_returns_before_processing(monkeypatch) -> None:
    """La route doit pouvoir répondre 200 IMMÉDIATEMENT : le traitement
    part en tâche de fond, receive_telegram_update ne l'attend pas."""
    from app.channels import telegram_bot as tb

    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowBotApp(_StubBotApp):
        async def process_update(self, update) -> None:
            started.set()
            await release.wait()  # simule un run agent long
            self.processed.append(update.update_id)

    stub = _SlowBotApp()
    monkeypatch.setattr(tb, "_bot_app", stub)
    tb._SEEN_UPDATE_IDS.clear()

    # Si le traitement était inline, ce wait_for timeouterait.
    await asyncio.wait_for(
        tb.receive_telegram_update({"update_id": 1}), timeout=1.0,
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert stub.processed == []  # toujours en vol — la route a déjà rendu la main
    release.set()
    await asyncio.sleep(0.05)
    assert stub.processed == [1]
