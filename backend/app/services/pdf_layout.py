# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/pdf_layout.py
# @brief      Ce qu'Ely DONNE au modèle, et ce qu'elle LIT de sa réponse.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""La géométrie d'un PDF, rendue lisible par un modèle — et sa réponse, relue.

Pourquoi ce module existe
--------------------------
Mesuré le 28/07/2026 : ``pdf_to_docx(source, output_name)``. L'outil ne reçoit
que le chemin du fichier et un nom de sortie. **Ce que Franck écrit dans sa
demande n'a aucun chemin pour l'atteindre** — « respecte les sauts de page »
s'arrête au modèle, qui se contente d'appeler l'outil et de rapporter son
résultat. Cinq essais de reformulation l'ont montré : affiner le prompt ne peut
rien changer à une signature à deux arguments.

Ce module ouvre le chemin manquant, dans le sens voulu par Franck le 27/07 :

    Ely     -> extrait la géométrie et la DONNE au modèle
    Modèle  -> décide de la structure, rend un BALISAGE
    Ely     -> matérialise, mécaniquement
    Ely     -> contrôle, et relance via la boucle de conformité

L'asymétrie qui fait tout tenir
--------------------------------
Le modèle voit des **extraits** et répond par des **identifiants**. Le texte
intégral ne quitte jamais Ely, qui le réinjecte à la matérialisation. Trois
conséquences, toutes voulues :

- **l'intégrité est structurelle** — aucun caractère ne dépend d'un modèle qui
  recopie ; le contrôle 0 de ``pdf_to_docx`` reste vrai par construction ;
- **le coût ne suit pas la longueur du manuscrit** — 395 pages tiennent en
  quelques tranches de digest, pas en 800 000 caractères ;
- **aucun bac à sable n'est requis** — un balisage déclaratif n'est pas du
  code. La ligne du 27/07 (pas d'exécution locale de code écrit par le modèle)
  tient sans aménagement.

Ce que le modèle décide, et ce qu'Ely garde
--------------------------------------------
Le modèle décide de ce qui demande un jugement : cette page est-elle voulue ou
est-ce un débordement, ce bloc est-il un titre, ce « 12 » isolé en bas de page
est-il du texte ou un folio. Ely garde ce qui est mécanique : lire la
géométrie, écrire les runs, compter les caractères.

Un bloc dont le modèle ne dit rien **garde le défaut d'Ely**. C'est la règle
« échouer OUVERT » de la boucle de conformité, appliquée ici : un modèle en
panne ne doit pas mutiler le document, il doit rendre la main au comportement
d'avant.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.services.pdf_to_docx import (
    Calibration,
    _fills_justification,
    _Line,
    _page_groups,
    calibrate,
)

logger = logging.getLogger(__name__)

# Longueur de l'extrait montré au modèle. Assez pour reconnaître un titre, une
# dédicace ou un folio ; trop court pour qu'il soit tenté de recopier.
_EXCERPT_CHARS = 90
# En deçà, une page est « courte » : dédicace, exergue, page de titre, faux
# titre. C'est le signal le plus discriminant pour « page voulue ».
_SHORT_PAGE_CHARS = 300


# ──────────────────────────────────────────────────────────────────────
# 1. Ce qu'Ely extrait
# ──────────────────────────────────────────────────────────────────────


@dataclass
class LayoutBlock:
    """Un bloc de texte, avec le nom sous lequel le modèle le désignera.

    ``id`` a la forme ``p3b1`` : page 3 (1-based, comme la voit un humain),
    bloc 1 de cette page. Stable tant que la géométrie ne change pas — ce qui
    est le cas, elle est relue du même PDF.
    """

    id: str
    page: int
    text: str
    lines: list[_Line]
    size: float
    bold: bool
    x0: float
    x1: float
    y0: float
    y1: float
    fills_line: bool
    centered: bool

    @property
    def line_count(self) -> int:
        return len(self.lines)


@dataclass
class PageLayout:
    number: int                       # 1-based
    width: float
    height: float
    blocks: list[LayoutBlock] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks)

    @property
    def is_short(self) -> bool:
        return self.char_count < _SHORT_PAGE_CHARS


@dataclass
class DocumentLayout:
    pages: list[PageLayout]
    calibration: Calibration
    toc: list[tuple[int, str, int]] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _is_centered(x0: float, x1: float, page_width: float, cal: Calibration) -> bool:
    """Bloc centré : marge gauche abandonnée ET écarts droite/gauche voisins.

    Un vers, une dédicace, une page de titre. Le convertisseur les traitait
    comme du corps aligné à gauche, ce qui suffit à ne plus reconnaître une
    page de garde.
    """
    left_gap = x0 - cal.left
    right_gap = (page_width - cal.left) - x1
    return left_gap > cal.body_size and abs(left_gap - right_gap) < cal.body_size * 2


def extract_layout(doc) -> DocumentLayout:
    """Relève la géométrie du document, bloc par bloc et page par page.

    S'appuie sur ``_page_groups`` — donc sur exactement le même découpage que
    la conversion. Deux découpages parallèles finiraient par diverger, et le
    balisage du modèle désignerait alors des blocs qui n'existent plus.
    """
    cal = calibrate(doc)
    pages: list[PageLayout] = []

    for pno, groups in enumerate(_page_groups(doc, cal)):
        rect = doc[pno].rect
        page = PageLayout(number=pno + 1, width=rect.width, height=rect.height)
        for gi, group in enumerate(groups):
            x0 = min(ln.x0 for ln in group)
            x1 = max(ln.x1 for ln in group)
            page.blocks.append(
                LayoutBlock(
                    id=f"p{pno + 1}b{gi}",
                    page=pno + 1,
                    text="".join(ln.text for ln in group).strip(),
                    lines=list(group),
                    size=max(ln.size for ln in group),
                    bold=all(ln.bold for ln in group),
                    x0=x0,
                    x1=x1,
                    y0=min(ln.y for ln in group),
                    y1=max(ln.y for ln in group),
                    fills_line=_fills_justification(group[-1], cal),
                    centered=_is_centered(x0, x1, rect.width, cal),
                )
            )
        pages.append(page)

    try:
        toc = [(int(e[0]), str(e[1]), int(e[2])) for e in (doc.get_toc() or [])]
    except Exception as exc:  # noqa: BLE001 — un PDF sans signet est la norme
        logger.debug("extract_layout : signet illisible (%s)", exc)
        toc = []

    return DocumentLayout(pages=pages, calibration=cal, toc=toc)


# ──────────────────────────────────────────────────────────────────────
# 2. Ce qu'Ely DONNE — le digest
# ──────────────────────────────────────────────────────────────────────


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else flat[:_EXCERPT_CHARS] + "…"


def _flags(block: LayoutBlock, cal: Calibration) -> str:
    marks = []
    if block.bold:
        marks.append("GRAS")
    if block.size > cal.body_size * 1.15:
        marks.append("GRAND")
    elif block.size < cal.body_size * 0.85:
        marks.append("PETIT")
    if block.centered:
        marks.append("CENTRE")
    if not block.fills_line:
        marks.append("COURT")
    return ",".join(marks) or "-"


def build_layout_digest(layout: DocumentLayout, *, first_page: int,
                        last_page: int) -> str:
    """Rend la tranche ``[first_page, last_page]`` sous une forme lisible.

    Une ligne par bloc, une en-tête par page. C'est la frontière de page qui
    porte la décision attendue, donc elle est explicite et numérotée — le
    modèle n'a pas à la déduire d'une coordonnée.

    Les extraits sont tronqués : le modèle décide de la STRUCTURE, il n'a
    besoin de reconnaître un bloc, pas de le lire en entier.
    """
    cal = layout.calibration
    out: list[str] = []

    titles = {t[2]: t[1] for t in layout.toc}

    for page in layout.pages:
        if not (first_page <= page.number <= last_page):
            continue
        head = (
            f"### PAGE {page.number} — {len(page.blocks)} bloc(s), "
            f"{page.char_count} caractères"
        )
        if page.is_short:
            head += " [PAGE COURTE]"
        if page.number in titles:
            head += f" [signet PDF : {titles[page.number]!r}]"
        out.append(head)

        if not page.blocks:
            out.append("  (page sans texte)")
            continue
        for block in page.blocks:
            out.append(
                f"  {block.id}  y={block.y0:.0f}  {block.size:.1f}pt  "
                f"{_flags(block, cal)}  « {_excerpt(block.text)} »"
            )

    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────
# 3. Ce qu'Ely LIT — le balisage du modèle
# ──────────────────────────────────────────────────────────────────────

# Le contrat, volontairement étroit. Un vocabulaire ouvert obligerait à
# interpréter, donc à deviner ; ici tout ce qui n'est pas reconnu est ignoré et
# le défaut d'Ely s'applique.
ROLES: frozenset[str] = frozenset(
    {"TITRE1", "TITRE2", "CORPS", "CITATION", "ARTEFACT"}
)
ATTRIBUTES: frozenset[str] = frozenset({"SAUT", "SUITE", "CENTRE"})

# Les décorations tolérées en tête de ligne : puce de liste, puis chevrons /
# crochets / accent grave autour de l'identifiant.
#
# ⚠️ Mesuré le 28/07 : sans cette tolérance, GPT-5.6 voyait **6 tranches sur
# 12** entièrement jetées — il rendait `<p1b0> TITRE1 SAUT`, un balisage juste
# aux chevrons près. Jeter une réponse correcte pour sa décoration est un échec
# d'Ely, pas du modèle.
_BLOCK_ID = re.compile(
    r"^\s*(?:[-*•]\s*)?[<\[(`]?\s*(p\d+b\d+)\s*[>\])`]?\s*(.*)$", re.IGNORECASE
)


@dataclass
class BlockDecision:
    role: str | None = None
    page_break: bool = False
    continuation: bool = False
    centered: bool = False


@dataclass
class ConversionPlan:
    """Les décisions du modèle, indexées par identifiant de bloc.

    Tout est OPTIONNEL par construction : un plan vide ne décide rien et la
    conversion retombe intégralement sur le comportement d'avant ce lot.
    """

    decisions: dict[str, BlockDecision] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.decisions

    def role_of(self, block_id: str) -> str | None:
        d = self.decisions.get(block_id)
        return d.role if d else None

    def breaks_before(self, block_id: str) -> bool:
        d = self.decisions.get(block_id)
        return bool(d and d.page_break)

    def continues(self, block_id: str) -> bool:
        d = self.decisions.get(block_id)
        return bool(d and d.continuation)

    def is_centered(self, block_id: str) -> bool:
        d = self.decisions.get(block_id)
        return bool(d and d.centered)

    def dropped(self) -> set[str]:
        return {bid for bid, d in self.decisions.items() if d.role == "ARTEFACT"}


def parse_conversion_plan(raw: str) -> ConversionPlan:
    """Lit le balisage rendu par le modèle. Ne lève jamais.

    Tolérant par nécessité : un modèle préfixe volontiers sa réponse de « Voici
    le plan », la ceint de ``` et la commente après coup. Refuser sur ces
    motifs cosmétiques rendrait la chaîne inutilisable en production pour une
    raison qui n'a rien à voir avec le travail demandé.

    Strict sur le reste : un rôle hors contrat est ignoré plutôt qu'interprété.
    Ely préfère son propre défaut à une invention appliquée au document.
    """
    plan = ConversionPlan()
    if not raw:
        return plan

    for line in str(raw).splitlines():
        m = _BLOCK_ID.match(line)
        if not m:
            continue
        block_id = m.group(1).lower()
        tokens = [t.strip(",;|") for t in m.group(2).upper().split()]

        decision = BlockDecision()
        for token in tokens:
            if token in ROLES:
                # Premier rôle nommé seulement : « CORPS TITRE1 » est une
                # contradiction, pas une précision.
                decision.role = decision.role or token
            elif token == "SAUT":
                decision.page_break = True
            elif token == "SUITE":
                decision.continuation = True
            elif token == "CENTRE":
                decision.centered = True

        if decision.role is None and not any(
            (decision.page_break, decision.continuation, decision.centered)
        ):
            # Une ligne qui ne porte qu'un identifiant ne dit rien.
            continue
        plan.decisions[block_id] = decision

    return plan


__all__ = [
    "ATTRIBUTES",
    "ROLES",
    "BlockDecision",
    "ConversionPlan",
    "DocumentLayout",
    "LayoutBlock",
    "PageLayout",
    "build_layout_digest",
    "extract_layout",
    "parse_conversion_plan",
]
