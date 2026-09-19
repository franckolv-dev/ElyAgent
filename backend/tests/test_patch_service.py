# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_patch_service.py
# @brief      « Améliorer la consigne » d'une tâche planifiée : propose /
#             apply / revert / reject, depuis la fiche de la tâche.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""« Améliorer la consigne » — le seul morceau utile de l'ancienne page Incidents.

19/09/2026 : la page « Incidents & propositions » accumulait 81 cartes depuis
juin. « Confirmer » ne faisait rien, un correctif remplacé ne pouvait plus
jamais être vérifié, et chaque exécution douteuse coûtait un appel LLM de
diagnostic. Franck ne s'était servi que d'une chose : la réécriture de la
consigne d'une tâche planifiée. Elle vit maintenant sur la fiche de la tâche,
à la demande, sans incident ni diagnostic en amont.

Run with:  cd backend && python -m pytest tests/test_patch_service.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


def _fake_admin(uid: str = "admin"):
    class _U:
        id = uid
    return _U()


async def _seed_user() -> str:
    from app.database import async_session
    from app.models.user import User
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[:8]}", email=f"{uid[:8]}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _seed_task(uid: str, *, prompt: str = "fais le truc",
                     outcome: str | None = "dubious",
                     last_status: str | None = "success") -> str:
    """Crée une tâche planifiée et, si demandé, le verdict de sa dernière exécution."""
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    from app.models.scheduled_task import ScheduledTask
    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(ScheduledTask(id=tid, user_id=uid, name="T", prompt=prompt,
                             cron_expression="0 9 * * *", channel="web",
                             last_status=last_status, last_result="rien écrit"))
        if outcome:
            db.add(ExecutionOutcome(user_id=uid, source="scheduled", source_id=tid,
                                    outcome=outcome, declared_status="success",
                                    signals='["no_write_effect"]'))
        await db.commit()
    return tid


async def _task_prompt(tid: str) -> str:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    async with async_session() as db:
        return (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == tid)
        )).scalar_one().prompt


_vu_par_le_llm: list[str] = []


async def _fake_patch_llm(prompt, user_id=None):
    _vu_par_le_llm.append(prompt)
    return (
        '{"new_prompt": "Récupère les prospects PUIS écris-les dans le CSV. '
        'Utilise sheets_append_row.", "rationale": "rendu impératif + outil nommé"}',
        "fake-patch-model",
    )


@pytest.fixture
def llm(monkeypatch):
    from app.services.learning import patch_service as ps
    _vu_par_le_llm.clear()
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    return _vu_par_le_llm


# ── 1. parse_patch ─────────────────────────────────────────────────────────


def test_parse_patch_valid_and_fenced() -> None:
    from app.services.learning.patch_service import parse_patch
    v = parse_patch('```json\n{"new_prompt":"X","rationale":"r"}\n```')
    assert v == {"new_prompt": "X", "rationale": "r"}


def test_parse_patch_missing_new_prompt_is_none() -> None:
    from app.services.learning.patch_service import parse_patch
    assert parse_patch('{"rationale":"r"}') is None
    assert parse_patch("pas du json") is None


# ── 2. proposer ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_creates_a_proposal_without_touching_the_task(llm) -> None:
    from app.services.learning.patch_service import propose_for_task
    uid = await _seed_user()
    tid = await _seed_task(uid)
    patch = await propose_for_task(tid, uid)
    assert patch.status == "proposed"
    assert patch.target_id == tid and patch.old_value == "fais le truc"
    assert "sheets_append_row" in patch.new_value
    assert await _task_prompt(tid) == "fais le truc"


@pytest.mark.asyncio
async def test_the_llm_sees_the_last_verdict_and_signals(llm) -> None:
    """Plus de diagnostic en amont : le contexte vient de la dernière exécution."""
    from app.services.learning.patch_service import propose_for_task
    uid = await _seed_user()
    tid = await _seed_task(uid)
    await propose_for_task(tid, uid)
    assert "no_write_effect" in llm[0]
    assert "dubious" in llm[0]
    assert "rien écrit" in llm[0]


@pytest.mark.asyncio
async def test_propose_twice_returns_the_pending_proposal(llm) -> None:
    from app.services.learning.patch_service import propose_for_task
    uid = await _seed_user()
    tid = await _seed_task(uid)
    a = await propose_for_task(tid, uid)
    b = await propose_for_task(tid, uid)
    assert a.id == b.id and len(llm) == 1


@pytest.mark.asyncio
async def test_propose_refuses_someone_elses_task(llm) -> None:
    from app.services.learning.patch_service import PatchError, propose_for_task
    tid = await _seed_task(await _seed_user())
    with pytest.raises(PatchError):
        await propose_for_task(tid, await _seed_user())


@pytest.mark.asyncio
async def test_propose_handles_list_content(monkeypatch) -> None:
    """Un tier à blocs rend `content` en LISTE : pas de `list.strip` hors du try."""
    from app.services.learning import patch_service as ps

    class _Resp:
        content = [{"type": "text", "text": '{"new_prompt": "X", "rationale": "r"}'}]

    class _Llm:
        model = "blocs"

        async def ainvoke(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr("app.services.llm_provider.get_llm_for_tier", lambda _t: _Llm())
    uid = await _seed_user()
    tid = await _seed_task(uid)
    patch = await ps.propose_for_task(tid, uid)
    assert patch.new_value == "X"


# ── 3. appliquer / annuler / rejeter ───────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_writes_the_prompt_and_revert_restores_it(llm) -> None:
    from app.services.learning.patch_service import (
        apply_patch, propose_for_task, revert_patch,
    )
    uid = await _seed_user()
    tid = await _seed_task(uid)
    patch = await propose_for_task(tid, uid)
    applied = await apply_patch(patch.id, uid)
    assert applied.status == "applied" and applied.applied_at is not None
    assert "sheets_append_row" in await _task_prompt(tid)
    reverted = await revert_patch(patch.id, uid)
    assert reverted.status == "reverted"
    assert await _task_prompt(tid) == "fais le truc"


@pytest.mark.asyncio
async def test_apply_twice_is_refused(llm) -> None:
    from app.services.learning.patch_service import PatchError, apply_patch, propose_for_task
    uid = await _seed_user()
    patch = await propose_for_task(await _seed_task(uid), uid)
    await apply_patch(patch.id, uid)
    with pytest.raises(PatchError):
        await apply_patch(patch.id, uid)


@pytest.mark.asyncio
async def test_reject_leaves_the_task_untouched(llm) -> None:
    from app.services.learning.patch_service import propose_for_task, reject_patch
    uid = await _seed_user()
    tid = await _seed_task(uid)
    patch = await propose_for_task(tid, uid)
    assert (await reject_patch(patch.id, uid)).status == "rejected"
    assert await _task_prompt(tid) == "fais le truc"


@pytest.mark.asyncio
async def test_another_user_cannot_apply_revert_or_reject(llm) -> None:
    from app.services.learning.patch_service import (
        PatchError, apply_patch, propose_for_task, reject_patch,
    )
    uid = await _seed_user()
    patch = await propose_for_task(await _seed_task(uid), uid)
    intrus = await _seed_user()
    for op in (apply_patch, reject_patch):
        with pytest.raises(PatchError):
            await op(patch.id, intrus)


@pytest.mark.asyncio
async def test_user_edits_made_after_the_proposal_are_preserved(llm) -> None:
    """La consigne a changé entre la proposition et le clic : on n'écrase rien."""
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    from app.services.learning.patch_service import (
        PatchError, apply_patch, propose_for_task, revert_patch,
    )
    uid = await _seed_user()
    tid = await _seed_task(uid)
    patch = await propose_for_task(tid, uid)
    async with async_session() as db:
        (await db.get(ScheduledTask, tid)).prompt = "ma version à moi"
        await db.commit()
    with pytest.raises(PatchError):
        await apply_patch(patch.id, uid)
    assert await _task_prompt(tid) == "ma version à moi"

    patch2 = await propose_for_task(await _seed_task(uid), uid)
    await apply_patch(patch2.id, uid)
    async with async_session() as db:
        (await db.get(ScheduledTask, patch2.target_id)).prompt = "retouchée après coup"
        await db.commit()
    with pytest.raises(PatchError):
        await revert_patch(patch2.id, uid)


# ── 4. la fiche de la tâche ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_task_card_says_when_a_run_needs_attention(llm) -> None:
    from app.database import async_session
    from app.routers.scheduler import list_tasks
    uid = await _seed_user()
    douteuse = await _seed_task(uid, outcome="dubious")
    saine = await _seed_task(uid, outcome="succeeded")
    en_erreur = await _seed_task(uid, outcome=None, last_status="error")
    async with async_session() as db:
        fiches = {t.id: t for t in await list_tasks(user=_fake_admin(uid), db=db)}
    assert fiches[douteuse].needs_attention is True
    assert fiches[en_erreur].needs_attention is True
    assert fiches[saine].needs_attention is False
    assert fiches[douteuse].last_outcome == "dubious"


@pytest.mark.asyncio
async def test_endpoints_propose_apply_revert_and_the_card_embeds_the_patch(llm) -> None:
    from app.database import async_session
    from app.routers.scheduler import (
        apply_prompt_patch, improve_prompt, list_tasks, revert_prompt_patch,
    )
    uid = await _seed_user()
    tid = await _seed_task(uid)
    moi = _fake_admin(uid)
    out = await improve_prompt(tid, user=moi)
    assert out.status == "proposed" and out.old_value == "fais le truc"
    async with async_session() as db:
        fiche = next(t for t in await list_tasks(user=moi, db=db) if t.id == tid)
    assert fiche.prompt_patch is not None and fiche.prompt_patch.id == out.id

    assert (await apply_prompt_patch(out.id, user=moi)).status == "applied"
    assert (await revert_prompt_patch(out.id, user=moi)).status == "reverted"
    async with async_session() as db:
        fiche = next(t for t in await list_tasks(user=moi, db=db) if t.id == tid)
    assert fiche.prompt_patch is None, "un correctif annulé ne reste pas sur la fiche"


@pytest.mark.asyncio
async def test_endpoint_refuses_a_foreign_task(llm) -> None:
    from app.routers.scheduler import improve_prompt
    tid = await _seed_task(await _seed_user())
    with pytest.raises(HTTPException) as exc:
        await improve_prompt(tid, user=_fake_admin(await _seed_user()))
    assert exc.value.status_code in (404, 422)
