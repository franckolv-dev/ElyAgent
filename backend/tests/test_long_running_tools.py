# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_long_running_tools.py
# @brief      Un outil long ne bloque plus un tour de chat : il bascule en
#             tâche de fond, l'utilisateur est prévenu, le travail est livré.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Garde-fou « outil long » — générique à TOUS les outils (natifs et MCP).

Incident fondateur (24/07) : `translate_pdf_folder` a tourné **2 h 52** dans
un tour de chat. L'utilisatrice n'a rien vu, la WebSocket est morte bien
avant, et le résultat — pourtant réussi — n'a jamais été livré.

Le contrat posé ici : sur une surface INTERACTIVE, aucun outil ne monopolise
le tour au-delà d'un budget court. Passé ce budget, l'exécution **continue en
tâche de fond** (rien n'est tué : c'est ce qui distingue ce garde-fou d'un
simple timeout), le modèle reçoit un accusé qui lui dit quoi répondre, et le
résultat est livré à l'arrivée — message persisté dans la conversation,
notification push, et reprise du raisonnement pour finir la demande.

Les surfaces NON interactives (missions, tâches planifiées) gardent le droit
d'attendre : elles sont faites pour les travaux longs et ont leurs propres
budgets.

Run with:  cd backend && python -m pytest tests/test_long_running_tools.py -v
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.long_running_tools import (
    HANDOFF_NOTICE_MARKER,
    describe_pending_job,
    invoke_with_handoff,
    pending_jobs_for_conversation,
)

_REPO = Path(__file__).resolve().parents[1]


class _Tool:
    """Outil factice : `delay` secondes avant de rendre `value`."""

    def __init__(self, name: str, delay: float, value: str = "OK"):
        self.name = name
        self._delay = delay
        self._value = value
        self.started = 0

    async def ainvoke(self, args):
        self.started += 1
        await asyncio.sleep(self._delay)
        return self._value


class _Ctx:
    """GatewayContext minimal (duck-typing — le service ne lit que ça)."""

    def __init__(self, interactive=True, conversation_id="conv-1", user_id="u1"):
        self.interactive = interactive
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.label = ""
        self.user_request = "traduis ce PDF en néerlandais"


@pytest.fixture(autouse=True)
def _fast_budget(monkeypatch):
    """Budget minuscule pour que les tests restent instantanés."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "long_tool_handoff_enabled", True)
    monkeypatch.setattr(get_settings(), "long_tool_soft_deadline_s", 0.05)


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch):
    """Neutralise la livraison réelle (DB/ntfy/agent) — testée à part."""
    delivered: list = []

    async def _fake_deliver(job):
        delivered.append(job)

    monkeypatch.setattr(
        "app.services.long_running_tools._deliver_result", _fake_deliver,
    )
    return delivered


# ────────────────────────────────────────────────────────────────────────
# Le chemin normal reste STRICTEMENT inchangé
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_tool_returns_normally():
    tool = _Tool("weather_get", delay=0.0, value="21°C")
    result, notice = await invoke_with_handoff(_Ctx(), "weather_get", tool, {})
    assert notice is None
    assert result == "21°C"


@pytest.mark.asyncio
async def test_tool_exception_still_propagates():
    """Une erreur d'outil doit remonter comme avant — le garde-fou ne doit
    pas transformer un échec en succès silencieux."""
    class _Boom:
        name = "boom"
        async def ainvoke(self, args):
            raise ValueError("l'API a refusé")

    with pytest.raises(ValueError, match="refusé"):
        await invoke_with_handoff(_Ctx(), "boom", _Boom(), {})


@pytest.mark.asyncio
async def test_non_interactive_surface_never_hands_off():
    """Une mission ou une tâche planifiée a le droit d'attendre."""
    tool = _Tool("translate_pdf_folder", delay=0.2, value="traduit")
    result, notice = await invoke_with_handoff(
        _Ctx(interactive=False), "translate_pdf_folder", tool, {},
    )
    assert notice is None
    assert result == "traduit"


@pytest.mark.asyncio
async def test_disabled_flag_restores_legacy_behaviour(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "long_tool_handoff_enabled", False)
    tool = _Tool("slow", delay=0.2, value="fini")
    result, notice = await invoke_with_handoff(_Ctx(), "slow", tool, {})
    assert notice is None
    assert result == "fini"


# ────────────────────────────────────────────────────────────────────────
# La bascule elle-même
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slow_tool_hands_off_without_being_killed(_no_delivery):
    """LE test de l'incident : l'outil dépasse le budget → le tour est rendu
    tout de suite, MAIS l'outil continue et son résultat est livré."""
    tool = _Tool("translate_pdf_folder", delay=0.3, value="PDF traduit")
    result, notice = await invoke_with_handoff(
        _Ctx(), "translate_pdf_folder", tool, {"input_dir": "/x"},
    )
    assert result is None
    assert notice is not None
    assert HANDOFF_NOTICE_MARKER in notice
    assert "translate_pdf_folder" in notice

    # L'outil n'a PAS été annulé : on attend sa vraie fin.
    await asyncio.sleep(0.4)
    assert len(_no_delivery) == 1, "le résultat doit être livré, pas jeté"
    assert _no_delivery[0].result == "PDF traduit"
    assert _no_delivery[0].tool_name == "translate_pdf_folder"
    assert tool.started == 1, "l'outil ne doit tourner qu'une fois"


@pytest.mark.asyncio
async def test_handoff_notice_tells_the_model_what_to_do(_no_delivery):
    """Le message rendu au modèle doit être actionnable : dire que ça tourne,
    interdire de relancer, et annoncer la notification."""
    tool = _Tool("translate_pdf_folder", delay=0.3)
    _r, notice = await invoke_with_handoff(_Ctx(), "translate_pdf_folder", tool, {})
    low = notice.lower()
    assert "arrière-plan" in low or "tâche de fond" in low
    assert "relance" in low          # « ne relance pas »
    assert "prévenu" in low or "notifi" in low
    await asyncio.sleep(0.35)


@pytest.mark.asyncio
async def test_failed_background_job_is_delivered_too(_no_delivery):
    """Un échec en tâche de fond doit être livré AUSSI — sinon l'utilisateur
    attend un résultat qui ne viendra jamais (le silence est le pire cas)."""
    class _SlowBoom:
        name = "slow_boom"
        async def ainvoke(self, args):
            await asyncio.sleep(0.2)
            raise RuntimeError("quota dépassé")

    _r, notice = await invoke_with_handoff(_Ctx(), "slow_boom", _SlowBoom(), {})
    assert notice is not None
    await asyncio.sleep(0.35)
    assert len(_no_delivery) == 1
    job = _no_delivery[0]
    assert job.ok is False
    assert "quota" in (job.error or "")


@pytest.mark.asyncio
async def test_pending_jobs_are_visible_per_conversation(_no_delivery):
    """Ely doit pouvoir dire « c'est toujours en cours » si on lui redemande."""
    tool = _Tool("translate_pdf_folder", delay=0.3)
    ctx = _Ctx(conversation_id="conv-abc")
    await invoke_with_handoff(ctx, "translate_pdf_folder", tool, {})

    pending = pending_jobs_for_conversation("conv-abc")
    assert len(pending) == 1
    assert pending[0].tool_name == "translate_pdf_folder"
    assert "translate_pdf_folder" in describe_pending_job(pending[0])
    assert pending_jobs_for_conversation("autre-conv") == []

    await asyncio.sleep(0.4)
    # Terminé → le job sort de la liste des travaux en cours
    assert pending_jobs_for_conversation("conv-abc") == []


@pytest.mark.asyncio
async def test_same_tool_and_args_is_not_started_twice(_no_delivery):
    """Anti-doublon : si le modèle relance le même appel pendant que le job
    tourne, on ne relance pas 3 h de travail — on rappelle qu'il tourne."""
    tool = _Tool("translate_pdf_folder", delay=0.3)
    ctx = _Ctx(conversation_id="conv-dup")
    args = {"input_dir": "/x", "target_language": "nl"}

    _r1, n1 = await invoke_with_handoff(ctx, "translate_pdf_folder", tool, args)
    _r2, n2 = await invoke_with_handoff(ctx, "translate_pdf_folder", tool, dict(args))

    assert n1 is not None and n2 is not None
    assert "déjà" in n2.lower()
    assert tool.started == 1, "le second appel ne doit PAS relancer l'outil"
    await asyncio.sleep(0.4)
    assert len(_no_delivery) == 1


# ────────────────────────────────────────────────────────────────────────
# Câblage : passerelle, contexte, prompt
# ────────────────────────────────────────────────────────────────────────


def test_gateway_uses_the_handoff():
    src = (_REPO / "app/services/tool_gateway.py").read_text(encoding="utf-8")
    assert "invoke_with_handoff" in src, (
        "la passerelle est le point unique par lequel TOUS les outils passent "
        "(chat, sous-agents, missions) — le garde-fou doit y vivre pour être "
        "générique aux outils natifs ET MCP"
    )


def test_gateway_context_carries_interactivity():
    src = (_REPO / "app/services/tool_gateway.py").read_text(encoding="utf-8")
    assert "interactive" in src


def test_chat_marks_the_surface_interactive_and_scheduler_does_not():
    src = (_REPO / "app/agent/tool_node.py").read_text(encoding="utf-8")
    assert "interactive=" in src
    # Le scheduler passe par le MÊME nœud avec automated_task=True : c'est ce
    # drapeau qui doit distinguer les deux, pas une surface en dur.
    assert "automated_task" in src


def test_prompt_tells_ely_to_announce_long_operations():
    """La règle doit exister ET apprendre au modèle à lire l'accusé de
    bascule — sinon il croit à un échec et relance 3 h de travail.
    (Formulation libre : le prompt a un plafond de 15 k, il doit rester
    resserrable sans casser ce pin.)"""
    src = (_REPO / "app/agent/prompts.py").read_text(encoding="utf-8")
    assert "Opérations longues" in src
    assert HANDOFF_NOTICE_MARKER in src, (
        "le prompt doit nommer le marqueur exact que la passerelle renvoie"
    )
    rule = src.split("Opérations longues", 1)[1][:600]
    assert "relance" in rule.lower()
