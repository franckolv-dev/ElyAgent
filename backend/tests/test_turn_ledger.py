# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_turn_ledger.py
# @brief      C3d-3 — registre de tour + fallback honnête + classification
#             unifiée des rotations LLM.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""C3d-3.

Exhibits 18/07/2026 (×4) : sous-agent mort APRÈS un gmail_list_emails réussi
→ le fallback général repartait de zéro et confabulait « accès Gmail
indisponible ». Ce lot : (1) la passerelle mémorise les résultats d'outils du
tour (registre borné, version anonymisée) ; (2) le fallback du superviseur
hérite de ces résultats + consigne « échec TECHNIQUE » ; (3) les trois
systèmes de rotation partagent classify_exception (la liste inline de la
factory ignorait « timed out » → un dépassement d'échéance C3d-2 tuait le
sous-agent au lieu de tourner).

Run with:  cd backend && python -m pytest tests/test_turn_ledger.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

from app.services import turn_ledger
from app.services.turn_ledger import technical_failure_notice

_REPO = Path(__file__).resolve().parents[1]


def _conv(n: str) -> str:
    return f"conv-ledger-{n}"


# ── Registre — comportement ─────────────────────────────────────────────────


def test_record_entries_clear_roundtrip():
    c = _conv("rt")
    turn_ledger.clear(c)
    turn_ledger.record(c, "gmail_list_emails", "De: a@b — Objet: facture")
    turn_ledger.record(c, "web_search", "3 résultats…")
    assert turn_ledger.entries(c) == [
        ("gmail_list_emails", "De: a@b — Objet: facture"),
        ("web_search", "3 résultats…"),
    ]
    turn_ledger.clear(c)
    assert turn_ledger.entries(c) == []


def test_record_truncates_and_bounds():
    c = _conv("bounds")
    turn_ledger.clear(c)
    turn_ledger.record(c, "big", "x" * 10_000)
    assert len(turn_ledger.entries(c)[0][1]) == 400
    for i in range(100):
        turn_ledger.record(c, f"t{i}", "r")
    assert len(turn_ledger.entries(c)) == 24  # borne par conversation
    turn_ledger.clear(c)


def test_record_is_safe_on_falsy_ids():
    turn_ledger.record("", "tool", "r")      # no-op
    turn_ledger.record(_conv("ok"), "", "r")  # no-op
    assert turn_ledger.entries("") == []
    turn_ledger.clear("")                     # no-op, ne lève pas


# ── Avis d'échec technique ──────────────────────────────────────────────────


def test_notice_forbids_access_confabulation_and_lists_results():
    txt = technical_failure_notice(
        "workspace", "timeout",
        [("gmail_list_emails", "De: a@b — Objet: facture")],
    )
    assert "TECHNIQUE" in txt
    assert "timeout" in txt
    assert "accès" in txt.lower()          # la consigne anti « pas d'accès »
    assert "gmail_list_emails" in txt      # l'héritage des résultats
    assert "facture" in txt


def test_notice_without_results_asks_to_retry_tools():
    txt = technical_failure_notice("research", "rate_limit", [])
    assert "TECHNIQUE" in txt
    assert "réessaie" in txt.lower()


# ── Pins de câblage ─────────────────────────────────────────────────────────


def test_gateway_records_successful_results():
    src = (_REPO / "app/services/tool_gateway.py").read_text(encoding="utf-8")
    assert "turn_ledger" in src, (
        "La passerelle doit mémoriser les résultats d'outils réussis dans le "
        "registre de tour (fallback honnête C3d-3)."
    )


def test_missions_log_classified_reason():
    src = (_REPO / "app/agent/missions/nodes.py").read_text(encoding="utf-8")
    assert "classify_exception" in src, (
        "L'except de l'acteur mission doit au moins classer la raison "
        "(observabilité de la rotation)."
    )


def test_unified_classifier_covers_wall_deadline():
    """Le lien C3d-2 ↔ C3d-3 : un dépassement d'échéance murale doit être
    reconnu par le classificateur unifié (la liste inline de la factory ne
    le reconnaissait PAS)."""
    from app.services.fallback_manager import FailoverReason, classify_exception

    exc = TimeoutError("LLM call timed out after 120s (wall-clock deadline, surface=sub-agent:workspace)")
    assert classify_exception(exc) is FailoverReason.TIMEOUT


def test_notice_is_pure_and_importable_from_supervisor():
    """Garde anti-cycle : turn_ledger ne doit importer AUCUN module agent."""
    import app.services.turn_ledger as tl

    src = inspect.getsource(tl)
    assert "from app.agent" not in src and "import app.agent" not in src
