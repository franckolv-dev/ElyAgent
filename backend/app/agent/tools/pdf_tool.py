"""PDF reading tool — extrait le texte d'un PDF (fichier local ou URL)."""
from __future__ import annotations

import asyncio
import os
import tempfile

from langchain_core.tools import tool

_MAX_CHARS = 15_000  # ~5 pages de texte dense


@tool
async def pdf_read(source: str, pages: str = "") -> str:
    """Read and extract text from a PDF file (local path or URL).

    Args:
        source: File path (e.g. '/tmp/contract.pdf') or URL (https://example.com/doc.pdf)
        pages: Page range to extract, e.g. '1-3', '2', '1,3,5'. Empty = all pages.
    """
    try:
        pdf_bytes = await _get_pdf_bytes(source)
    except Exception as exc:
        return f"Impossible de récupérer le PDF : {exc}"

    try:
        import pypdf
    except ImportError:
        return (
            "Le module pypdf n'est pas installé. "
            "Ajoute 'pypdf>=4.0.0' dans pyproject.toml."
        )

    try:
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total = len(reader.pages)

        # Résoudre la liste de pages demandées
        page_indices = _parse_pages(pages, total)

        extracted = []
        for idx in page_indices:
            page = reader.pages[idx]
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                extracted.append(f"--- Page {idx + 1} ---\n{text}")

        if not extracted:
            return f"Aucun texte extractible dans ce PDF ({total} page(s))."

        full = "\n\n".join(extracted)
        header = (
            f"PDF : {os.path.basename(source)}\n"
            f"Pages extraites : {len(page_indices)}/{total}\n\n"
        )

        result = header + full
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + (
                f"\n\n[… contenu tronqué — {len(full)} caractères au total. "
                f"Utilise le paramètre 'pages' pour cibler des pages spécifiques.]"
            )
        return result

    except Exception as exc:
        return f"Erreur lors de la lecture du PDF : {exc}"


@tool
async def pdf_info(source: str) -> str:
    """Get metadata and structure info from a PDF (number of pages, title, author, etc.).

    Args:
        source: File path or URL of the PDF
    """
    try:
        pdf_bytes = await _get_pdf_bytes(source)
    except Exception as exc:
        return f"Impossible de récupérer le PDF : {exc}"

    try:
        import pypdf
        import io

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        meta   = reader.metadata or {}
        total  = len(reader.pages)

        lines = [
            f"Nombre de pages : {total}",
            f"Titre    : {meta.get('/Title',    'Non renseigné')}",
            f"Auteur   : {meta.get('/Author',   'Non renseigné')}",
            f"Sujet    : {meta.get('/Subject',  'Non renseigné')}",
            f"Créateur : {meta.get('/Creator',  'Non renseigné')}",
            f"Crypté   : {'Oui' if reader.is_encrypted else 'Non'}",
        ]
        return "\n".join(lines)

    except Exception as exc:
        return f"Erreur lors de la lecture des métadonnées : {exc}"


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_pdf_bytes(source: str) -> bytes:
    """Fetch PDF bytes from a URL or read from local path."""
    if source.startswith(("http://", "https://")):
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(source)
            resp.raise_for_status()
            return resp.content
    else:
        path = os.path.expanduser(source)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        with open(path, "rb") as f:
            return f.read()


def _parse_pages(pages_str: str, total: int) -> list[int]:
    """Parse a page spec like '1-3', '2', '1,3,5' into 0-based indices."""
    if not pages_str.strip():
        return list(range(total))

    indices: set[int] = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            start = max(1, int(a.strip())) - 1
            end   = min(total, int(b.strip()))
            indices.update(range(start, end))
        else:
            idx = int(part.strip()) - 1
            if 0 <= idx < total:
                indices.add(idx)

    return sorted(indices)
