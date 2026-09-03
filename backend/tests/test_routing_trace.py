# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_routing_trace.py
# @brief      C3d-4 — RoutingDecision traçable : contrat note() + câblage.
# @license    MIT
# =============================================================================
"""C3d-4.

Diagnostics 18-19/07 : les décisions de routage n'existaient qu'en logs texte
épars — il a fallu déduire le tier d'un sous-agent du NOM du modèle pour
comprendre le bug #210. Désormais chaque décision émet un EventEnvelope
``kind=routing`` (ring + log JSON + OTel, attributs assainis P1) et une ligne
compacte « [routing] conv=… aspect=décision ».

Run with:  cd backend && python -m pytest tests/test_routing_trace.py -v
"""
from __future__ import annotations

from pathlib import Path

from app.services import routing_trace
from app.services.event_envelope import _RING, EventKind

_REPO = Path(__file__).resolve().parents[1]


def _last_routing_event():
    for env in reversed(_RING):
        if env.kind is EventKind.ROUTING:
            return env
    return None


# ── Contrat note() ──────────────────────────────────────────────────────────


def test_note_emits_routing_envelope_with_decision_and_attrs():
    routing_trace.note(
        "conv-rt-abcdef123", "turn",
        user_id="u1", decision="medium",
        chain_len=3, active_idx=0, provider="openai_codex",
    )
    env = _last_routing_event()
    assert env is not None
    assert env.capability_id == "turn"
    assert env.outcome == "medium"
    assert env.attributes["conv"] == "conv-rt-"          # tronqué à 8
    assert env.attributes["chain_len"] == 3
    assert env.attributes["provider"] == "openai_codex"
    assert env.user_id_hash and env.user_id_hash != "u1"  # jamais l'id brut


def test_note_logs_compact_line(caplog):
    with caplog.at_level("INFO", logger="app.services.routing_trace"):
        routing_trace.note("conv-log-1", "switch", decision="deepseek",
                           reason="timeout")
    assert any(
        "[routing]" in r.message and "switch=deepseek" in r.message
        and "reason=timeout" in r.message
        for r in caplog.records
    )


def test_note_never_raises(monkeypatch):
    """La trace ne casse JAMAIS un tour — même si l'émission explose."""
    import app.services.event_envelope as ee

    def _boom(*_a, **_k):
        raise RuntimeError("emit down")

    monkeypatch.setattr(ee, "emit", _boom)
    routing_trace.note("conv-boom", "turn", decision="simple")  # ne lève pas


def test_unknown_aspect_tolerated():
    routing_trace.note("conv-unk", "aspect_futur", decision="x")
    env = _last_routing_event()
    assert env is not None and env.capability_id == "aspect_futur"


def test_routing_kind_exists():
    assert EventKind.ROUTING.value == "routing"


# ── Pins de câblage — les 5 familles de décisions émettent ──────────────────


def test_general_node_traces_slm_and_turn():
    src = (_REPO / "app/agent/nodes.py").read_text(encoding="utf-8")
    assert "routing_trace" in src and src.count("routing_note(") >= 2, (
        "agent_node doit tracer le choix SLM-vs-cloud ET le départ de tour "
        "(tier + chaîne + position) — c'étaient les décisions invisibles du 18/07."
    )


def test_fallback_manager_traces_switches():
    src = (_REPO / "app/services/fallback_manager.py").read_text(encoding="utf-8")
    assert "routing_trace" in src, (
        "try_activate doit émettre la bascule (from→to→reason) et l'épuisement "
        "de chaîne en événement structuré, pas seulement en log texte."
    )
