# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_detached_spawn.py
# @brief      C4-2d — spawn(detach_context=True) : les tâches de fond à
#             appels LLM propres n'héritent pas du contexte de l'appelant.
# @license    MIT
# =============================================================================
"""Bug réel (19/07/2026, test B live) : ``create_task`` hérite des contextvars
de l'appelant, et LangChain propage son arbre de callbacks par contextvars —
les tokens du générateur tier-S (tâche de fond lancée DANS le tour de chat)
sont partis dans le stream WebSocket de l'utilisateur, entrelacés caractère
par caractère avec la réponse d'Ely.

Run with:  cd backend && python -m pytest tests/test_detached_spawn.py -v
"""
from __future__ import annotations

import asyncio
import contextvars

import pytest

from app.services.background_tasks import spawn

_LEAK_PROBE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "leak_probe", default="vierge")


@pytest.mark.asyncio
async def test_default_spawn_inherits_context():
    """Comportement historique conservé : sans détachement, le contexte de
    l'appelant est visible (c'est ce dont dépendent LEARNED_TOOL_USER_ID &
    co sur les chemins synchrones au tour)."""
    _LEAK_PROBE.set("contexte-du-tour")

    async def _read() -> str:
        return _LEAK_PROBE.get()

    assert await spawn(_read()) == "contexte-du-tour"


@pytest.mark.asyncio
async def test_detached_spawn_starts_from_a_clean_context():
    """detach_context=True : la tâche NE voit PAS les contextvars du tour —
    donc pas non plus l'arbre de callbacks LangChain qui routait les tokens
    du LLM de fond vers le stream de l'appelant."""
    _LEAK_PROBE.set("contexte-du-tour")

    async def _read() -> str:
        return _LEAK_PROBE.get()

    assert await spawn(_read(), detach_context=True) == "vierge"


@pytest.mark.asyncio
async def test_detached_spawn_still_logs_and_tracks(caplog):
    """Le contrat de spawn (référence forte + exceptions loggées) tient
    aussi en mode détaché."""

    async def _boom() -> None:
        raise RuntimeError("explosion contrôlée")

    with caplog.at_level("WARNING", logger="app.services.background_tasks"):
        task = spawn(_boom(), label="bg-test-detached", detach_context=True)
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)  # laisse le done-callback tourner
    assert any("bg-test-detached" in r.message for r in caplog.records)


def test_generation_spawn_is_detached():
    """Pin : le déclencheur d'auto-génération DOIT être détaché — c'est le
    site du bug (tokens tier-S dans le chat de l'utilisateur)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] /
           "app/skills/builtin/find_tool_skill.py").read_text(encoding="utf-8")
    assert "detach_context=True" in src