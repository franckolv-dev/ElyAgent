# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_selector.py
# @brief      Un petit modèle local LIT les descriptions et choisit les outils
#             pertinents — au lieu d'envoyer les 85 à chaque tour.
# @license    MIT
# =============================================================================
"""Le contexte d'un tour ordinaire, mesuré le 29/07/2026.

    15 567 tool_defs +   427 conversation +   910 mcp + 1 033 système
    = 17 937 tokens  →  87 % du contexte, ce sont les DESCRIPTIONS D'OUTILS

Les 85 outils du profil partent à chaque tour, quelle que soit la demande. Et
comme la boucle d'outils renvoie tout le contexte à chaque itération, ces
15 567 tokens sont **repayés à chaque tour de boucle** (même mécanisme
quadratique que #301).

Pourquoi le filtre par mots-clés existant ne convenait pas
------------------------------------------------------------
``filter_tools_by_query`` coupe bien (85 → 8-30), mais mesuré sur les vraies
demandes de Franck :

- il **coupe ``find_tool``** dans 5 cas sur 6 — or c'est l'annuaire, le seul
  moyen de retrouver un outil coupé. Sans lui, « je n'ai pas l'outil » ;
- il ne comprend pas les demandes naturelles : « cale un déjeuner avec Gert »
  ne matche ni ``calendar`` ni ``agenda`` → 85/85 gardés, aucun gain.

C'est le mécanisme qui a produit le bug de #287. On ne le rebranche pas.

Ce que ce lot fait à la place
-------------------------------
Un **modèle local lit les descriptions**. Mesuré sur `gemma-4-E4B` :

    « cale un déjeuner avec Gert »  → calendar_quick_add · …   ✓  1,1 s
    « convertis ce PDF en Word »    → pdf_to_docx · …          ✓  1,0 s
    « nettoie ma boîte mail »       → gmail_search_for_cleanup ✓  1,2 s
    « dépose ce fichier sur Drive » → drive_upload_local_file  ✓  1,1 s

4/4, en une seconde, à coût nul. Le même sélecteur fiabilise ``find_tool``,
qui répondait ``trainer_start`` à « créer un événement dans l'agenda ».

⚠️ Échouer OUVERT
------------------
Sélecteur absent, lent, ou réponse illisible → **on garde les 85 outils**,
c'est-à-dire le comportement d'aujourd'hui. Un tour un peu plus lourd vaut
infiniment mieux qu'un « je n'ai pas l'outil ».

Run with:  cd backend && python -m pytest tests/test_tool_selector.py -v
"""
from __future__ import annotations

import pytest


class _Tool:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


def _tools() -> list[_Tool]:
    return [
        _Tool("pdf_to_docx", "Convert a text-based PDF into a real .docx file.\nLong detail."),
        _Tool("pdf_read", "Read and extract raw text from a PDF file."),
        _Tool("calendar_create_event", "Create an event in Google Calendar."),
        _Tool("gmail_send_email", "Send an email via Gmail."),
        _Tool("drive_upload_local_file", "Upload a local file to Google Drive."),
        _Tool("find_tool", "Find which tool covers a capability."),
        _Tool("memory_recall", "Recall typed memories."),
    ]


@pytest.fixture
def selector(monkeypatch):
    """Un faux modèle local qui rend une sélection choisie par le test."""
    def _install(reply: str):
        class _LLM:
            prompts: list[str] = []

            async def ainvoke(self, payload, **kwargs):
                _LLM.prompts.append(
                    payload[0].content if isinstance(payload, list) else str(payload)
                )

                class _R:
                    content = reply

                return _R()

        llm = _LLM()
        monkeypatch.setattr(
            "app.agent.tool_selector._selector_llm", lambda: llm,
        )
        return llm
    return _install


# ─────────────────────────────────────────────────────────────────────
# L'annuaire donné au sélecteur
# ─────────────────────────────────────────────────────────────────────


def test_the_directory_keeps_one_line_per_tool():
    """Envoyer les descriptions complètes au sélecteur reviendrait à payer ce
    qu'on cherche à économiser. Une ligne suffit à reconnaître un outil."""
    from app.agent.tool_selector import build_directory

    annuaire = build_directory(_tools())

    assert "pdf_to_docx" in annuaire
    assert "Long detail" not in annuaire, "la 2e ligne de description est passée"
    assert len(annuaire.splitlines()) == len(_tools())


def test_the_directory_stays_small_for_the_whole_catalogue():
    """Mesuré sur les 207 outils réels : 16 738 caractères, ~4 184 tokens.
    C'est le prix d'entrée du sélecteur — il doit rester très inférieur aux
    15 567 tokens qu'il fait économiser."""
    from app.agent.tool_selector import build_directory

    beaucoup = [_Tool(f"outil_{i}", "Description ordinaire d'un outil." ) for i in range(207)]
    assert len(build_directory(beaucoup)) < 30_000


# ─────────────────────────────────────────────────────────────────────
# La sélection
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_the_relevant_tools_are_kept(selector):
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx\npdf_read")
    gardes = await select_tools("convertis ce PDF en Word", _tools())

    noms = {t.name for t in gardes}
    assert "pdf_to_docx" in noms
    assert "gmail_send_email" not in noms


@pytest.mark.asyncio
async def test_the_query_and_the_directory_reach_the_model(selector):
    from app.agent.tool_selector import select_tools

    llm = selector("pdf_to_docx")
    await select_tools("convertis ce PDF", _tools())

    prompt = llm.prompts[0]
    assert "convertis ce PDF" in prompt
    assert "pdf_to_docx" in prompt


@pytest.mark.asyncio
async def test_an_invented_tool_name_is_ignored(selector):
    """Un modèle local invente parfois un nom plausible. Le garder ferait
    planter le binding, ou pire, laisserait croire à un outil qui n'existe pas."""
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx\npdf_magique_qui_nexiste_pas")
    noms = {t.name for t in await select_tools("convertis", _tools())}

    assert "pdf_to_docx" in noms
    assert not any("magique" in n for n in noms)


# ─────────────────────────────────────────────────────────────────────
# Le noyau — ce qui reste branché quoi qu'il arrive
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_tool_is_always_kept(selector):
    """LE garde-fou. ``find_tool`` est le seul moyen de retrouver un outil que
    le sélecteur aurait coupé à tort. Le filtre par mots-clés le coupait dans
    5 cas sur 6 — c'est précisément ce qui rendait ce filtre dangereux."""
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx")           # le modèle ne le demande pas
    noms = {t.name for t in await select_tools("convertis ce PDF", _tools())}

    assert "find_tool" in noms


@pytest.mark.asyncio
async def test_the_core_can_be_left_out_when_asked(selector):
    """Le noyau sert à BRANCHER un tour — garder le filet sous la main. Il n'a
    rien à faire dans une réponse d'annuaire : proposer ``find_tool`` comme
    réponse à « quel outil pour X » est une boucle, et ``memory_recall``
    pollue. Défaut vu à l'essai réel, pas par les pins."""
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx")
    noms = {t.name for t in await select_tools(
        "convertis ce PDF", _tools(), include_core=False,
    )}

    assert noms == {"pdf_to_docx"}


@pytest.mark.asyncio
async def test_the_core_survives_an_unrelated_query(selector):
    from app.agent.tool_selector import CORE_TOOLS, select_tools

    selector("gmail_send_email")
    noms = {t.name for t in await select_tools("envoie un mail", _tools())}

    for attendu in CORE_TOOLS & {t.name for t in _tools()}:
        assert attendu in noms, f"{attendu} devrait rester dans le noyau"


# ─────────────────────────────────────────────────────────────────────
# Échouer OUVERT — jamais « je n'ai pas l'outil »
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_selector_keeps_every_tool(monkeypatch):
    """Aucun modèle local disponible → comportement d'aujourd'hui, à
    l'identique."""
    monkeypatch.setattr("app.agent.tool_selector._selector_llm", lambda: None)
    from app.agent.tool_selector import select_tools

    assert len(await select_tools("peu importe", _tools())) == len(_tools())


@pytest.mark.asyncio
async def test_a_broken_selector_keeps_every_tool(monkeypatch):
    class _Broken:
        async def ainvoke(self, payload, **kwargs):
            raise RuntimeError("LM Studio éteint")

    monkeypatch.setattr("app.agent.tool_selector._selector_llm", lambda: _Broken())
    from app.agent.tool_selector import select_tools

    assert len(await select_tools("peu importe", _tools())) == len(_tools())


@pytest.mark.asyncio
async def test_an_unreadable_answer_keeps_every_tool(selector):
    """Le modèle bavarde au lieu de lister : on ne devine pas, on garde tout."""
    from app.agent.tool_selector import select_tools

    selector("Je pense qu'il faudrait plutôt utiliser un traitement de texte.")
    assert len(await select_tools("convertis", _tools())) == len(_tools())


@pytest.mark.asyncio
async def test_a_selection_that_matches_nothing_keeps_every_tool(selector):
    """Si aucun nom rendu n'existe, la sélection ne vaut rien — mieux vaut le
    contexte lourd d'hier qu'un agent désarmé."""
    from app.agent.tool_selector import select_tools

    selector("outil_a\noutil_b\noutil_c")
    assert len(await select_tools("convertis", _tools())) == len(_tools())


@pytest.mark.asyncio
async def test_an_empty_query_keeps_every_tool(selector):
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx")
    assert len(await select_tools("", _tools())) == len(_tools())


# ─────────────────────────────────────────────────────────────────────
# Le gain
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_selection_actually_reduces_the_list(selector):
    """Le but du lot : 85 outils envoyés à chaque tour, il n'en faut qu'une
    poignée."""
    from app.agent.tool_selector import select_tools

    selector("pdf_to_docx\npdf_read")
    gardes = await select_tools("convertis ce PDF en Word", _tools())

    assert len(gardes) < len(_tools())
