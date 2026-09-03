# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_patch_service.py
# @brief      Boucle d'auto-diagnostic J5 — correctifs validables (voie C) :
#             propose / apply / revert / reject d'un prompt de tâche planifiée,
#             + endpoints admin.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests J5 — patch_service + endpoints.

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


async def _seed_scheduled_incident(uid: str, *, prompt: str = "fais le truc",
                                   category: str = "prompt") -> tuple[str, int, int]:
    """Crée task + execution_outcome(scheduled,dubious) + diagnosis(open).
    Renvoie (task_id, outcome_id, diagnosis_id)."""
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    from app.models.execution_outcome import ExecutionOutcome
    from app.models.execution_diagnosis import ExecutionDiagnosis
    tid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(ScheduledTask(id=tid, user_id=uid, name="T", prompt=prompt,
                             cron_expression="0 9 * * *", channel="web"))
        await db.commit()
    async with async_session() as db:
        oc = ExecutionOutcome(user_id=uid, source="scheduled", source_id=tid,
                              outcome="dubious", declared_status="success",
                              signals='["no_write_effect"]')
        db.add(oc)
        await db.commit()
        oc_id = oc.id
        diag = ExecutionDiagnosis(execution_outcome_id=oc_id, user_id=uid,
                                  source="scheduled", source_id=tid,
                                  category=category, hypothesis="prompt trop mou",
                                  confidence="medium", status="open",
                                  critic_model="rule-based")
        db.add(diag)
        await db.commit()
        return tid, oc_id, diag.id


async def _task_prompt(tid: str) -> str:
    from app.database import async_session
    from app.models.scheduled_task import ScheduledTask
    async with async_session() as db:
        t = (await db.execute(
            select(ScheduledTask).where(ScheduledTask.id == tid)
        )).scalar_one()
        return t.prompt


async def _diag_status(did: int) -> str:
    from app.database import async_session
    from app.models.execution_diagnosis import ExecutionDiagnosis
    async with async_session() as db:
        d = (await db.execute(
            select(ExecutionDiagnosis).where(ExecutionDiagnosis.id == did)
        )).scalar_one()
        return d.status


async def _fake_patch_llm(prompt, user_id=None):
    return (
        '{"new_prompt": "Récupère les prospects PUIS écris-les dans le CSV. '
        'Utilise sheets_append_row.", "rationale": "rendu impératif + outil nommé"}',
        "fake-patch-model",
    )


# ── 1. parse_patch ─────────────────────────────────────────────────────────


def test_parse_patch_valid_and_fenced() -> None:
    from app.services.learning.patch_service import parse_patch
    v = parse_patch('```json\n{"new_prompt":"X","rationale":"r"}\n```')
    assert v == {"new_prompt": "X", "rationale": "r"}


def test_parse_patch_missing_new_prompt_is_none() -> None:
    from app.services.learning.patch_service import parse_patch
    assert parse_patch('{"new_prompt":"","rationale":"r"}') is None
    assert parse_patch("nope") is None


# ── 2. propose / apply / revert / reject ───────────────────────────────────


@pytest.mark.asyncio
async def test_propose_patch_creates_proposed(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="fais le truc")

    patch = await ps.propose_patch(did)
    assert patch is not None
    assert patch.status == "proposed"
    assert patch.target_type == "scheduled_task"
    assert patch.target_id == tid
    assert patch.old_value == "fais le truc"
    assert "CSV" in patch.new_value
    # NE touche PAS la tâche tant que non appliqué
    assert await _task_prompt(tid) == "fais le truc"


@pytest.mark.asyncio
async def test_propose_patch_handles_list_content(monkeypatch) -> None:
    """Régression : un provider tier-C qui renvoie ``content`` en LISTE de
    blocs (Responses API / codex, modèles à reasoning, Anthropic) ne doit PAS
    faire planter (HTTP 500 via ``list.strip``) — le contenu est coercé en str.

    On exerce le VRAI ``_call_patch_llm`` (pas le stub) en n'interceptant que
    ``get_llm_for_tier``, pour couvrir la coercition ``content_to_text``.
    """
    import app.services.llm_provider as provider

    class _FakeLLM:
        model = "fake-reasoning"

        async def ainvoke(self, _messages, config=None):  # noqa: ARG002
            # Forme réelle d'OpenAI Responses API / openai-codex (output_version
            # v0) : une LISTE de blocs typés, pas une str (cf. message_content).
            # Les blocs « reasoning » n'ont pas de champ ``text`` → ignorés.
            class _R:
                content = [
                    {"type": "reasoning", "index": 0},
                    {"type": "text", "index": 0,
                     "text": '{"new_prompt": "Récupère PUIS écris dans le CSV.",'
                             ' "rationale": "rendu impératif"}'},
                ]
            return _R()

    monkeypatch.setattr(provider, "get_llm_for_tier", lambda _tier: _FakeLLM())
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="fais le truc")

    import app.services.learning.patch_service as ps
    patch = await ps.propose_patch(did)        # ne doit pas lever
    assert patch is not None
    assert patch.status == "proposed"
    assert "CSV" in patch.new_value


@pytest.mark.asyncio
async def test_propose_patch_rejects_non_scheduled(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    from app.models.execution_diagnosis import ExecutionDiagnosis
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    async with async_session() as db:
        oc = ExecutionOutcome(user_id=uid, source="mission", source_id="m1",
                              outcome="dubious", declared_status="completed")
        db.add(oc)
        await db.commit()
        diag = ExecutionDiagnosis(execution_outcome_id=oc.id, user_id=uid,
                                  source="mission", source_id="m1",
                                  category="prompt", hypothesis="x",
                                  confidence="low", status="open")
        db.add(diag)
        await db.commit()
        did = diag.id
    with pytest.raises(ps.PatchError):
        await ps.propose_patch(did)


@pytest.mark.asyncio
async def test_apply_patch_writes_prompt_and_actions_incident(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="ancien prompt")

    patch = await ps.propose_patch(did)
    applied = await ps.apply_patch(patch.id)
    assert applied.status == "applied"
    assert applied.applied_at is not None
    assert applied.old_value == "ancien prompt"          # snapshot exact
    assert await _task_prompt(tid) == patch.new_value      # tâche modifiée
    assert await _diag_status(did) == "actioned"           # incident résolu


@pytest.mark.asyncio
async def test_revert_patch_restores_prompt(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="prompt original")

    patch = await ps.propose_patch(did)
    await ps.apply_patch(patch.id)
    assert await _task_prompt(tid) != "prompt original"
    reverted = await ps.revert_patch(patch.id)
    assert reverted.status == "reverted"
    assert await _task_prompt(tid) == "prompt original"    # restauré


@pytest.mark.asyncio
async def test_apply_twice_is_refused(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    _tid, _oc, did = await _seed_scheduled_incident(uid)
    patch = await ps.propose_patch(did)
    await ps.apply_patch(patch.id)
    with pytest.raises(ps.PatchError):
        await ps.apply_patch(patch.id)


@pytest.mark.asyncio
async def test_reject_patch_leaves_task_untouched(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="intact")
    patch = await ps.propose_patch(did)
    rejected = await ps.reject_patch(patch.id)
    assert rejected.status == "rejected"
    assert await _task_prompt(tid) == "intact"


# ── 3. Endpoints + IncidentOut embeds patch ────────────────────────────────


@pytest.mark.asyncio
async def test_endpoints_propose_apply_and_incident_embeds_patch(monkeypatch) -> None:
    import app.services.learning.patch_service as ps
    from app.database import async_session
    from app.routers.learning_skills import (
        apply_incident_patch,
        list_incidents,
        propose_incident_patch,
    )
    monkeypatch.setattr(ps, "_call_patch_llm", _fake_patch_llm)
    uid = await _seed_user()
    tid, _oc, did = await _seed_scheduled_incident(uid, prompt="vieux")

    patch_out = await propose_incident_patch(did, _admin=_fake_admin())
    assert patch_out.status == "proposed"

    # l'incident (open) embarque maintenant le correctif proposé
    async with async_session() as db:
        rows = await list_incidents(status="open", user_id=uid, limit=100,
                                    _admin=_fake_admin(), db=db)
    assert len(rows) == 1
    assert rows[0].patch is not None
    assert rows[0].patch.status == "proposed"

    # apply via endpoint → tâche modifiée + incident actioned
    applied = await apply_incident_patch(patch_out.id, _admin=_fake_admin())
    assert applied.status == "applied"
    assert await _task_prompt(tid) == patch_out.new_value
    assert await _diag_status(did) == "actioned"


def test_patch_routes_registered() -> None:
    from app.routers.learning_skills import router
    paths = {r.path for r in router.routes}
    assert "/admin/learning/incidents/{incident_id}/propose-patch" in paths
    assert "/admin/learning/patches/{patch_id}/apply" in paths
    assert "/admin/learning/patches/{patch_id}/revert" in paths
    assert "/admin/learning/patches/{patch_id}/reject" in paths
