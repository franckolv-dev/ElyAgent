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


@pytest.fixture(autouse=True)
def _gate_says_tool(monkeypatch):
    """La garde OUTIL/COMPÉTENCE (lot du 29/07) répond « outil ».

    Ces pins portent sur la GÉNÉRATION — déclenchement, unicité par gap,
    notification. Sans ce stub ils mesureraient la garde, qui rend False dès
    qu'aucun modèle de niveau S n'est joignable : ils passeraient au vert pour
    la mauvaise raison, en ne générant jamais rien.
    """
    async def _yes(capability, **kwargs):
        return True

    monkeypatch.setattr(
        "app.services.learning.tool_or_skill.needs_a_tool", _yes,
    )

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
async def test_generation_skips_precheck_when_model_judged(monkeypatch):
    """skip_precheck=True (chemin report_missing_capability) : le modèle a
    déjà jugé — le pré-check lexical ne re-bloque pas la génération."""
    _patch_flag(monkeypatch, True)
    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill.capability_has_existing_tool",
        _Recorder("drive_export_file"))  # bloquerait sans skip
    gen = _Recorder({"status": "validation_failed"})
    monkeypatch.setattr(
        "app.services.learning.tool_creator.generate_and_persist_tool", gen)
    out = await atg.maybe_generate_for_gap(
        77, "convertir un pdf en docx", "u1", skip_precheck=True)
    assert out is not None and len(gen.calls) == 1


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
    # NB (C4-2c) : le pré-check reste un juge LEXICAL — sur « convertir un
    # pdf en docx » il peut légitimement pointer un voisin (drive_export_file
    # exporte des Docs en pdf/docx). C'est pourquoi il n'a PAS de droit de
    # veto sur le chemin report_missing_capability (jugé par le modèle) —
    # contrat pinné par test_report_records_despite_lexical_neighbor.
    # Auto-empoisonnement pinné : les méta-outils du funnel ne sont JAMAIS
    # candidats (le docstring de report_missing_capability contient l'exemple
    # pdf→docx mot pour mot et se retrouvait « outil existant » à 1.0).
    meta = await capability_has_existing_tool(
        "consigner une capacité manquante et générer un outil candidat")
    assert meta not in {"find_tool", "report_missing_capability"}


# ── Notification (transport) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_is_noop_without_ntfy_url(monkeypatch):
    monkeypatch.delenv("NTFY_URL", raising=False)
    from app.services.learning.candidate_notify import notify_candidate

    await notify_candidate("outil_x", "capacité y")  # ne lève pas, no-op


# ── Pins de câblage ─────────────────────────────────────────────────────────


def test_find_tool_spawns_generation_on_gap():
    """⚠️ LA SECONDE ASSERTION A ÉTÉ RECENTRÉE (24/08), pas affaiblie.

    Elle cherchait la formule exacte « démarre automatiquement ». Le message a
    dû changer : depuis que la branche « compétence » de l'aiguillage écrit un
    playbook au lieu de ne rien faire, promettre « un outil candidat » est
    devenu FAUX — c'est une procédure OU un outil, et c'est `needs_a_tool` qui
    tranche, après ce message.

    L'invariant que ce pin défend n'est pas une tournure : c'est que
    l'utilisateur soit prévenu qu'une rédaction démarre toute seule. On vise
    donc ça, et on interdit explicitement la promesse trop étroite.
    """
    src = (_REPO / "app/skills/builtin/find_tool_skill.py").read_text(encoding="utf-8")
    assert "maybe_generate_for_gap" in src, (
        "Le no-match de find_tool doit déclencher l'auto-génération — "
        "c'est LE déclencheur du funnel (vision validée 19/07)."
    )
    assert "en cours de rédaction" in src, (
        "Le message utilisateur doit annoncer qu'une rédaction démarre "
        "d'elle-même quand le flag est actif."
    )
    assert "d'un outil candidat démarre" not in src, (
        "le message promet un OUTIL alors qu'une procédure peut arriver — "
        "le modèle attendrait une capacité appelable qui ne viendra pas"
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
async def test_report_records_despite_lexical_neighbor(monkeypatch):
    """Le pré-check lexical n'a PAS de droit de veto sur le jugement du
    modèle (leçon 19/07 : drive_export_file bloquait le gap PDF→DOCX
    fondateur à 0,67 de couverture). Il devient un CAVEAT informatif."""
    from app.skills.builtin import find_tool_skill as fts

    monkeypatch.setattr(fts, "capability_has_existing_tool", _Recorder("drive_export_file"))
    rec = _Recorder("Capacité consignée — génération lancée.")
    monkeypatch.setattr(fts, "_record_gap_and_trigger", rec)
    out = await fts.report_missing_capability.ainvoke(
        {"capability": "convertir un fichier pdf en docx"})
    assert "consignée" in out, "le gap DOIT être consigné malgré le voisin lexical"
    assert "drive_export_file" in out, "le voisin lexical est signalé en caveat"
    assert len(rec.calls) == 1
    assert rec.calls[0][1].get("model_judged") is True, (
        "la génération issue du jugement modèle saute le pré-check (pas de "
        "double veto)"
    )


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
