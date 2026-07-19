# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_llm_deadline.py
# @brief      C3d-2 — échéance murale par appel LLM : contrat helper + câblage.
# @license    Elastic License 2.0
# =============================================================================
"""Échéances murales (C3d-2).

Contexte (18/07/2026) : un appel de synthèse sous-agent a pendu 907 s — le
timeout httpx du client codex est PAR LECTURE (un SSE qui goutte ne le
déclenche jamais) et aucun site d'appel LLM n'avait d'échéance totale.

Contrat central pinné ici : le ``TimeoutError`` levé par
``ainvoke_with_deadline`` doit être classé ``FailoverReason.TIMEOUT`` par
``classify_exception`` — c'est CE couplage qui fait qu'une échéance dépassée
déclenche la rotation de chaîne existante (chantier4) sans câblage de plus.

Run with:  cd backend && python -m pytest tests/test_llm_deadline.py -v
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.llm_deadline import ainvoke_with_deadline, deadline_for_tier

_REPO = Path(__file__).resolve().parents[1]


class _FastLLM:
    async def ainvoke(self, payload):
        return {"echo": payload}


class _HungLLM:
    """Simule le stream codex qui goutte : ne rend JAMAIS la main."""

    cancelled = False

    async def ainvoke(self, payload):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            _HungLLM.cancelled = True
            raise


# ── Helper — comportement ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_call_passes_through():
    out = await ainvoke_with_deadline(_FastLLM(), "ping", timeout_s=5.0)
    assert out == {"echo": "ping"}


@pytest.mark.asyncio
async def test_hung_call_raises_timeout_and_cancels():
    _HungLLM.cancelled = False
    with pytest.raises(TimeoutError) as exc_info:
        await ainvoke_with_deadline(_HungLLM(), "ping", timeout_s=0.05, surface="test")
    assert "timed out" in str(exc_info.value)
    assert "surface=test" in str(exc_info.value)
    await asyncio.sleep(0)  # laisse la cancellation se propager
    assert _HungLLM.cancelled, "wait_for doit ANNULER l'appel sous-jacent (libère la connexion)"


@pytest.mark.asyncio
async def test_deadline_error_is_classified_timeout_for_rotation():
    """LE contrat C3d-2 : échéance dépassée ⇒ FailoverReason.TIMEOUT ⇒ la
    rotation de chaîne (fallback_manager) se déclenche comme sur un vrai
    timeout réseau."""
    from app.services.fallback_manager import FailoverReason, classify_exception

    with pytest.raises(TimeoutError) as exc_info:
        await ainvoke_with_deadline(_HungLLM(), "ping", timeout_s=0.05)
    assert classify_exception(exc_info.value) is FailoverReason.TIMEOUT


# ── deadline_for_tier ───────────────────────────────────────────────────────


def test_deadline_for_tier_mapping():
    from app.config import get_settings
    from app.services.llm_provider import ComplexityTier

    s = get_settings()
    assert deadline_for_tier(ComplexityTier.SIMPLE) == s.llm_deadline_simple_s
    assert deadline_for_tier(ComplexityTier.MEDIUM) == s.llm_deadline_medium_s
    assert deadline_for_tier(ComplexityTier.COMPLEX) == s.llm_deadline_complex_s
    # IMAGE = génération potentiellement longue → borne complex.
    assert deadline_for_tier(ComplexityTier.IMAGE) == s.llm_deadline_complex_s
    # Inconnu / None → MEDIUM (défaut sûr).
    assert deadline_for_tier(None) == s.llm_deadline_medium_s
    assert deadline_for_tier("n_importe_quoi") == s.llm_deadline_medium_s


def test_settings_defaults():
    from app.config import get_settings

    s = get_settings()
    assert s.llm_deadline_simple_s == 30.0
    assert s.llm_deadline_medium_s == 120.0
    assert s.llm_deadline_complex_s == 240.0
    assert s.llm_deadline_mission_act_s == 180.0
    assert s.llm_deadline_router_s == 10.0


# ── Pins de câblage — chaque famille de sites passe par le helper ───────────


@pytest.mark.parametrize("rel_path", [
    "app/agent/nodes.py",                # général : primaire + retry + 2 fallbacks
    "app/agent/sub_agents/factory.py",   # sous-agents : primaire + 2 fallbacks
    "app/agent/missions/nodes.py",       # missions : plan/act/eval
    "app/agent/supervisor.py",           # routeur passe-2 (échéance courte)
    "app/agent/tools/orchestrate_tool.py",
    "app/agent/force_summary.py",
])
def test_llm_call_sites_use_wall_deadline(rel_path: str):
    src = (_REPO / rel_path).read_text(encoding="utf-8")
    assert "ainvoke_with_deadline(" in src, (
        f"{rel_path} doit envelopper ses appels LLM dans ainvoke_with_deadline "
        "(échéance murale C3d-2) — un ainvoke nu peut pendre indéfiniment."
    )
