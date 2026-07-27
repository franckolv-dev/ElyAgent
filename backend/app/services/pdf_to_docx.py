# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/pdf_to_docx.py
# @brief      Reconstruit la structure LOGIQUE d'un PDF, puis l'écrit en
#             styles Word natifs.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Conversion PDF → DOCX par reconstruction de la structure.

**Ce que faisait Ely avant.** Le cœur tenait en trois lignes :

    for line in text.split("\\n"):
        if line.strip():
            document.add_paragraph(line.strip())

Une ligne VISUELLE = un paragraphe Word. C'est le premier des deux raccourcis
qui condamnent une conversion : on obtient des milliers de faux paragraphes,
des mots coupés par les césures et aucun style. Et ``pypdf.extract_text()`` ne
donne aucune géométrie — ni coordonnées, ni corps, ni graisse — donc rien de
tout cela n'était même détectable.

**Le principe.** Un PDF ne contient pas de paragraphes : il contient des
glyphes posés à des coordonnées. La seule voie utile pour un texte suivi est de
**reconstruire la structure logique depuis la géométrie**, puis de la réécrire
en styles Word natifs.

**Le calibrage n'est pas optionnel.** Les seuils ne sont pas des valeurs
universelles : ce sont les mesures de CE document. Ils sont relevés sur le PDF
lui-même — les avances verticales entre lignes forment deux pics, l'interligne
courant et le passage au paragraphe suivant. On ne les devine pas.

**Périmètre assumé.** Ce module traite : fragments de ligne, césures,
paragraphes à cheval sur deux pages, détection de titre, styles nommés, et un
contrôle d'intégrité des caractères. Il ne traite PAS encore : vers et blocs
centrés, images en ligne, harmonisation de la ponctuation en fausse fonte,
champs PAGEREF du sommaire. Ce sont les raffinements — la structure d'abord.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class NoTextLayer(Exception):
    """Aucune page ne porte de texte — c'est un scan.

    Mieux vaut une erreur explicite qu'un document Word vide livré comme un
    succès : c'est exactement le genre de façade que ce projet traque.
    """


@dataclass
class Calibration:
    """Les mesures de CE document, pas des constantes universelles."""

    line_pitch: float
    para_gap_min: float
    left: float
    body_size: float
    right_edge: float


@dataclass
class ConversionReport:
    """Ce qui a été mesuré — pas seulement « converti »."""

    pages: int = 0
    paragraphs: int = 0
    titles: int = 0
    chars_pdf: int = 0
    chars_docx: int = 0
    missing_chars: int = 0
    calibration: Calibration | None = None


@dataclass
class _Line:
    text: str
    y: float
    x0: float
    x1: float
    size: float
    bold: bool
    page: int


@dataclass
class _Block:
    kind: str                       # "body" | "title"
    lines: list[_Line] = field(default_factory=list)


# ------------------------------------------------------------------ #
# 1. Calibrage                                                        #
# ------------------------------------------------------------------ #

# Le seuil de paragraphe se place JUSTE AU-DESSUS de l'interligne, pas au
# milieu entre les deux pics : les paragraphes serrés sont plus fréquents que
# les interlignes dilatés, donc mieux vaut pencher du côté de l'interligne.
_PARA_GAP_RATIO = 1.25
# Tolérance verticale pour regrouper les fragments d'une même ligne. Un
# changement d'italique ou une ponctuation en autre fonte crée un bloc
# distinct, parfois décalé de 1 à 2 points.
_LINE_TOLERANCE = 5.0
_DEFAULT_PITCH = 14.0
# En deçà, l'échantillon ne dit rien de fiable sur l'interligne du document.
_MIN_ADVANCE_SAMPLES = 5


def calibrate(doc) -> Calibration:
    """Relève l'interligne, le seuil de paragraphe et la marge sur le document.

    Les avances verticales entre lignes forment deux pics : l'interligne
    courant et le passage au paragraphe suivant. Le mode donne le premier.
    """
    advances: Counter = Counter()
    lefts: Counter = Counter()
    sizes: Counter = Counter()
    rights: list[float] = []

    sample = range(min(len(doc), 40))
    for pno in sample:
        page = doc[pno]
        ys = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                bbox = line["bbox"]
                ys.append(round(bbox[1], 1))
                lefts[round(bbox[0])] += 1
                rights.append(bbox[2])
                for span in line.get("spans", []):
                    sizes[round(span.get("size", 0), 1)] += 1
        ys = sorted(set(ys))
        advances.update(round(b - a, 1) for a, b in zip(ys, ys[1:]) if 0 < b - a < 60)

    # Un document de deux lignes donnerait un « pas » égal à l'unique avance
    # mesurée — donc un seuil de paragraphe absurde qui recollerait tout. En
    # dessous de ce nombre d'échantillons, le défaut prudent vaut mieux qu'une
    # mesure qui n'en est pas une.
    pitch = (
        advances.most_common(1)[0][0]
        if sum(advances.values()) >= _MIN_ADVANCE_SAMPLES
        else _DEFAULT_PITCH
    )
    left = float(lefts.most_common(1)[0][0]) if lefts else 72.0
    body = float(sizes.most_common(1)[0][0]) if sizes else 11.0
    # Bord droit du bloc de justification : au-delà, une ligne est « pleine ».
    right = statistics.median(rights) if rights else 500.0

    return Calibration(
        line_pitch=float(pitch),
        para_gap_min=float(pitch) * _PARA_GAP_RATIO,
        left=left,
        body_size=body,
        right_edge=float(right),
    )


# ------------------------------------------------------------------ #
# 2. Lecture des lignes — piège (a), fragments                        #
# ------------------------------------------------------------------ #

def _is_bold(span: dict) -> bool:
    if span.get("flags", 0) & (1 << 4):
        return True
    return "bold" in str(span.get("font", "")).lower() or "hebo" in str(
        span.get("font", "")
    ).lower()


def _page_lines(page, pno: int) -> list[_Line]:
    """Regroupe les fragments par tolérance verticale, puis trie par ``x``.

    Trié naïvement par ``y``, un texte dont l'italique crée un bloc décalé de
    1 à 2 points part dans le désordre.
    """
    frags: list[tuple[float, float, float, str, float, bool]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            bbox = line["bbox"]
            text = "".join(s.get("text", "") for s in line.get("spans", []))
            if not text.strip():
                continue
            spans = line.get("spans", [])
            size = max((s.get("size", 0) for s in spans), default=0.0)
            bold = any(_is_bold(s) for s in spans)
            centre = (bbox[1] + bbox[3]) / 2
            frags.append((centre, bbox[0], bbox[2], text, size, bold))

    frags.sort(key=lambda f: (f[0], f[1]))

    lines: list[_Line] = []
    for centre, x0, x1, text, size, bold in frags:
        if lines and abs(centre - lines[-1].y) <= _LINE_TOLERANCE:
            prev = lines[-1]
            # Même ligne visuelle : on concatène dans l'ordre des x.
            if x0 >= prev.x1:
                prev.text += text
            else:
                prev.text = text + prev.text
            prev.x0 = min(prev.x0, x0)
            prev.x1 = max(prev.x1, x1)
            prev.size = max(prev.size, size)
            prev.bold = prev.bold or bold
        else:
            lines.append(_Line(text, centre, x0, x1, size, bold, pno))
    return lines


# ------------------------------------------------------------------ #
# 3. Césures — piège (b)                                              #
# ------------------------------------------------------------------ #

def join_lines(texts: list[str]) -> str:
    """Recolle les lignes d'un paragraphe en traitant les césures.

    On supprime le trait d'union si la ligne suivante commence par une
    minuscule ou une apostrophe. Sinon on le garde : sans cette règle on
    obtient « éblouis-sement » ou, pire, « portefenêtre ».
    """
    out = ""
    for i, raw in enumerate(texts):
        cur = raw.rstrip()
        nxt = texts[i + 1].lstrip() if i + 1 < len(texts) else ""
        if cur.endswith("-") and nxt:
            # Minuscule ou apostrophe après : trait d'union typographique, on
            # le supprime. Sinon c'est un vrai trait d'union du mot — on le
            # garde, ET sans espace : « porte-Fenêtre » reste un seul mot.
            out += cur[:-1] if (nxt[0].islower() or nxt[0] in "'’") else cur
            continue
        out += cur
        if i + 1 < len(texts):
            out += " "
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------------ #
# 4. Titres — piège (d)                                               #
# ------------------------------------------------------------------ #

_TOP_OF_PAGE_RATIO = 0.35


def _toc_titles(doc) -> set[str]:
    """Le signet PDF donne la vérité quand il existe."""
    try:
        return {str(entry[1]).strip().lower() for entry in doc.get_toc() or []}
    except Exception:  # noqa: BLE001 — un PDF sans signet est la norme
        return set()


def _looks_like_title(lines: list[_Line], cal: Calibration, page_h: float,
                      toc: set[str]) -> bool:
    """Jamais par le texte. Chercher « Chapitre » ne marche pas — langue,
    chiffres romains, titres muets. On croise plusieurs signaux."""
    if not lines or len(lines) > 2:
        return False
    text = " ".join(line.text for line in lines).strip()
    if text.lower() in toc:
        return True
    bigger = max(line.size for line in lines) > cal.body_size * 1.15
    bold = all(line.bold for line in lines)
    high = min(line.y for line in lines) < page_h * _TOP_OF_PAGE_RATIO
    return (bigger and high) or (bold and bigger) or (bold and high)


# ------------------------------------------------------------------ #
# 5. Découpage en blocs + fusion inter-pages — piège (c)              #
# ------------------------------------------------------------------ #

_SENTENCE_END = tuple(".!?…»\"'")


def _fills_justification(line: _Line, cal: Calibration) -> bool:
    """La ligne va-t-elle jusqu'au bord du bloc de justification ?"""
    return line.x1 >= cal.right_edge - cal.body_size


def _build_blocks(doc, cal: Calibration) -> list[_Block]:
    toc = _toc_titles(doc)
    blocks: list[_Block] = []

    for pno in range(len(doc)):
        page = doc[pno]
        page_h = page.rect.height
        lines = _page_lines(page, pno)
        if not lines:
            continue

        # Découpage vertical : une avance supérieure au seuil ouvre un bloc.
        groups: list[list[_Line]] = [[lines[0]]]
        for prev, cur in zip(lines, lines[1:]):
            if cur.y - prev.y >= cal.para_gap_min:
                groups.append([cur])
            else:
                groups[-1].append(cur)

        for gi, group in enumerate(groups):
            kind = "title" if _looks_like_title(group, cal, page_h, toc) else "body"

            # Fusion inter-pages : uniquement le PREMIER groupe d'une page,
            # et seulement si la page précédente s'arrêtait en pleine phrase.
            merged = False
            if gi == 0 and kind == "body" and blocks and blocks[-1].kind == "body":
                last = blocks[-1].lines[-1]
                if (
                    last.page == pno - 1
                    and _fills_justification(last, cal)
                    and not last.text.rstrip().endswith(_SENTENCE_END)
                ):
                    blocks[-1].lines.extend(group)
                    merged = True

            if not merged:
                blocks.append(_Block(kind=kind, lines=list(group)))

    return blocks


# ------------------------------------------------------------------ #
# 6. Écriture DOCX — styles NOMMÉS, pas de formatage direct            #
# ------------------------------------------------------------------ #

def _ensure_styles(document) -> None:
    """Crée les styles nommés, tous basés sur ``Normal``.

    ``python-docx`` pousse au formatage direct (``run.bold = True`` partout).
    C'est ce qui produit ces DOCX impossibles à retoucher : changer le corps du
    texte demande des milliers de modifications manuelles. Avec un style nommé,
    c'est UNE modification.
    """
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt

    styles = document.styles
    normal = styles["Normal"]

    for name, size, bold, level in (("Chapitre", 18, True, 0), ("Partie", 22, True, 0)):
        if name in [s.name for s in styles]:
            continue
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        style.font.size = Pt(size)
        style.font.bold = bold
        # `w:outlineLvl` alimente le volet Navigation de Word et les signets à
        # l'export PDF. Sans lui, un titre n'est qu'un texte en gras.
        ppr = style.element.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(level))
        ppr.append(outline)
        # Le saut de page vit DANS le style : ajouter un chapitre ne casse
        # rien, contrairement à des sauts manuels semés dans le document.
        pbb = OxmlElement("w:pageBreakBefore")
        ppr.append(pbb)


def _write_document(blocks: list[_Block], out_path: Path) -> tuple[int, int]:
    import docx

    document = docx.Document()
    _ensure_styles(document)

    paragraphs = titles = 0
    for block in blocks:
        text = join_lines([line.text for line in block.lines])
        if not text:
            continue
        if block.kind == "title":
            document.add_paragraph(text, style="Chapitre")
            titles += 1
        else:
            document.add_paragraph(text)
        paragraphs += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    return paragraphs, titles


# ------------------------------------------------------------------ #
# 7. Contrôle 0 — le PDF face au DOCX                                 #
# ------------------------------------------------------------------ #

def _char_multiset(text: str) -> Counter:
    """Multi-ensemble des caractères, espaces exclus.

    Insensible à l'ordre de lecture des fragments — qui n'est pas significatif
    dans un PDF — mais impitoyable sur la moindre perte.
    """
    return Counter(c for c in text if not c.isspace())


def _docx_text(path: Path) -> str:
    import docx

    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


# ------------------------------------------------------------------ #
# Point d'entrée                                                      #
# ------------------------------------------------------------------ #

def convert_pdf_to_docx(pdf_bytes: bytes, out_path: str | Path) -> ConversionReport:
    """Convertit *pdf_bytes* en un ``.docx`` structuré et vérifié.

    Lève :class:`NoTextLayer` si aucune page ne porte de texte.
    """
    import fitz

    out_path = Path(out_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    pdf_text = "".join(doc[i].get_text() for i in range(len(doc)))
    if not pdf_text.strip():
        raise NoTextLayer(f"{len(doc)} page(s) sans couche texte")

    cal = calibrate(doc)
    blocks = _build_blocks(doc, cal)
    paragraphs, titles = _write_document(blocks, out_path)

    pdf_chars = _char_multiset(pdf_text)
    docx_chars = _char_multiset(_docx_text(out_path))
    # Ce qui manque au DOCX. Le trait d'union d'une césure supprimée est une
    # perte VOULUE : on ne la compte pas comme une anomalie.
    missing = pdf_chars - docx_chars
    missing.pop("-", None)

    return ConversionReport(
        pages=len(doc),
        paragraphs=paragraphs,
        titles=titles,
        chars_pdf=sum(pdf_chars.values()),
        chars_docx=sum(docx_chars.values()),
        missing_chars=sum(missing.values()),
        calibration=cal,
    )
