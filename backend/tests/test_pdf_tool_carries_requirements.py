# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pdf_tool_carries_requirements.py
# @brief      La signature de l'outil laisse enfin passer les exigences de
#             l'utilisateur, et le rapport dit ce qui a été décidé.
# @license    Elastic License 2.0
# =============================================================================
"""Le goulot mesuré, et sa levée.

    signature réelle au 28/07/2026 : pdf_to_docx(source, output_name)

Deux arguments : un chemin, un nom de fichier. **Aucun ne peut porter une
exigence.** Franck a écrit cinq fois « respecte les sauts de page », « garde
les polices » : ces phrases s'arrêtaient au chat. Le modèle choisissait
d'appeler l'outil, l'outil convertissait selon ses seuils, et le modèle
rapportait le résultat. Il n'a jamais vu le PDF. Affiner le prompt ne pouvait
rien y changer — ce n'était pas un problème de formulation.

Ces pins verrouillent les deux extrémités du chemin
----------------------------------------------------
- **en entrée** : ``requirements`` existe, et ce qu'il contient arrive
  réellement au modèle qui décide de la structure ;
- **en sortie** : le rapport de l'outil dit ce qui a été décidé — sauts de
  page, artefacts retirés, intégrité. C'est ce que la boucle de conformité
  (#288/#289) confronte à la demande pour relancer sur un écart NOMMÉ.

Run with:  cd backend && python -m pytest tests/test_pdf_tool_carries_requirements.py -v
"""
from __future__ import annotations

import inspect

import pytest

fitz = pytest.importorskip("fitz", reason="pymupdf requis pour ces pins")


def _pdf(tmp_path, pages: int = 2, name: str = "source"):
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 100.0
        for i in range(4):
            page.insert_text((72.0, y), f"Page {p + 1} ligne {i} du texte courant.",
                             fontsize=11.0, fontname="helv")
            y += 14.0
        page.insert_text((300.0, 780.0), str(p + 1), fontsize=9.0, fontname="helv")
    path = tmp_path / f"{name}.pdf"
    doc.save(str(path))
    return path


@pytest.fixture
def spy(monkeypatch):
    """Note les exigences reçues par la couche de délégation."""
    seen: dict = {}

    async def _fake_plan(layout, requirements="", **kwargs):
        from app.services.pdf_layout import parse_conversion_plan

        seen["requirements"] = requirements
        seen["pages"] = layout.page_count
        return parse_conversion_plan("p2b0 CORPS SAUT\np1b1 ARTEFACT\n")

    monkeypatch.setattr(
        "app.services.pdf_plan_llm.request_conversion_plan", _fake_plan,
    )
    return seen


# ─────────────────────────────────────────────────────────────────────
# En entrée : le goulot
# ─────────────────────────────────────────────────────────────────────


def test_the_tool_accepts_requirements():
    """LE fait mesuré du lot : cet argument n'existait pas.

    Vérifié sur ``args_schema`` — le contrat que le modèle voit réellement —
    et pas sur la signature Python : un argument absent du schéma serait
    inatteignable même s'il existait dans le code.
    """
    from app.agent.tools.pdf_tool import pdf_to_docx

    fields = pdf_to_docx.args_schema.model_fields
    assert "requirements" in fields, f"schéma exposé : {list(fields)}"

    coroutine = pdf_to_docx.coroutine
    params = inspect.signature(coroutine).parameters
    assert "requirements" in params, f"signature : {list(params)}"


def test_the_tool_description_tells_the_model_to_pass_them():
    """Un argument que le modèle ne sait pas remplir ne sert à rien. La
    description est la seule chose qu'il lit avant d'appeler."""
    from app.agent.tools.pdf_tool import pdf_to_docx

    assert "requirements" in (pdf_to_docx.description or "")


@pytest.mark.asyncio
async def test_what_the_user_asked_reaches_the_model(tmp_path, spy):
    """Le bout du chemin. Cette phrase de Franck mourait dans le chat."""
    from app.agent.tools.pdf_tool import pdf_to_docx

    await pdf_to_docx.ainvoke({
        "source": str(_pdf(tmp_path)),
        "output_name": "sortie",
        "requirements": "Respecte les sauts de page du PDF source.",
    })

    assert spy["requirements"] == "Respecte les sauts de page du PDF source."


@pytest.mark.asyncio
async def test_the_conversion_still_works_without_requirements(tmp_path, spy):
    """Rétrocompatibilité : les appels existants n'en passent pas."""
    from app.agent.tools.pdf_tool import pdf_to_docx

    out = await pdf_to_docx.ainvoke({"source": str(_pdf(tmp_path))})

    assert "Document Word créé" in out
    assert spy["requirements"] == ""


# ─────────────────────────────────────────────────────────────────────
# En sortie : de quoi juger, donc de quoi relancer
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_report_states_the_page_breaks(tmp_path, spy):
    """« Les sauts de page du PDF source sont respectés » ne se vérifie que si
    le nombre de sauts est DIT. Le juge de conformité lit ce texte-là."""
    from app.agent.tools.pdf_tool import pdf_to_docx

    out = await pdf_to_docx.ainvoke({
        "source": str(_pdf(tmp_path)),
        "requirements": "Respecte les sauts de page.",
    })

    assert "saut" in out.lower()
    assert "1" in out


@pytest.mark.asyncio
async def test_the_report_states_what_was_removed(tmp_path, spy):
    """Retirer du texte sans le dire est exactement la façade que ce projet
    traque. Les folios sortent — et l'utilisateur l'apprend."""
    from app.agent.tools.pdf_tool import pdf_to_docx

    out = await pdf_to_docx.ainvoke({
        "source": str(_pdf(tmp_path)),
        "requirements": "Retire les numéros de page.",
    })

    assert "artefact" in out.lower() or "retiré" in out.lower()


@pytest.mark.asyncio
async def test_a_model_failure_still_produces_the_document(tmp_path, monkeypatch):
    """Échouer OUVERT jusqu'au bout de la chaîne : la délégation tombe, le
    document sort quand même — celui d'avant le lot, pas un fichier vide."""
    async def _broken(layout, requirements="", **kwargs):
        raise RuntimeError("plus de quota")

    monkeypatch.setattr(
        "app.services.pdf_plan_llm.request_conversion_plan", _broken,
    )
    from app.agent.tools.pdf_tool import pdf_to_docx

    out = await pdf_to_docx.ainvoke({
        "source": str(_pdf(tmp_path)),
        "requirements": "Respecte les sauts de page.",
    })

    assert "Document Word créé" in out
