# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pdf_plan_retries_empty_window.py
# @brief      Le gabarit du prompt écrivait <identifiant> — le modèle rendait
#             <p1b0>, et une réponse PARFAITE était jetée une fois sur deux.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le défaut mesuré juste après #294 — et le faux diagnostic qu'il a failli
faire livrer.

Ce qui a été observé
---------------------
Sur 12 appels réels à GPT-5.6 Terra, MÊME document, MÊME prompt :
**6 tranches sur 12 sans aucune décision exploitable.** Aucune erreur, aucun
``finish_reason``, aucun timeout (l'échéance du tier complex est à 240 s).

Le premier diagnostic — « le modèle rend parfois du vide » — était **FAUX**.
Les réponses en échec faisaient 481 à 560 caractères. Lues intégralement :

    <p1b0> TITRE1 SAUT CENTRE
    <p1b1> TITRE2 CENTRE
    <p1b4> ARTEFACT

Un balisage **parfaitement correct**, aux chevrons près. Et la cause est dans
le prompt d'Ely, pas dans le modèle : le gabarit écrivait

    <identifiant> <RÔLE> [ATTRIBUTS]

Le modèle reproduisait les chevrons — lecture parfaitement raisonnable d'une
notation qui ne dit pas qu'ils sont un méta-symbole.

⚠️ **La leçon, réutilisable.** On allait livrer une « reprise sur tranche
vide » : elle aurait masqué un défaut d'écriture au prix d'appels doublés, et
le taux d'échec serait passé de 50 % à 25 % au lieu de tomber à zéro. **Lire la
réponse en entier avant de conclure sur sa forme** — « 0 décision » ne veut pas
dire « 0 caractère ».

Ce que ce lot corrige
----------------------
1. **Le gabarit du prompt** — un exemple littéral, plus aucun méta-symbole à
   recopier par erreur.
2. **Le parseur, tolérant aux décorations** — un modèle en ajoutera toujours
   d'une façon ou d'une autre ; jeter un balisage juste pour des chevrons est
   un échec d'Ely, pas du modèle.
3. **Une reprise par tranche**, conservée — elle ne sert plus à rattraper ce
   défaut-là mais les pannes réseau, et elle ne coûte rien au cas nominal.

Run with:  cd backend && python -m pytest tests/test_pdf_plan_retries_empty_window.py -v
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz", reason="pymupdf requis pour ces pins")


def _doc(pages: int = 1):
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 100.0
        for i in range(3):
            page.insert_text((72.0, y), f"Page {p + 1} ligne {i} du texte courant.",
                             fontsize=11.0, fontname="helv")
            y += 14.0
    return doc


class _Scripted:
    """Un faux LLM qui joue une suite de réponses préparées."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls = 0

    async def ainvoke(self, payload, **kwargs):
        self.calls += 1
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]

        class _R:
            content = reply

        return _R()


def _install(monkeypatch, llm):
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda tier: llm,
    )


# ─────────────────────────────────────────────────────────────────────
# LA cause réelle : les chevrons du gabarit
# ─────────────────────────────────────────────────────────────────────


def test_a_block_id_wrapped_in_angle_brackets_is_read():
    """LE pin de ce lot. Réponse réelle de GPT-5.6, jetée en entier avant."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan(
        "<p1b0> TITRE1 SAUT CENTRE\n"
        "<p1b4> ARTEFACT\n"
        "<p8b0> CORPS SUITE\n"
    )

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.breaks_before("p1b0") is True
    assert plan.role_of("p1b4") == "ARTEFACT"
    assert plan.continues("p8b0") is True


def test_other_decorations_are_tolerated_too():
    """Un modèle décorera toujours d'une façon ou d'une autre. Jeter un
    balisage juste pour une puce est un échec d'Ely, pas du modèle."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan(
        "- p1b0 TITRE1\n"
        "* [p1b1] CORPS\n"
        "`p1b2` ARTEFACT\n"
    )

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.role_of("p1b1") == "CORPS"
    assert plan.role_of("p1b2") == "ARTEFACT"


def test_the_prompt_template_shows_no_meta_symbol_to_copy():
    """La cause première. Le gabarit écrivait `<identifiant> <RÔLE>` : le
    modèle recopiait les chevrons une fois sur deux."""
    from app.services.pdf_plan_llm import _PROMPT

    assert "<identifiant>" not in _PROMPT
    assert "<RÔLE>" not in _PROMPT


# ─────────────────────────────────────────────────────────────────────
# La reprise — le filet, pas la correction
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_empty_window_is_asked_again(monkeypatch):
    """Reste utile pour les pannes réseau et les réponses hors contrat."""
    llm = _Scripted("", "p1b0 TITRE1 SAUT\n")
    _install(monkeypatch, llm)
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    plan = await request_conversion_plan(extract_layout(_doc()), requirements="")

    assert llm.calls == 2, f"{llm.calls} appel(s) — la tranche vide n'a pas été redemandée"
    assert plan.role_of("p1b0") == "TITRE1"


@pytest.mark.asyncio
async def test_a_window_that_answers_costs_a_single_call(monkeypatch):
    """La reprise ne doit rien coûter au cas nominal — sur 27 tranches, un
    appel de trop par tranche double la facture pour rien."""
    llm = _Scripted("p1b0 TITRE1 SAUT\n")
    _install(monkeypatch, llm)
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    await request_conversion_plan(extract_layout(_doc()), requirements="")

    assert llm.calls == 1


@pytest.mark.asyncio
async def test_two_empty_answers_stop_the_retries(monkeypatch):
    """Pas de boucle. Un modèle muet deux fois ne le sera pas moins la
    troisième — c'est la leçon d'`is_making_progress` (#289)."""
    llm = _Scripted("", "")
    _install(monkeypatch, llm)
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    plan = await request_conversion_plan(extract_layout(_doc()), requirements="")

    assert llm.calls == 2
    assert plan.is_empty is True


@pytest.mark.asyncio
async def test_a_window_that_errors_is_also_retried(monkeypatch):
    """Une coupure réseau mérite le même geste qu'une réponse vide : les deux
    laissent la tranche sans décision alors que le modèle sait la traiter."""

    class _FlakyThenFine:
        calls = 0

        async def ainvoke(self, payload, **kwargs):
            _FlakyThenFine.calls += 1
            if _FlakyThenFine.calls == 1:
                raise RuntimeError("coupure réseau")

            class _R:
                content = "p1b0 TITRE1 SAUT\n"

            return _R()

    _install(monkeypatch, _FlakyThenFine())
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    plan = await request_conversion_plan(extract_layout(_doc()), requirements="")

    assert _FlakyThenFine.calls == 2
    assert plan.role_of("p1b0") == "TITRE1"


@pytest.mark.asyncio
async def test_an_off_contract_answer_is_retried_too(monkeypatch):
    """« Je n'ai pas compris » n'est pas une décision de structure. Sans
    reprise, ce bavardage vaudrait abandon de la tranche."""
    llm = _Scripted("Je ne suis pas sûr de comprendre la demande.",
                    "p1b0 TITRE1 SAUT\n")
    _install(monkeypatch, llm)
    from app.services.pdf_layout import extract_layout
    from app.services.pdf_plan_llm import request_conversion_plan

    plan = await request_conversion_plan(extract_layout(_doc()), requirements="")

    assert llm.calls == 2
    assert plan.role_of("p1b0") == "TITRE1"
