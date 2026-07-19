# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_auto_tool_generation.py
# @brief      C4-2 — auto-génération sur capacité manquante : garde-fous,
#             pré-check anti-doublon, notification, câblages.
# @license    Elastic License 2.0
# =============================================================================
"""C4-2 — le « vrai auto de bout en bout » (backlog #57, enfin câblé).

La boucle validée : gap consigné → génération AUTOMATIQUE d'un candidate
(tier-S) → notification push → validation HUMAINE → binding. Ces tests
verrouillent les garde-fous : flag kill-switch, une tentative par gap et par
boot, pré-check sémantique anti-doublon (leçon Drive/Sheets : un « outil
manquant » est presque toujours un trou de binding), sortie jamais auto-promue.

Run with:  cd backend && python -m pytest tests/test_auto_tool_generation.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.learning import auto_tool_generation as atg

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_attempts():
    atg.reset_attempts()
    yield
    atg.reset_attempts()


def _patch_flag(monkeypatch, enabled: bool):
    from app.config import get_settings

    # get_settings est lru_cached → patcher l'INSTANCE partagée (un attribut
    # de classe serait masqué par le champ pydantic de l'instance).
    monkeypatch.setattr(get_settings(), "auto_tool_generation_enabled", enabled)


class _Recorder:
    def __init__(self, result=None):
        self.calls: list = []
        self._result = result

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result


# ── Garde-fous ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_off_short_circuits(monkeypatch):
    _patch_flag(monkeypatch, False)
    gen = _Recorder({"status": "created"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", gen)
    assert await atg.maybe_generate_for_gap(1, "capacité x", "u1") is None
    assert gen.calls == []


@pytest.mark.asyncio
async def test_one_attempt_per_gap_per_boot(monkeypatch):
    _patch_flag(monkeypatch, True)
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Recorder(None))
    gen = _Recorder({"status": "validation_failed"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", gen)
    await atg.maybe_generate_for_gap(42, "téléporter sur mars", "u1")
    await atg.maybe_generate_for_gap(42, "téléporter sur mars", "u1")  # dédup
    assert len(gen.calls) == 1, "un gap re-consigné ne re-brûle pas du tier-S"


@pytest.mark.asyncio
async def test_existing_tool_blocks_generation(monkeypatch):
    """Leçon Drive/Sheets : outil existant trouvé → trou de binding, pas de
    génération (et pas de doublon fabriqué)."""
    _patch_flag(monkeypatch, True)
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Recorder("sheets_read_spreadsheet"))
    gen = _Recorder({"status": "created"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", gen)
    assert await atg.maybe_generate_for_gap(7, "lire un google sheet", "u1") is None
    assert gen.calls == []


@pytest.mark.asyncio
async def test_created_candidate_notifies(monkeypatch):
    _patch_flag(monkeypatch, True)
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Recorder(None))
    gen = _Recorder({"status": "created", "tool_name": "pdf_to_docx"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", gen)
    notify = _Recorder(None)
    monkeypatch.setattr(
        "app.services.learning.candidate_notify.notify_candidate", notify)
    out = await atg.maybe_generate_for_gap(9, "convertir un pdf en docx", "u1")
    assert out and out["status"] == "created"
    assert len(gen.calls) == 1
    assert len(notify.calls) == 1
    # Le lien gap↔candidate part avec la génération.
    assert gen.calls[0][1]["from_failure_case_ids"] == [9]


@pytest.mark.asyncio
async def test_failed_generation_stays_silent(monkeypatch):
    """Pas de notification d'échec (bruit) — le gap reste ouvert, le bouton
    manuel demeure."""
    _patch_flag(monkeypatch, True)
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Recorder(None))
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool",
        _Recorder({"status": "validation_failed"}))
    notify = _Recorder(None)
    monkeypatch.setattr(
        "app.services.learning.candidate_notify.notify_candidate", notify)
    out = await atg.maybe_generate_for_gap(11, "capacité qui rate", "u1")
    assert out and out["status"] == "validation_failed"
    assert notify.calls == []


# ── Pré-check réel (catalogue) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capability_precheck_real_catalog():
    from app.skills.builtin import find_tool_skill as fts
    from app.skills.builtin import register_all
    from app.skills.builtin.find_tool_skill import capability_has_existing_tool

    register_all()          # peuple le catalogue builtin complet (pattern #56)
    fts._catalog_sig = None  # force le rebuild

    hit = await capability_has_existing_tool("lire un google sheet existant")
    assert hit is not None, "les outils Sheets existent — trou de binding détecté"
    miss = await capability_has_existing_tool("zzz introuvable xyzzy frobnicator")
    assert miss is None


# ── Notification (transport) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_is_noop_without_ntfy_url(monkeypatch):
    monkeypatch.delenv("NTFY_URL", raising=False)
    from app.services.learning.candidate_notify import notify_candidate

    await notify_candidate("outil_x", "capacité y")  # ne lève pas, no-op


# ── Pins de câblage ─────────────────────────────────────────────────────────


def test_find_tool_spawns_generation_on_gap():
    src = (_REPO / "app/skills/builtin/find_tool_skill.py").read_text(encoding="utf-8")
    assert "maybe_generate_for_gap" in src, (
        "Le no-match de find_tool doit déclencher l'auto-génération — "
        "c'est LE déclencheur du funnel (vision validée 19/07)."
    )
    assert "démarre automatiquement" in src, (
        "Le message utilisateur doit annoncer la génération automatique "
        "quand le flag est actif."
    )


def test_admin_endpoint_has_semantic_precheck():
    src = (_REPO / "app/routers/learning_skills.py").read_text(encoding="utf-8")
    assert "capability_has_existing_tool" in src, (
        "L'endpoint /tool-creator/run doit pré-vérifier le catalogue avant "
        "de dépenser du tier-S (trou identifié par la carte C4)."
    )
    assert '"status": "exists"' in src


def test_skill_autocreate_notifies_promotions():
    src = (_REPO / "app/services/learning/skill_autocreate.py").read_text(encoding="utf-8")
    assert "notify_playbook_activated" in src, (
        "L'auto-promotion des playbooks est conservée mais ne doit plus être "
        "silencieuse (arbitrage 19/07)."
    )


# ── C4-2b — report_missing_capability (le déclencheur RÉALISTE) ─────────────
# Un vrai gap a presque toujours des faux-matchs faibles (« pdf » ⊂ outils
# pdf non pertinents) : le no-match strict de find_tool ne suffit pas — le
# modèle doit pouvoir CONSIGNER son jugement de non-pertinence.


@pytest.mark.asyncio
async def test_report_refuses_when_existing_tool_covers(monkeypatch):
    from app.skills.builtin import find_tool_skill as fts

    monkeypatch.setattr(fts, "capability_has_existing_tool", _Recorder("sheets_read_spreadsheet"))
    rec = _Recorder("ne doit pas être appelé")
    monkeypatch.setattr(fts, "_record_gap_and_trigger", rec)
    out = await fts.report_missing_capability.ainvoke(
        {"capability": "lire un google sheet"})
    assert "sheets_read_spreadsheet" in out and "non consigné" in out
    assert rec.calls == []


@pytest.mark.asyncio
async def test_report_records_and_triggers_on_real_gap(monkeypatch):
    from app.skills.builtin import find_tool_skill as fts

    monkeypatch.setattr(fts, "capability_has_existing_tool", _Recorder(None))
    rec = _Recorder("consigné — génération lancée")
    monkeypatch.setattr(fts, "_record_gap_and_trigger", rec)
    out = await fts.report_missing_capability.ainvoke(
        {"capability": "convertir un pdf en docx"})
    assert out == "consigné — génération lancée"
    assert len(rec.calls) == 1


@pytest.mark.asyncio
async def test_report_requires_a_description():
    from app.skills.builtin import find_tool_skill as fts

    out = await fts.report_missing_capability.ainvoke({"capability": "  "})
    assert "Précise" in out


def test_report_tool_is_bound_and_prompted():
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    assert "report_missing_capability" in _DEFAULT_TOOLS, (
        "L'outil de consignation doit être toujours bindé (comme find_tool) — "
        "un déclencheur invisible est un funnel mort."
    )
    prompts = (_REPO / "app/agent/prompts.py").read_text(encoding="utf-8")
    assert "report_missing_capability" in prompts, (
        "Le prompt doit dire QUAND l'appeler : résultats de find_tool non "
        "pertinents → consigner."
    )
