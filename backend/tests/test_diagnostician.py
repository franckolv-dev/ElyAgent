# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_diagnostician.py
# @brief      Boucle d'auto-diagnostic J3 — diagnostiqueur (maillon 2) :
#             classifieur à règles, parsing LLM, diagnose_execution (LLM +
#             repli), cron run_pending_diagnoses.
# @license    MIT
# =============================================================================
"""Tests J3 — diagnostiqueur.

Run with:  cd backend && python -m pytest tests/test_diagnostician.py -v
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.database import init_db
    await init_db()


async def _seed_user() -> str:
    from app.database import async_session
    from app.models.user import User
    uid = str(uuid.uuid4())
    async with async_session() as db:
        db.add(User(id=uid, username=f"u_{uid[:8]}", email=f"{uid[:8]}@t.local",
                    hashed_password="x"))
        await db.commit()
    return uid


async def _seed_outcome(uid: str, *, outcome: str = "dubious",
                        signals: list[str] | None = None, source: str = "scheduled",
                        source_id: str | None = None,
                        conversation_id: str | None = None,
                        model_used: str | None = None) -> int:
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    async with async_session() as db:
        row = ExecutionOutcome(
            user_id=uid, source=source, source_id=source_id, outcome=outcome,
            declared_status="success",
            signals=json.dumps(signals) if signals else None,
            conversation_id=conversation_id, model_used=model_used,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _diagnoses(uid: str) -> list:
    from app.database import async_session
    from app.models.execution_diagnosis import ExecutionDiagnosis
    async with async_session() as db:
        return list((await db.execute(
            select(ExecutionDiagnosis).where(ExecutionDiagnosis.user_id == uid)
        )).scalars().all())


# ── 1. Classifieur à règles ───────────────────────────────────────────────


def test_rule_based_claimed_no_tool_is_binding() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, conf, _ = rule_based_diagnosis({"signals": ["claimed_no_tool"]})
    assert cat == "binding"


def test_rule_based_repeated_fallback_is_config_tier_high() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, conf, _ = rule_based_diagnosis({
        "signals": ["fallback"], "provider_switches": {"count": 3, "reasons": ["timeout"]},
    })
    assert cat == "config_tier"
    assert conf == "high"


def test_rule_based_single_fallback_is_config_tier_medium() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, conf, _ = rule_based_diagnosis({
        "signals": ["fallback"], "provider_switches": {"count": 1},
    })
    assert cat == "config_tier"
    assert conf == "medium"


def test_rule_based_no_write_effect_is_prompt() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, _, _ = rule_based_diagnosis({"signals": ["no_write_effect"]})
    assert cat == "prompt"


def test_rule_based_learned_tool_error_is_gap_tool() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, _, _ = rule_based_diagnosis({
        "signals": [], "tool_errors": {"count": 1, "origins": ["learned"]},
    })
    assert cat == "gap_tool"


def test_rule_based_builtin_tool_error_is_code_core_low() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, conf, _ = rule_based_diagnosis({
        "signals": [], "tool_errors": {"count": 2, "origins": ["builtin"]},
    })
    assert cat == "code_core"
    assert conf == "low"


def test_rule_based_empty_is_unknown() -> None:
    from app.services.learning.diagnostician import rule_based_diagnosis
    cat, conf, _ = rule_based_diagnosis({"signals": []})
    assert cat == "unknown"
    assert conf == "low"


# ── 2. Parsing du verdict LLM ──────────────────────────────────────────────


def test_parse_diagnosis_valid() -> None:
    from app.services.learning.diagnostician import parse_diagnosis
    v = parse_diagnosis('{"category":"config_tier","confidence":"high","hypothesis":"Tier instable."}')
    assert v == {"category": "config_tier", "confidence": "high", "hypothesis": "Tier instable."}


def test_parse_diagnosis_unknown_category_and_default_confidence() -> None:
    from app.services.learning.diagnostician import parse_diagnosis
    v = parse_diagnosis('{"category":"banana","confidence":"épique","hypothesis":"x"}')
    assert v["category"] == "unknown"
    assert v["confidence"] == "medium"


def test_parse_diagnosis_strips_fences() -> None:
    from app.services.learning.diagnostician import parse_diagnosis
    raw = '```json\n{"category":"binding","confidence":"low","hypothesis":"trou de binding"}\n```'
    v = parse_diagnosis(raw)
    assert v["category"] == "binding"


def test_parse_diagnosis_missing_hypothesis_is_none() -> None:
    from app.services.learning.diagnostician import parse_diagnosis
    assert parse_diagnosis('{"category":"prompt","confidence":"low","hypothesis":""}') is None
    assert parse_diagnosis("pas du json") is None
    assert parse_diagnosis("") is None


# ── 3. diagnose_execution (LLM mocké + repli) ──────────────────────────────


async def _fake_llm_config_tier(prompt, user_id=None):
    return (
        '{"category":"config_tier","confidence":"high","hypothesis":'
        '"Le tier C bascule en boucle depuis le passage à gpt-5.5."}',
        "fake-critic-model",
    )


@pytest.mark.asyncio
async def test_diagnose_execution_uses_llm_verdict(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _fake_llm_config_tier)

    uid = await _seed_user()
    oid = await _seed_outcome(uid, outcome="dubious", signals=["fallback"])
    did = await diag.diagnose_execution(oid)
    assert did is not None

    rows = await _diagnoses(uid)
    assert len(rows) == 1
    assert rows[0].execution_outcome_id == oid
    assert rows[0].category == "config_tier"
    assert rows[0].confidence == "high"
    assert rows[0].critic_model == "fake-critic-model"
    assert rows[0].status == "open"
    assert "gpt-5.5" in rows[0].hypothesis


@pytest.mark.asyncio
async def test_diagnose_execution_falls_back_to_rules_on_llm_error(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag

    async def _boom(prompt, user_id=None):
        raise RuntimeError("llm down")
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _boom)

    uid = await _seed_user()
    oid = await _seed_outcome(uid, outcome="dubious", signals=["claimed_no_tool"])
    did = await diag.diagnose_execution(oid)
    assert did is not None

    rows = await _diagnoses(uid)
    assert len(rows) == 1
    assert rows[0].category == "binding"          # repli à règles
    assert rows[0].critic_model == "rule-based"


@pytest.mark.asyncio
async def test_diagnose_execution_skips_succeeded(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _fake_llm_config_tier)
    uid = await _seed_user()
    oid = await _seed_outcome(uid, outcome="succeeded")
    assert await diag.diagnose_execution(oid) is None
    assert await _diagnoses(uid) == []


@pytest.mark.asyncio
async def test_diagnose_execution_is_idempotent(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _fake_llm_config_tier)
    uid = await _seed_user()
    oid = await _seed_outcome(uid, outcome="failed", signals=["fallback"])
    did1 = await diag.diagnose_execution(oid)
    did2 = await diag.diagnose_execution(oid)
    assert did1 == did2
    assert len(await _diagnoses(uid)) == 1


# ── 4. Cron run_pending_diagnoses ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_pending_diagnoses_only_dubious_failed(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _fake_llm_config_tier)
    uid = await _seed_user()
    await _seed_outcome(uid, outcome="succeeded")
    oid_d = await _seed_outcome(uid, outcome="dubious", signals=["fallback"])
    oid_f = await _seed_outcome(uid, outcome="failed")

    # batch_limit large : le cron scanne GLOBALEMENT (pas de filtre user), donc
    # on vérifie l'effet SUR CE USER plutôt que le compteur global — robuste à
    # d'éventuels outcomes laissés par d'autres tests dans la base partagée.
    await diag.run_pending_diagnoses(batch_limit=500)
    diags = await _diagnoses(uid)
    diagnosed = {d.execution_outcome_id for d in diags}
    assert oid_d in diagnosed          # dubious diagnostiqué
    assert oid_f in diagnosed          # failed diagnostiqué
    assert len(diags) == 2             # le « succeeded » ne l'est PAS

    # 2e passage : rien de neuf pour ce user (idempotent)
    await diag.run_pending_diagnoses(batch_limit=500)
    assert len(await _diagnoses(uid)) == 2


# ── 5. gather_evidence corrèle les signaux ─────────────────────────────────


@pytest.mark.asyncio
async def test_gather_evidence_correlates_provider_switch_by_conversation() -> None:
    from app.database import async_session
    from app.models.execution_outcome import ExecutionOutcome
    from app.models.provider_switch import ProviderSwitch
    from app.services.learning.diagnostician import gather_evidence

    uid = await _seed_user()
    conv = f"conv-{uuid.uuid4()}"
    async with async_session() as db:
        db.add(ProviderSwitch(
            user_id=uid, conversation_id=conv, tier_llm="C",
            from_provider="openai-codex", to_provider="deepseek-v4-pro",
            reason="timeout", position_in_chain=1,
        ))
        await db.commit()
    oid = await _seed_outcome(uid, outcome="dubious", signals=["fallback"],
                              conversation_id=conv)
    async with async_session() as db:
        outcome = (await db.execute(
            select(ExecutionOutcome).where(ExecutionOutcome.id == oid)
        )).scalar_one()

    ev = await gather_evidence(outcome)
    assert ev["provider_switches"]["count"] == 1
    assert "timeout" in ev["provider_switches"]["reasons"]
    assert ev["signals"] == ["fallback"]


# ── 6. Garde anti-doublon (incidents récurrents) ───────────────────────────
#
# Une tâche planifiée qui échoue de la même façon chaque jour ne doit produire
# QU'UN incident open (compteur occurrences), pas un par run. La garde compare
# la clé (user_id, source, source_id, category=rule_cat) AVANT l'appel LLM.


_PROMPT_VERDICT = (
    '{"category":"prompt","confidence":"high","hypothesis":'
    '"La tâche déclare un succès sans jamais écrire."}'
)


def _counting_llm(payload: str = _PROMPT_VERDICT):
    """Faux LLM qui compte ses appels — la garde doit économiser le LLM."""
    calls = {"n": 0}

    async def _fake(prompt, user_id=None):
        calls["n"] += 1
        return payload, "fake-critic-model"

    return _fake, calls


async def _seed_open_diagnosis(uid: str, *, source_id: str,
                               category: str = "prompt") -> int:
    """Simule un doublon du backlog pré-dédup : une diagnose open par run."""
    from app.database import async_session
    from app.models.execution_diagnosis import ExecutionDiagnosis
    oid = await _seed_outcome(uid, signals=["no_write_effect"], source_id=source_id)
    async with async_session() as db:
        row = ExecutionDiagnosis(
            execution_outcome_id=oid, user_id=uid, source="scheduled",
            source_id=source_id, category=category,
            hypothesis="Succès déclaré sans outil d'écriture.",
            confidence="medium", critic_model="rule-based", status="open",
        )
        db.add(row)
        await db.commit()
        return row.id


def test_merged_status_registered() -> None:
    from app.models.execution_diagnosis import DIAGNOSIS_STATUSES
    assert "merged" in DIAGNOSIS_STATUSES


@pytest.mark.asyncio
async def test_dedup_same_key_folds_into_canonical(monkeypatch) -> None:
    """2e run identique → pas de 2e incident open : occurrences=2 + marqueur."""
    import app.services.learning.diagnostician as diag
    fake, calls = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    oid1 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    oid2 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did1 = await diag.diagnose_execution(oid1)
    did2 = await diag.diagnose_execution(oid2)

    assert did2 == did1                    # la garde retourne le canonique
    assert calls["n"] == 1                 # le doublon n'a PAS re-payé le LLM

    rows = {r.execution_outcome_id: r for r in await _diagnoses(uid)}
    canonical, marker = rows[oid1], rows[oid2]
    assert canonical.status == "open"
    assert canonical.occurrences == 2
    assert canonical.last_seen_at is not None
    assert marker.status == "merged"       # 1 run = 1 ligne → le cron n'y revient pas
    assert marker.occurrences == 1
    assert f"#{did1}" in (marker.resolution or "")


@pytest.mark.asyncio
async def test_dedup_different_source_id_creates_new_incident(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag
    fake, calls = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    oid1 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-1")
    oid2 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-2")
    did1 = await diag.diagnose_execution(oid1)
    did2 = await diag.diagnose_execution(oid2)

    assert did1 != did2
    assert calls["n"] == 2                 # deux clés → deux diagnoses complètes
    rows = await _diagnoses(uid)
    assert sorted(r.status for r in rows) == ["open", "open"]
    assert all(r.occurrences == 1 for r in rows)


@pytest.mark.asyncio
async def test_dedup_different_category_creates_new_incident(monkeypatch) -> None:
    import app.services.learning.diagnostician as diag

    async def _boom(prompt, user_id=None):
        raise RuntimeError("llm down")
    monkeypatch.setattr(diag, "_call_diagnostician_llm", _boom)

    uid = await _seed_user()
    oid1 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    oid2 = await _seed_outcome(uid, signals=["claimed_no_tool"], source_id="task-42")
    await diag.diagnose_execution(oid1)    # rule_cat=prompt
    await diag.diagnose_execution(oid2)    # rule_cat=binding → autre clé

    rows = await _diagnoses(uid)
    assert sorted(r.status for r in rows) == ["open", "open"]


@pytest.mark.asyncio
async def test_dedup_reopens_after_human_resolution(monkeypatch) -> None:
    """Résolu puis re-échec → NOUVEL incident open (le problème est revenu)."""
    import app.services.learning.diagnostician as diag
    from app.database import async_session
    from app.models.execution_diagnosis import ExecutionDiagnosis
    fake, _ = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    oid1 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did1 = await diag.diagnose_execution(oid1)
    async with async_session() as db:
        row = (await db.execute(select(ExecutionDiagnosis).where(
            ExecutionDiagnosis.id == did1))).scalar_one()
        row.status = "validated"
        await db.commit()

    oid2 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did2 = await diag.diagnose_execution(oid2)

    assert did2 is not None and did2 != did1
    rows = {r.id: r for r in await _diagnoses(uid)}
    assert rows[did2].status == "open"
    assert rows[did2].occurrences == 1


@pytest.mark.asyncio
async def test_dedup_folds_existing_backlog(monkeypatch) -> None:
    """Les doublons open préexistants se replient en 1 au run suivant."""
    import app.services.learning.diagnostician as diag
    fake, calls = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    d1 = await _seed_open_diagnosis(uid, source_id="task-42")
    d2 = await _seed_open_diagnosis(uid, source_id="task-42")
    d3 = await _seed_open_diagnosis(uid, source_id="task-42")

    oid = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did = await diag.diagnose_execution(oid)

    assert did == d1                       # canonique = le plus ancien
    assert calls["n"] == 0                 # pas de LLM pour un doublon
    rows = await _diagnoses(uid)
    open_rows = [r for r in rows if r.status == "open"]
    merged = [r for r in rows if r.status == "merged"]
    assert len(open_rows) == 1 and open_rows[0].id == d1
    assert open_rows[0].occurrences == 4   # 1 + 2 repliés + 1 run courant
    assert len(merged) == 3                # d2, d3 + le marqueur du run courant
    assert {d2, d3} <= {r.id for r in merged}


@pytest.mark.asyncio
async def test_dedup_canonical_prefers_incident_with_patch(monkeypatch) -> None:
    """Le repli garde l'incident qui porte un correctif (pas d'orphelin)."""
    import app.services.learning.diagnostician as diag
    from app.database import async_session
    from app.models.proposed_patch import ProposedPatch
    fake, _ = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    d1 = await _seed_open_diagnosis(uid, source_id="task-42")
    d2 = await _seed_open_diagnosis(uid, source_id="task-42")
    async with async_session() as db:
        db.add(ProposedPatch(execution_diagnosis_id=d2, user_id=uid,
                             target_id="task-42", new_value="prompt corrigé"))
        await db.commit()

    oid = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did = await diag.diagnose_execution(oid)

    assert did == d2                       # d2 porte le patch → canonique
    rows = {r.id: r for r in await _diagnoses(uid)}
    assert rows[d2].status == "open"
    assert rows[d2].occurrences == 3       # 1 + d1 replié + run courant
    assert rows[d1].status == "merged"


@pytest.mark.asyncio
async def test_cron_does_not_reprocess_deduped_outcomes(monkeypatch) -> None:
    """Le marqueur merged sort l'outcome doublon du radar du cron."""
    import app.services.learning.diagnostician as diag
    fake, calls = _counting_llm()
    monkeypatch.setattr(diag, "_call_diagnostician_llm", fake)

    uid = await _seed_user()
    oid1 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    oid2 = await _seed_outcome(uid, signals=["no_write_effect"], source_id="task-42")
    did1 = await diag.diagnose_execution(oid1)
    await diag.diagnose_execution(oid2)
    assert len(await _diagnoses(uid)) == 2

    await diag.run_pending_diagnoses(batch_limit=500)   # tick suivant

    rows = {r.id: r for r in await _diagnoses(uid)}
    assert len(rows) == 2                  # rien de re-créé
    assert rows[did1].occurrences == 2     # PAS re-gonflé par le cron
