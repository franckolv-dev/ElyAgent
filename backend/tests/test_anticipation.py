# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_anticipation.py
# @brief      C5 — anticipation V1 : détecter les demandes récurrentes et
#             PROPOSER une tâche planifiée (jamais exécuter seule).
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""C5 (P4) — anticipation en mode suggestion.

Cadrage validé (docs_internes/cadrage_c5_anticipation_v1.md) : détecteur
hebdo 100 % heuristique (lexical + cadence) sur la DB messages (28 j
glissants, messages user), seuils ≥ 3 occurrences / heures resserrées
± 2 h / même jour de semaine ; une suggestion par pattern_hash MAXIMUM,
un refus n'est JAMAIS re-proposé ; notification ntfy + endpoints
/api/me/suggestions ; Ely ne crée jamais la tâche elle-même.

Run with:  cd backend && python -m pytest tests/test_anticipation.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database import async_session, init_db
from app.models.anticipation import AnticipationSuggestion, SuggestionStatus
from app.models.conversation import Conversation, Message
from app.services.anticipation import (
    MIN_OCCURRENCES,
    _cluster_key,
    detect_time_regularity,
    run_anticipation_cycle,
    scan_user,
)

_REPO = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User

    uid = f"ant-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(id=uid, username=f"ant_{uid}", email=f"{uid}@test.local",
                    hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(AnticipationSuggestion).where(
            AnticipationSuggestion.user_id == uid))
        convs = (await db.execute(
            select(Conversation.id).where(Conversation.user_id == uid)
        )).scalars().all()
        if convs:
            await db.execute(delete(Message).where(Message.conversation_id.in_(convs)))
            await db.execute(delete(Conversation).where(Conversation.id.in_(convs)))
        from app.models.user import User
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _seed_user_message(uid: str, content: str, at: datetime) -> None:
    async with async_session() as db:
        conv = Conversation(user_id=uid, title="ant seed")
        db.add(conv)
        await db.flush()
        m = Message(conversation_id=str(conv.id), role="user", content=content)
        db.add(m)
        await db.flush()
        m.created_at = at.astimezone(timezone.utc).replace(tzinfo=None)
        conv.updated_at = m.created_at
        await db.commit()


# ────────────────────────────────────────────────────────────────────────
# Détecteur pur
# ────────────────────────────────────────────────────────────────────────


def test_cluster_key_groups_quasi_duplicates():
    a = _cluster_key("Quels sont mes mails importants ?")
    b = _cluster_key("quels sont mes mails importants")
    # Casse/ponctuation/accents ne séparent pas…
    assert a and a == b
    # …mais une PARAPHRASE (tokens différents : « sont-ils », plus de
    # « mes ») est un pattern DISTINCT — seuil élevé assumé par le
    # cadrage V1 : quasi-doublons stricts, pas d'analyse sémantique.
    c = _cluster_key("mails importants — quels sont-ils ?")
    assert c != a
    assert _cluster_key("météo de demain") != a


def test_cluster_key_rejects_trivial_messages():
    assert _cluster_key("bonjour") is None      # 1 seul token significatif
    assert _cluster_key("ok") is None
    assert _cluster_key("") is None


def test_detect_daily_regularity():
    base = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)  # lundi 9h
    times = [base + timedelta(days=d, minutes=m)
             for d, m in ((0, 0), (1, 10), (2, -15), (4, 5))]
    out = detect_time_regularity(times)
    assert out is not None
    assert out["kind"] == "daily"
    assert out["hour"] == 9


def test_detect_daily_needs_distinct_days():
    base = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=i) for i in range(4)]  # même jour
    assert detect_time_regularity(times) is None


def test_detect_weekly_regularity():
    base = datetime(2026, 7, 6, 18, 30, tzinfo=timezone.utc)  # lundi
    times = [base - timedelta(weeks=w) for w in (0, 1, 2)]
    out = detect_time_regularity(times)
    assert out is not None
    assert out["kind"] == "weekly"
    assert out["weekday"] == 0  # lundi
    assert out["hour"] == 18


def test_detect_scattered_returns_none():
    times = [
        datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),   # mercredi matin
        datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc),  # dimanche soir
        datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc), # mardi aprem
    ]
    assert detect_time_regularity(times) is None


# ────────────────────────────────────────────────────────────────────────
# Scan utilisateur (SQLite réel)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_user_finds_weekly_pattern(_user):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for w in (1, 2, 3):
        await _seed_user_message(_user, "fais-moi le point sur mes factures",
                                 now - timedelta(weeks=w))
    # Bruit non récurrent
    await _seed_user_message(_user, "traduis ce paragraphe en anglais",
                             now - timedelta(days=3))

    candidates = await scan_user(_user, now=now)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["occurrences"] >= MIN_OCCURRENCES
    assert c["cadence"]["kind"] == "weekly"
    assert "factures" in c["suggested_prompt"]
    assert c["pattern_hash"]


@pytest.mark.asyncio
async def test_scan_user_ignores_low_frequency(_user):
    now = datetime.now(timezone.utc)
    for w in (1, 2):  # seulement 2 occurrences < MIN_OCCURRENCES
        await _seed_user_message(_user, "rappelle-moi d'arroser les plantes",
                                 now - timedelta(weeks=w))
    assert await scan_user(_user, now=now) == []


@pytest.mark.asyncio
async def test_scan_user_excludes_scheduler_conversations(_user):
    """Angle mort attrapé au 1er test réel (22/07, 8 fausses suggestions) :
    le scheduler persiste CHAQUE run comme une conversation « [Planifié] … »
    avec le prompt en message user → le détecteur voyait les tâches DÉJÀ
    planifiées comme des routines à planifier (ouroboros). Ces conversations
    synthétiques sont exclues du scan."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    async with async_session() as db:
        conv = Conversation(user_id=_user, title="[Planifié] daily brief")
        db.add(conv)
        await db.flush()
        conv_id = str(conv.id)
        for d in (1, 2, 3, 4):
            m = Message(conversation_id=conv_id, role="user",
                        content="prépare et envoie le daily briefing complet")
            db.add(m)
            await db.flush()
            m.created_at = (now - timedelta(days=d)).replace(tzinfo=None)
        await db.commit()

    assert await scan_user(_user, now=now) == []


# ────────────────────────────────────────────────────────────────────────
# Cycle : insertion, anti-spam, refus définitif, kill-switch, ntfy
# ────────────────────────────────────────────────────────────────────────


async def _seed_weekly_pattern(uid: str, now: datetime, text: str = "fais-moi le point sur mes factures"):
    for w in (1, 2, 3):
        await _seed_user_message(uid, text, now - timedelta(weeks=w))


@pytest.mark.asyncio
async def test_cycle_inserts_once_and_notifies_once(_user, monkeypatch):
    calls: list = []

    async def _fake_notify(**kw):
        calls.append(kw)

    monkeypatch.setattr(
        "app.services.anticipation._notify_suggestion", _fake_notify,
    )
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    await _seed_weekly_pattern(_user, now)

    out1 = await run_anticipation_cycle(now=now)
    out2 = await run_anticipation_cycle(now=now)  # re-run → anti-spam

    assert out1["proposed"] == 1
    assert out2["proposed"] == 0
    assert len(calls) == 1

    async with async_session() as db:
        rows = (await db.execute(
            select(AnticipationSuggestion).where(
                AnticipationSuggestion.user_id == _user)
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == SuggestionStatus.PROPOSED
    assert rows[0].suggested_prompt
    assert rows[0].suggested_cadence.startswith("weekly:")


@pytest.mark.asyncio
async def test_cycle_never_reproposes_dismissed(_user, monkeypatch):
    async def _fake_notify(**kw):
        pass

    monkeypatch.setattr(
        "app.services.anticipation._notify_suggestion", _fake_notify,
    )
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    await _seed_weekly_pattern(_user, now)

    await run_anticipation_cycle(now=now)
    async with async_session() as db:
        row = (await db.execute(
            select(AnticipationSuggestion).where(
                AnticipationSuggestion.user_id == _user)
        )).scalar_one()
        row.status = SuggestionStatus.DISMISSED
        await db.commit()

    out = await run_anticipation_cycle(now=now)
    assert out["proposed"] == 0
    async with async_session() as db:
        rows = (await db.execute(
            select(AnticipationSuggestion).where(
                AnticipationSuggestion.user_id == _user)
        )).scalars().all()
    assert len(rows) == 1  # toujours l'unique row, restée dismissed


@pytest.mark.asyncio
async def test_cycle_kill_switch(monkeypatch, _user):
    monkeypatch.setenv("ANTICIPATION_DISABLED", "true")
    out = await run_anticipation_cycle()
    assert out["skipped_disabled"] is True


def test_ntfy_title_goes_through_ascii_header():
    """En-têtes HTTP = ASCII (leçon #220) — tout Title ntfy passe par
    ascii_header. 5ᵉ site pinné."""
    src = (_REPO / "app/services/anticipation.py").read_text(encoding="utf-8")
    assert "ascii_header(" in src


# ────────────────────────────────────────────────────────────────────────
# Endpoints /api/me/suggestions (handlers directs, pattern maison)
# ────────────────────────────────────────────────────────────────────────


async def _get_user_obj(uid: str):
    from app.models.user import User
    async with async_session() as db:
        return (await db.execute(select(User).where(User.id == uid))).scalar_one()


async def _seed_suggestion(uid: str) -> int:
    async with async_session() as db:
        s = AnticipationSuggestion(
            user_id=uid,
            pattern_hash=uuid.uuid4().hex[:16],
            suggested_prompt="fais-moi le point sur mes factures",
            suggested_cadence="weekly:mon@09:00",
            evidence_json="[]",
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_list_suggestions_scoped_to_caller(_user):
    from app.routers.suggestions import list_suggestions

    sid = await _seed_suggestion(_user)
    me = await _get_user_obj(_user)
    out = await list_suggestions(current_user=me)
    assert [s["id"] for s in out["suggestions"]] == [sid]


@pytest.mark.asyncio
async def test_dismiss_marks_and_is_idempotent(_user):
    from app.routers.suggestions import dismiss_suggestion

    sid = await _seed_suggestion(_user)
    me = await _get_user_obj(_user)
    out = await dismiss_suggestion(sid, current_user=me)
    assert out["status"] == SuggestionStatus.DISMISSED
    out2 = await dismiss_suggestion(sid, current_user=me)  # idempotent
    assert out2["status"] == SuggestionStatus.DISMISSED


@pytest.mark.asyncio
async def test_accept_marks_accepted(_user):
    from app.routers.suggestions import accept_suggestion

    sid = await _seed_suggestion(_user)
    me = await _get_user_obj(_user)
    out = await accept_suggestion(sid, current_user=me)
    assert out["status"] == SuggestionStatus.ACCEPTED


@pytest.mark.asyncio
async def test_foreign_suggestion_404(_user):
    from fastapi import HTTPException

    from app.routers.suggestions import dismiss_suggestion

    sid = await _seed_suggestion(_user)
    # Autre utilisateur
    from app.models.user import User
    other_id = f"ant-o-{uuid.uuid4().hex[:6]}"
    async with async_session() as db:
        db.add(User(id=other_id, username=other_id,
                    email=f"{other_id}@test.local", hashed_password="x"))
        await db.commit()
    other = await _get_user_obj(other_id)
    with pytest.raises(HTTPException) as exc:
        await dismiss_suggestion(sid, current_user=other)
    assert exc.value.status_code == 404
    async with async_session() as db:
        await db.execute(delete(User).where(User.id == other_id))
        await db.commit()


def test_router_registered_in_main():
    src = (_REPO / "app/main.py").read_text(encoding="utf-8")
    assert "suggestions" in src, (
        "include_router(suggestions) manquant dans main.py — les endpoints "
        "n'existeraient pas en prod."
    )


def test_cron_registered_in_main():
    src = (_REPO / "app/main.py").read_text(encoding="utf-8")
    assert "run_anticipation_cycle" in src, (
        "Le cron hebdo d'anticipation doit être enregistré au boot "
        "(pattern learned_skills_curator)."
    )
