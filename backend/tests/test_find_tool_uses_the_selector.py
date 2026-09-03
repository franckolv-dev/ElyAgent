# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_find_tool_uses_the_selector.py
# @brief      L'annuaire d'Ely lit les descriptions au lieu de compter des mots.
# @license    MIT
# =============================================================================
"""``find_tool`` se trompait une fois sur deux — mesuré le 29/07/2026.

    « convertir un PDF en Word »          → pdf_to_docx        ✓
    « créer un événement dans l'agenda »  → **trainer_start**  ✗

``_rank_capability`` combine un score lexical et un score sémantique. Sur une
demande formulée naturellement, aucun des deux ne retrouve le bon outil : ni
« créer », ni « événement », ni « agenda » n'apparaissent dans la description
de ``calendar_create_event``, et l'embedding place ``trainer_start`` devant.

Pourquoi c'est grave
---------------------
``find_tool`` est l'ANNUAIRE : le seul moyen, pour Ely, de retrouver un outil
qui n'est pas branché au tour. Quand il se trompe, elle conclut de bonne foi
qu'elle n'a pas l'outil — et depuis #300, un gap consigné peut même déclencher
la fabrication d'un outil qui existait déjà.

Ce que ce lot change
---------------------
Un petit modèle local **lit** les descriptions. Mesuré sur ``gemma-4-E4B`` :
4/4 en ~1,1 s, à coût nul. ``find_tool`` étant appelé rarement, la seconde de
latence est sans importance — c'est ce qui rend ce branchement-ci sûr, alors
que filtrer À CHAQUE TOUR poserait la question du cache de prompt.

⚠️ Le classement lexical reste le REPLI, jamais l'inverse : sélecteur absent,
lent ou muet → on retombe sur le comportement d'avant, qui trouvait quand même
la moitié des cas.

Run with:  cd backend && python -m pytest tests/test_find_tool_uses_the_selector.py -v
"""
from __future__ import annotations

import pytest


@pytest.fixture
def catalogue(monkeypatch):
    """Le catalogue complet, et un classement lexical qui se trompe."""
    async def _noop():
        return None

    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill._ensure_catalog", _noop,
    )

    async def _rank_faux(capability, k):
        # Exactement ce que le vrai classement rend aujourd'hui pour
        # « créer un événement dans l'agenda ».
        return ["trainer_start", "notes_create"]

    monkeypatch.setattr(
        "app.skills.builtin.find_tool_skill._rank_capability", _rank_faux,
    )


@pytest.mark.asyncio
async def test_the_model_selection_wins_over_the_lexical_ranking(catalogue, monkeypatch):
    """LE pin du lot : le modèle voit `calendar_create_event` là où le
    classement lexical propose `trainer_start`."""
    async def _select(query, tools, *, include_core: bool = True):
        class _T:
            name = "calendar_create_event"

        return [_T()]

    monkeypatch.setattr("app.agent.tool_selector.select_tools", _select)
    from app.skills.builtin.find_tool_skill import find_tool

    out = await find_tool.ainvoke({"capability": "créer un événement dans l'agenda"})

    assert "calendar_create_event" in out
    assert "trainer_start" not in out


@pytest.mark.asyncio
async def test_the_lexical_ranking_remains_the_fallback(catalogue, monkeypatch):
    """Sélecteur indisponible → on retombe sur le comportement d'avant, qui
    trouvait quand même la moitié des cas. Jamais sur rien."""
    async def _broken(query, tools, *, include_core: bool = True):
        raise RuntimeError("LM Studio éteint")

    monkeypatch.setattr("app.agent.tool_selector.select_tools", _broken)
    from app.skills.builtin.find_tool_skill import find_tool

    out = await find_tool.ainvoke({"capability": "créer un événement"})

    assert "trainer_start" in out, "le repli lexical n'a pas joué"


@pytest.mark.asyncio
async def test_a_selector_that_returns_everything_is_not_a_selection(
    catalogue, monkeypatch,
):
    """``select_tools`` rend la liste COMPLÈTE quand il échoue ouvert. La
    prendre pour une réponse ferait afficher les 200 outils comme « les plus
    pertinents » — pire que le classement lexical."""
    async def _tout(query, tools, *, include_core: bool = True):
        return list(tools)

    monkeypatch.setattr("app.agent.tool_selector.select_tools", _tout)
    from app.skills.builtin.find_tool_skill import find_tool

    out = await find_tool.ainvoke({"capability": "créer un événement"})

    assert out.count("•") <= 10, "toute la liste a été rendue comme pertinente"
