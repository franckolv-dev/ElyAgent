# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pdf_to_docx.py
# @brief      Tests du tool pdf_to_docx (conversion locale PDF → Word .docx).
# =============================================================================
"""pdf_to_docx : convertit un PDF texte en .docx SUR LE DISQUE DU SERVEUR.

Contexte (incident 22/07) : les outils auto-générés `convert_pdf_to_docx` /
`pdf_to_docx` passaient par Google Drive et plantaient sur
``'str' object has no attribute 'get'`` — les tools `drive_*` renvoient du
texte, pas des dicts. La conversion doit se faire en local (pypdf +
python-docx), sans aller-retour Drive : c'est plus fiable, ça marche hors
ligne, et ça évite le plafond d'import PDF→Google Docs de 2 Mo (le manuscrit
de 399 pages qui a déclenché l'incident pèse 2,17 Mo).

Le tool retourne un CHEMIN LOCAL, que l'agent enchaîne ensuite avec
``drive_upload_local_file`` s'il faut déposer le résultat sur Drive.
"""
from __future__ import annotations

import os
import re

import pytest

from app.agent.tools.drive_tool import _assert_upload_path_allowed
from app.agent.tools.pdf_tool import pdf_to_docx


# ── Fabrique de PDF minimal (xref valide, texte extractible) ─────────────────
def _make_pdf(pages: list[str]) -> bytes:
    """Construit un PDF valide d'une ligne de texte par page.

    Écrit à la main plutôt que via une dépendance de génération : le test
    reste hermétique et n'ajoute rien au pyproject.
    """
    objs: list[bytes] = []
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]  # 1=Catalog 2=Pages 3=Font

    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objs.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % n_pages)
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for i, text in enumerate(pages):
        content_id = page_ids[i] + 1
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
            b"/Resources << /Font << /F1 3 0 R >> >> "
            b"/Contents %d 0 R >>" % content_id
        )
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = b"BT /F1 12 Tf 20 250 Td (" + escaped.encode("latin-1") + b") Tj ET"
        objs.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % idx + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objs) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


def _blank_pdf(n_pages: int = 1) -> bytes:
    """PDF sans aucun texte extractible — le cas « PDF scanné »."""
    return _make_pdf([""] * n_pages)


@pytest.fixture
def pdf_path(tmp_path):
    def _write(data: bytes, name: str = "doc.pdf") -> str:
        # /tmp est dans la liste blanche de pdf_tool ET de drive_upload.
        target = tmp_path / name
        target.write_bytes(data)
        return str(target)

    return _write


def _extract_path(result: str) -> str:
    """Récupère le chemin .docx annoncé dans le retour du tool."""
    match = re.search(r"(/\S+\.docx)", result)
    assert match, f"aucun chemin .docx dans le retour : {result!r}"
    return match.group(1)


def _docx_text(path: str) -> str:
    import docx

    return "\n".join(p.text for p in docx.Document(path).paragraphs)


# ── Cas nominal ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_converts_text_pdf_to_a_real_docx_file(pdf_path):
    src = pdf_path(_make_pdf(["Bonjour Ely", "Deuxieme page"]))

    result = await pdf_to_docx.ainvoke({"source": src})

    out = _extract_path(result)
    assert os.path.isfile(out), f"fichier .docx non créé : {result}"
    assert os.path.getsize(out) > 0
    text = _docx_text(out)
    assert "Bonjour Ely" in text
    assert "Deuxieme page" in text


@pytest.mark.asyncio
async def test_output_path_is_accepted_by_drive_upload(pdf_path):
    """Contrat de chaînage : le .docx doit être téléversable tel quel."""
    src = pdf_path(_make_pdf(["Contenu"]))

    result = await pdf_to_docx.ainvoke({"source": src})

    # Ne lève pas => drive_upload_local_file acceptera le chemin.
    _assert_upload_path_allowed(_extract_path(result))


@pytest.mark.asyncio
async def test_custom_output_name_is_honoured(pdf_path):
    src = pdf_path(_make_pdf(["Contenu"]))

    result = await pdf_to_docx.ainvoke(
        {"source": src, "output_name": "manuscrit_final"}
    )

    assert os.path.basename(_extract_path(result)) == "manuscrit_final.docx"


# ── Le cœur de l'incident : aucune troncature sur un gros document ───────────
@pytest.mark.asyncio
async def test_long_pdf_is_converted_in_full_without_truncation(pdf_path):
    """pdf_read tronque à 15 000 caractères ; la conversion, jamais.

    Le déclencheur de l'incident est un manuscrit de 399 pages : un tool qui
    tronque produirait un .docx silencieusement amputé — pire qu'une erreur.
    """
    pages = [f"Page numero {i} du manuscrit" for i in range(1, 121)]
    src = pdf_path(_make_pdf(pages))

    result = await pdf_to_docx.ainvoke({"source": src})

    text = _docx_text(_extract_path(result))
    assert "Page numero 1 du manuscrit" in text
    assert "Page numero 120 du manuscrit" in text
    assert len(text) > 15_000 or all(
        f"Page numero {i} du manuscrit" in text for i in range(1, 121)
    )


# ── Échecs explicites (jamais de .docx vide livré en silence) ────────────────
@pytest.mark.asyncio
async def test_scanned_pdf_reports_no_extractable_text(pdf_path):
    src = pdf_path(_blank_pdf(3), name="scan.pdf")

    result = await pdf_to_docx.ainvoke({"source": src})

    assert "aucun texte" in result.lower()
    assert "pdf_analyze_with_vision" in result  # oriente vers l'OCR/vision
    assert ".docx" not in result.replace("pdf_to_docx", "")


@pytest.mark.asyncio
async def test_path_outside_allowed_dirs_is_refused():
    result = await pdf_to_docx.ainvoke({"source": "/etc/passwd.pdf"})

    assert "refus" in result.lower() or "acces" in result.lower()


@pytest.mark.asyncio
async def test_missing_file_reports_clearly(tmp_path):
    result = await pdf_to_docx.ainvoke({"source": str(tmp_path / "absent.pdf")})

    assert "introuvable" in result.lower()
