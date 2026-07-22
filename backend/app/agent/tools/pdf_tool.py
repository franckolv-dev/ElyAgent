# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/pdf_tool.py
# @brief      PDF reading tool — extrait le texte d'un PDF (fichier local ou URL).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""PDF reading tool — extrait le texte d'un PDF (fichier local ou URL)."""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from langchain_core.tools import tool

_MAX_CHARS = 15_000  # ~5 pages de texte dense


@tool
async def pdf_read(source: str, pages: str = "") -> str:
    """Read and extract raw text from a PDF file (local path or URL).

    USE THIS for simple text-based PDFs (reports, articles, contracts with plain text).
    PREFER pdf_analyze_with_vision instead for: catalogs, invoices, tables, multi-column
    layouts, or any document where visual layout matters for understanding the content.

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
async def pdf_to_docx(source: str, output_name: str = "") -> str:
    """Convert a text-based PDF into a real Microsoft Word .docx file.

    USE THIS whenever the user asks to convert / transform a PDF into Word,
    .docx, or "an editable document". The conversion runs locally on the
    server — do NOT route it through Google Drive.

    Returns the path of the generated .docx on the server. To deliver it:
      - Google Drive  → chain ``drive_upload_local_file`` with that path.
      - user's Mac    → chain ``desktop_write_file`` / the desktop tools.

    Text and paragraph order are preserved; visual layout (columns, tables,
    images) is NOT. For a scanned PDF (no text layer) this returns an explicit
    error — use ``pdf_analyze_with_vision`` instead.

    Args:
        source: File path (e.g. '/app/uploads/…/manuscrit.pdf') or URL.
        output_name: Optional base name for the .docx (no extension).
            Defaults to the source file's own name.
    """
    try:
        pdf_bytes = await _get_pdf_bytes(source)
    except PermissionError as exc:
        return str(exc)
    except FileNotFoundError as exc:
        return str(exc)
    except Exception as exc:
        return f"Impossible de récupérer le PDF : {exc}"

    try:
        import pypdf  # noqa: F401
    except ImportError:
        return (
            "Le module pypdf n'est pas installé. "
            "Ajoute 'pypdf>=4.0.0' dans pyproject.toml."
        )
    try:
        import docx  # noqa: F401
    except ImportError:
        return (
            "Le module python-docx n'est pas installé. "
            "Ajoute 'python-docx>=1.1.0' dans pyproject.toml."
        )

    base = output_name.strip() or Path(_basename_of(source)).stem
    safe_base = _safe_stem(base)

    try:
        # Extraction + écriture sont CPU-bound et peuvent durer plusieurs
        # secondes sur un manuscrit de plusieurs centaines de pages : hors
        # de la boucle asyncio, sinon tout le backend gèle pendant ce temps.
        out_path, pages_done, pages_total, empty_pages = await asyncio.to_thread(
            _write_docx, pdf_bytes, safe_base
        )
    except _NoTextLayer as exc:
        return (
            f"Aucun texte extractible dans ce PDF ({exc.pages} page(s)) — "
            "c'est très probablement un scan (image) sans couche texte. "
            "La conversion en Word donnerait un document vide. "
            "Utilise pdf_analyze_with_vision pour en lire le contenu."
        )
    except Exception as exc:
        return f"Erreur lors de la conversion en .docx : {exc}"

    size_kb = os.path.getsize(out_path) // 1024
    lines = [
        f"Document Word créé : {out_path}",
        f"Pages converties : {pages_done}/{pages_total} — {size_kb} Ko",
    ]
    if empty_pages:
        lines.append(
            f"Note : {empty_pages} page(s) sans texte extractible (images ?) "
            "ont été ignorées."
        )
    lines.append(
        "Le fichier est sur le disque du serveur. Pour le déposer sur Drive, "
        "enchaîne drive_upload_local_file avec ce chemin."
    )
    return "\n".join(lines)


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

# Sortie des conversions. /tmp est dans la liste blanche de pdf_tool ET dans
# celle de drive_upload_local_file — le .docx produit est donc téléversable
# tel quel, sans copie intermédiaire.
_DOCX_OUT_DIR = Path(tempfile.gettempdir()) / "ely-docx"


class _NoTextLayer(Exception):
    """PDF sans aucun texte extractible (scan). Porte le nombre de pages."""

    def __init__(self, pages: int) -> None:
        super().__init__(f"no text layer ({pages} pages)")
        self.pages = pages


def _basename_of(source: str) -> str:
    """Nom de fichier d'un chemin OU d'une URL (sans query string)."""
    if source.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        return os.path.basename(urlparse(source).path) or "document.pdf"
    return os.path.basename(source) or "document.pdf"


def _safe_stem(name: str) -> str:
    """Nom de fichier sûr : pas de séparateur, pas de traversal, non vide."""
    stem = os.path.basename(name).strip().strip(".")
    stem = re.sub(r"[^\w.\- ]+", "_", stem, flags=re.UNICODE).strip()
    return (stem or "document")[:120]


def _write_docx(pdf_bytes: bytes, safe_base: str) -> tuple[str, int, int, int]:
    """Extrait le texte page à page et écrit le .docx. Bloquant (to_thread).

    Retourne ``(chemin, pages_converties, pages_totales, pages_vides)``.
    Lève :class:`_NoTextLayer` si AUCUNE page ne porte de texte — mieux vaut
    une erreur explicite qu'un document Word vide livré comme un succès.
    """
    import io

    import docx
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)

    document = docx.Document()
    written = 0
    empty = 0
    for idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            empty += 1
            continue
        if written:
            document.add_page_break()
        for line in text.split("\n"):
            # Une ligne PDF = un paragraphe Word. On garde les lignes vides
            # hors du document (elles ne portent pas d'information ici).
            if line.strip():
                document.add_paragraph(line.strip())
        written += 1

    if written == 0:
        raise _NoTextLayer(total)

    _DOCX_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _DOCX_OUT_DIR / f"{safe_base}.docx"
    document.save(str(out_path))
    return str(out_path), written, total, empty


_ALLOWED_DIRS: list[str] = [
    str((Path(__file__).parents[3] / "uploads").resolve()),
    # realpath : sur macOS /tmp est un lien vers /private/tmp, et le chemin
    # comparé est déjà résolu — la chaîne brute "/tmp" ne matchait jamais.
    # (drive_tool résout déjà ; ici c'était la seule liste qui ne le faisait
    # pas. Sans effet en prod Linux, où /tmp est un vrai répertoire.)
    os.path.realpath("/tmp"),
    os.path.realpath(tempfile.gettempdir()),
]

_BLOCKED_PATHS: list[str] = [
    "/etc", "/proc", "/sys", "/var/run",
    "/app/.env", "/root", "/home",
]


def _validate_local_path(file_path: str) -> str:
    """Validate that a local file path is safe (no path traversal)."""
    resolved = os.path.realpath(os.path.expanduser(file_path))

    # Block explicitly dangerous paths
    for blocked in _BLOCKED_PATHS:
        if resolved.startswith(blocked):
            raise PermissionError(
                f"Acces refuse : '{file_path}' est dans un repertoire bloque ({blocked})."
            )

    # Allow only whitelisted directories
    if not any(resolved.startswith(allowed) for allowed in _ALLOWED_DIRS):
        allowed_display = ", ".join(_ALLOWED_DIRS)
        raise PermissionError(
            f"Acces refuse : '{file_path}' est en dehors des repertoires autorises. "
            f"Repertoires accessibles : {allowed_display}"
        )

    return resolved


async def _get_pdf_bytes(source: str) -> bytes:
    """Fetch PDF bytes from a URL or read from local path."""
    if source.startswith(("http://", "https://")):
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(source)
            resp.raise_for_status()
            return resp.content
    else:
        path = _validate_local_path(source)
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
