# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pdf_plan_delegated_to_model.py
# @brief      Ely DONNE le travail de structure au modèle cloud — c'est lui qui
#             décide, elle contrôle.
# @license    MIT
# =============================================================================
"""La consigne de Franck, du 28/07/2026, verrouillée par des pins.

    « Fais en sorte qu'elle délègue le travail à un LLM cloud. On a configuré
      des modèles par complexité de travail, il faut qu'elle les utilise et
      qu'elle arrête de faire le travail elle-même. Elle est là pour donner
      aux bons modèles, avec les bonnes instructions et pour contrôler le
      travail fait. »

Ce qui rendait cette consigne inatteignable
--------------------------------------------
``pdf_to_docx(source, output_name)`` : deux arguments, aucun n'est une
exigence. Ce que Franck écrit — « respecte les sauts de page », « garde les
polices » — n'avait **aucun chemin** pour descendre jusqu'au travail. Le modèle
choisissait d'appeler l'outil et rapportait son résultat ; il n'a jamais vu ces
PDF. Cinq essais de reformulation l'ont montré.

Ces pins verrouillent le chemin qui manquait
---------------------------------------------
- les exigences de l'utilisateur arrivent **dans le prompt du modèle** ;
- le modèle reçoit la géométrie réelle du document, pas une description ;
- le manuscrit est découpé en tranches — 395 pages ne tiennent pas dans une
  fenêtre de contexte, et refuser de découper reviendrait à ne rien déléguer ;
- **échouer OUVERT** : modèle en panne, quota épuisé, réponse illisible → plan
  vide → la conversion d'avant. Une délégation cassée ne doit jamais rendre un
  document pire que celui d'hier.

⚠️ Piège vécu le 28/07 et couvert ici
--------------------------------------
Un stub à ``**kwargs`` avale n'importe quoi et masque une signature
incompatible : le test passait au vert pendant que la production levait un
``TypeError``. D'où le dernier pin de ce fichier, qui appelle la VRAIE
``ainvoke_with_deadline``.

Run with:  cd backend && python -m pytest tests/test_pdf_plan_delegated_to_model.py -v
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz", reason="pymupdf requis pour ces pins")

_BODY_SIZE = 11.0
_LINE_PITCH = 14.0


def _doc(pages: int = 1, lines_per_page: int = 3):
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 100.0
        for i in range(lines_per_page):
            page.insert_text((72.0, y), f"Page {p + 1} ligne {i} du texte courant.",
                             fontsize=_BODY_SIZE, fontname="helv")
            y += _LINE_PITCH
    return doc


class _Recorder:
    """Un faux LLM qui NOTE ce qu'on lui envoie, au lieu de le simuler."""

    def __init__(self, reply: str = "p1b0 CORPS\n"):
        self.reply = reply
        self.prompts: list[str] = []
        self.configs: list[dict | None] = []

    async def ainvoke(self, payload, **kwargs):
        text = payload[0].content if isinstance(payload, list) else str(payload)
        self.prompts.append(text)
        self.configs.append(kwargs.get("config"))

        class _R:
            content = self.reply

        return _R()


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: rec,
    )
    return rec


# ─────────────────────────────────────────────────────────────────────
# Le chemin qui manquait : la demande de Franck atteint le travail
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_user_requirements_reach_the_model(recorder):
    """LE pin du lot. Avant, cette phrase mourait dans le chat."""
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=1))
    await request_conversion_plan(
        layout, requirements="Respecte scrupuleusement les sauts de page du PDF.",
    )

    assert recorder.prompts, "aucun appel au modèle n'a été fait"
    assert "sauts de page du PDF" in recorder.prompts[0]


@pytest.mark.asyncio
async def test_the_model_receives_the_real_geometry(recorder):
    """Le modèle n'a jamais vu ces PDF. On ne lui demande pas d'imaginer un
    document : on lui donne les blocs mesurés, avec leurs identifiants."""
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=2))
    await request_conversion_plan(layout, requirements="")

    joined = "\n".join(recorder.prompts)
    assert "p1b0" in joined
    assert "PAGE 1" in joined and "PAGE 2" in joined


@pytest.mark.asyncio
async def test_the_answer_becomes_a_usable_plan(recorder):
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    recorder.reply = "p1b0 TITRE1 SAUT\n"
    layout = extract_layout(_doc(pages=1))
    plan = await request_conversion_plan(layout, requirements="")

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.breaks_before("p1b0") is True


# ─────────────────────────────────────────────────────────────────────
# L'échelle : 395 pages ne tiennent pas dans une fenêtre
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_long_document_is_cut_into_windows(recorder, monkeypatch):
    """Refuser de découper reviendrait à ne rien déléguer du tout sur le seul
    document qui a motivé ce lot."""
    monkeypatch.setattr("app.services.pdf_plan_llm.PAGES_PER_WINDOW", 2)
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=6))
    await request_conversion_plan(layout, requirements="")

    assert len(recorder.prompts) == 3, f"{len(recorder.prompts)} appel(s) pour 6 pages"


@pytest.mark.asyncio
async def test_the_decisions_of_every_window_are_kept(monkeypatch):
    """Une tranche perdue, c'est un tiers du manuscrit qui retombe au défaut
    sans que personne ne le sache."""
    monkeypatch.setattr("app.services.pdf_plan_llm.PAGES_PER_WINDOW", 2)

    replies = iter(["p1b0 TITRE1\n", "p3b0 CORPS SAUT\n", "p5b0 ARTEFACT\n"])

    class _PerWindow:
        async def ainvoke(self, payload, **kwargs):
            class _R:
                content = next(replies)

            return _R()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _PerWindow(),
    )
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=6))
    plan = await request_conversion_plan(layout, requirements="")

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.breaks_before("p3b0") is True
    assert plan.role_of("p5b0") == "ARTEFACT"


# ─────────────────────────────────────────────────────────────────────
# Échouer OUVERT
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_model_failure_yields_an_empty_plan(monkeypatch):
    """Un plan vide = la conversion d'hier. Jamais un document mutilé."""

    class _Broken:
        async def ainvoke(self, payload, **kwargs):
            raise RuntimeError("quota épuisé")

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _Broken(),
    )
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=1))
    plan = await request_conversion_plan(layout, requirements="")

    assert plan.is_empty is True


@pytest.mark.asyncio
async def test_no_model_at_all_yields_an_empty_plan(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: None,
    )
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=1))
    plan = await request_conversion_plan(layout, requirements="")

    assert plan.is_empty is True


@pytest.mark.asyncio
async def test_one_broken_window_does_not_lose_the_others(monkeypatch):
    """Sur 16 tranches, une panne passagère ne doit pas jeter les 15 autres."""
    monkeypatch.setattr("app.services.pdf_plan_llm.PAGES_PER_WINDOW", 2)

    calls = {"n": 0}

    class _Flaky:
        async def ainvoke(self, payload, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("coupure réseau")

            class _R:
                content = "p1b0 TITRE1\n"

            return _R()

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: _Flaky(),
    )
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=4))
    plan = await request_conversion_plan(layout, requirements="")

    assert plan.role_of("p1b0") == "TITRE1"


# ─────────────────────────────────────────────────────────────────────
# Les tokens du plan ne doivent PAS s'afficher chez l'utilisateur
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_call_cuts_the_callback_tree(recorder):
    """Bug réel du 19/07 : sans ``config={"callbacks": []}``, LangChain propage
    l'arbre par contextvars et les tokens de cet appel s'entrelacent caractère
    par caractère dans la réponse de l'utilisateur."""
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    layout = extract_layout(_doc(pages=1))
    await request_conversion_plan(layout, requirements="")

    assert recorder.configs[0] == {"callbacks": []}


@pytest.mark.asyncio
async def test_the_real_deadline_helper_accepts_this_call_shape():
    """Le doublon du piège du 28/07 : les pins ci-dessus stubbent le LLM, donc
    ils ne prouvent PAS que la vraie ``ainvoke_with_deadline`` accepte cette
    forme d'appel. Un stub permissif avait déjà masqué un ``TypeError`` garanti
    en production."""
    from app.services.llm_deadline import ainvoke_with_deadline

    class _Echo:
        async def ainvoke(self, payload, **kwargs):
            class _R:
                content = "p1b0 CORPS\n"

            return _R()

    result = await ainvoke_with_deadline(
        _Echo(), ["peu importe"],
        tier="complex", surface="pdf-plan", config={"callbacks": []},
    )
    assert result.content == "p1b0 CORPS\n"
