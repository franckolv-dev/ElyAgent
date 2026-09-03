# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase2_batch3.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 2 lot 3a — pins :
#             A-6b budget LLM quotidien par user (opt-in) + coûts
#             background comptés dans UsageLog.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Phase 2 batch 3a pins (revue 2026-06-10)."""
from __future__ import annotations

import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────────
# Fixture — user jetable + lignes UsageLog contrôlées
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def user_with_spend():
    from app.database import async_session, init_db
    from app.models.usage_log import UsageLog
    from app.models.user import User
    from sqlalchemy import delete

    await init_db()
    uid = f"test_budget_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid, username=f"u_{uid[-8:]}", email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        # 0.30 $ aujourd'hui + 5 $ HIER (ne doit pas compter)
        db.add(UsageLog(
            user_id=uid, model="m", provider="p",
            input_tokens=1, output_tokens=1, total_tokens=2, cost_usd=0.30,
        ))
        db.add(UsageLog(
            user_id=uid, model="m", provider="p",
            input_tokens=1, output_tokens=1, total_tokens=2, cost_usd=5.0,
            timestamp=datetime.now(timezone.utc) - timedelta(days=1, hours=1),
        ))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(UsageLog).where(UsageLog.user_id == uid))
        u = await db.get(User, uid)
        if u is not None:
            await db.delete(u)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────
# A-6b — budget quotidien
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_disabled_by_default(monkeypatch, user_with_spend) -> None:
    """Défaut = désactivé : une install solo (Franck) ne doit JAMAIS
    s'auto-bloquer sur une table de prix heuristique."""
    from app.services.budget_guard import check_user_budget

    monkeypatch.delenv("ELY_USER_DAILY_BUDGET_USD", raising=False)
    assert await check_user_budget(user_with_spend) is None


@pytest.mark.asyncio
async def test_budget_counts_only_today(monkeypatch, user_with_spend) -> None:
    """Le user a 0.30 $ aujourd'hui et 5 $ hier : avec un budget de 1 $,
    il doit passer (hier ne compte pas — fenêtre = minuit UTC)."""
    from app.services.budget_guard import check_user_budget, get_today_spend_usd

    assert await get_today_spend_usd(user_with_spend) == pytest.approx(0.30)
    monkeypatch.setenv("ELY_USER_DAILY_BUDGET_USD", "1.0")
    assert await check_user_budget(user_with_spend) is None


@pytest.mark.asyncio
async def test_budget_refuses_when_exceeded(monkeypatch, user_with_spend) -> None:
    from app.services.budget_guard import check_user_budget

    monkeypatch.setenv("ELY_USER_DAILY_BUDGET_USD", "0.25")
    refusal = await check_user_budget(user_with_spend)
    assert refusal is not None
    assert "Budget" in refusal


@pytest.mark.asyncio
async def test_budget_never_blocks_on_db_error(monkeypatch) -> None:
    """Best-effort : une erreur DB ne bloque jamais un run — le budget est
    un garde-fou de coût, pas une barrière de sécurité."""
    from app.services import budget_guard as bg

    async def boom(_uid):
        raise RuntimeError("db down")

    monkeypatch.setenv("ELY_USER_DAILY_BUDGET_USD", "1.0")
    monkeypatch.setattr(bg, "get_today_spend_usd", boom)
    assert await bg.check_user_budget("u1") is None


# ─────────────────────────────────────────────────────────────────────────
# A-6b — coûts background comptés
# ─────────────────────────────────────────────────────────────────────────


def _fake_response(input_tokens: int = 0, output_tokens: int = 0, model: str | None = None):
    resp = types.SimpleNamespace()
    resp.usage_metadata = (
        {"input_tokens": input_tokens, "output_tokens": output_tokens}
        if (input_tokens or output_tokens) else None
    )
    resp.response_metadata = {"model_name": model} if model else {}
    return resp


@pytest.mark.asyncio
async def test_log_response_usage_extracts_tokens(monkeypatch) -> None:
    from app.services import analytics_service as an

    seen: list[dict] = []

    async def fake_log_usage(**kw):
        seen.append(kw)

    monkeypatch.setattr(an, "log_usage", fake_log_usage)

    await an.log_response_usage(
        "u1", _fake_response(120, 40, model="gemma-4"),
        skill_used="conversation_summary",
    )
    assert len(seen) == 1
    assert seen[0]["input_tokens"] == 120
    assert seen[0]["output_tokens"] == 40
    assert seen[0]["model"] == "gemma-4"
    assert seen[0]["channel"] == "background"


@pytest.mark.asyncio
async def test_log_response_usage_noop_without_metadata(monkeypatch) -> None:
    """Les providers qui n'exposent pas usage_metadata → no-op silencieux,
    jamais de ligne UsageLog à 0 token."""
    from app.services import analytics_service as an

    seen: list[dict] = []

    async def fake_log_usage(**kw):
        seen.append(kw)

    monkeypatch.setattr(an, "log_usage", fake_log_usage)
    await an.log_response_usage("u1", _fake_response())
    assert seen == []


def test_background_paths_are_instrumented() -> None:
    """Pin source-level : les 3 chemins background identifiés par la revue
    (résumé de fin de conversation, extraction+consolidation mémoire,
    mission critic) appellent log_response_usage."""
    from pathlib import Path

    assert "log_response_usage" in Path("app/routers/chat.py").read_text()
    assert Path("app/services/memory_service.py").read_text().count("log_response_usage") >= 2
    assert "log_response_usage" in Path("app/services/learning/mission_critic.py").read_text()
