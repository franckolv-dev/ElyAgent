# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_pdf_layout_handoff.py
# @brief      Ely DONNE la géométrie au modèle et MATÉRIALISE son balisage —
#             elle ne décide plus seule de la structure.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Le lot « la conversion : Ely donne et contrôle ».

Ce qui a été mesuré le 28/07/2026, et qui ferme le débat
---------------------------------------------------------
    signature réelle : pdf_to_docx(source, output_name)
    add_page_break dans app/services/pdf_to_docx.py : 0 occurrence

Le prompt de Franck **ne peut pas atteindre l'outil** : il ne reçoit que le
chemin du fichier et un nom de sortie. Quoi qu'il écrive (« respecte les sauts
de page »), rien ne descend. Affiner le prompt est structurellement inutile.

⚠️ Nuance mesurée pendant ce lot, qui corrige la formule « le convertisseur ne
sait pas produire de saut de page ». Il en produit — mais **uniquement** par
l'attribut ``w:pageBreakBefore`` des styles ``Chapitre``/``Partie``, donc
seulement là où l'heuristique a cru voir un titre. Mesure sur les 12 premières
pages du manuscrit de Franck : 12 pages PDF → 6 sauts, dont un sur le bloc de
copyright pris pour un chapitre, et zéro pour la dédicace et l'exergue. Le
symptôme qu'il décrit — 4-5 pages aplaties en une — est donc exact ; sa cause
est « le saut est un effet de bord de la détection de titre », pas « il n'y a
aucun saut ».

La forme livrée (décision de Franck, 28/07)
--------------------------------------------
    Ely     -> extrait la géométrie (pymupdf) et la DONNE au modèle
    Modèle  -> décide de la structure et rend un BALISAGE
    Ely     -> matérialise le balisage, mécaniquement
    Ely     -> contrôle et relance via la boucle de conformité (#288/#289)

**Le texte ne transite jamais par le modèle.** Le balisage ne porte que des
IDENTIFIANTS de blocs ; Ely réinjecte le texte depuis sa propre extraction.
C'est ce qui rend l'intégrité vérifiable par construction et le coût
indépendant de la longueur du manuscrit.

**Aucun bac à sable requis** : un balisage déclaratif n'est pas du code. La
ligne du 27/07 (pas d'exécution locale de code écrit par le modèle) tient.

Run with:  cd backend && python -m pytest tests/test_pdf_layout_handoff.py -v
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz", reason="pymupdf requis pour ces pins")

_LINE_PITCH = 14.0
_PARA_GAP = 26.0
_LEFT = 72.0
_TOP = 100.0
_BODY_SIZE = 11.0


def _page(doc, lines, *, left=_LEFT, top=_TOP, width=595, height=842):
    """Pose des lignes à une géométrie EXACTE.

    Chaque entrée : ``(texte, avance_avant, taille, gras)``.
    """
    page = doc.new_page(width=width, height=height)
    y = top
    for text, gap, size, bold in lines:
        y += gap
        page.insert_text((left, y), text, fontsize=size,
                         fontname="hebo" if bold else "helv")
    return page


def _body(n, prefix="Ligne"):
    return [(f"{prefix} {i} du paragraphe courant qui coule.",
             0 if i == 0 else _LINE_PITCH, _BODY_SIZE, False) for i in range(n)]


# ─────────────────────────────────────────────────────────────────────
# 1. Ely extrait la géométrie et la rend RÉFÉRENÇABLE
# ─────────────────────────────────────────────────────────────────────


def test_every_block_carries_a_stable_identifier():
    """Le modèle ne peut désigner un bloc que s'il a un nom. Sans identifiant,
    il faudrait qu'il RECOPIE le texte pour dire de quoi il parle — et un
    modèle qui recopie 395 pages perd des caractères et coûte une fortune."""
    from app.services.pdf_layout import extract_layout

    doc = fitz.open()
    _page(doc, [("Titre du chapitre", 0, 20.0, True)] + _body(3))
    _page(doc, _body(4))

    layout = extract_layout(doc)

    ids = [b.id for page in layout.pages for b in page.blocks]
    assert len(ids) == len(set(ids)), f"identifiants en double : {ids}"
    assert ids[0].startswith("p1"), f"l'identifiant doit porter sa page : {ids[0]}"
    assert any(i.startswith("p2") for i in ids), "la page 2 n'a produit aucun bloc"


def test_the_layout_keeps_the_full_text_of_each_block():
    """Ely garde le texte ; le modèle ne le verra qu'en extrait. C'est cette
    asymétrie qui garantit qu'aucun caractère ne dépend du modèle."""
    from app.services.pdf_layout import extract_layout

    doc = fitz.open()
    _page(doc, _body(4, prefix="Phrase"))

    layout = extract_layout(doc)

    joined = " ".join(b.text for b in layout.pages[0].blocks)
    assert "Phrase 3 du paragraphe courant" in joined


def test_the_layout_reports_what_the_model_needs_to_decide_a_page_break():
    """Décider « page voulue ou débordement » demande deux signaux : la
    dernière ligne va-t-elle au bout de la justification, et la page est-elle
    courte. Sans eux le modèle devine."""
    from app.services.pdf_layout import extract_layout

    doc = fitz.open()
    _page(doc, [("Dedicace seule au milieu du vide.", 0, _BODY_SIZE, False)])
    _page(doc, _body(20))

    layout = extract_layout(doc)

    assert layout.pages[0].char_count < layout.pages[1].char_count
    assert hasattr(layout.pages[0].blocks[0], "fills_line")


# ─────────────────────────────────────────────────────────────────────
# 2. Le digest — ce qu'Ely DONNE au modèle
# ─────────────────────────────────────────────────────────────────────


def test_the_digest_names_every_block_of_the_window():
    """Le modèle doit pouvoir statuer sur chaque bloc qu'on lui montre. Un
    bloc absent du digest est une décision qu'Ely reprend en douce."""
    from app.services.pdf_layout import build_layout_digest, extract_layout

    doc = fitz.open()
    _page(doc, [("Chapitre premier", 0, 20.0, True)] + _body(3))

    layout = extract_layout(doc)
    digest = build_layout_digest(layout, first_page=1, last_page=1)

    for block in layout.pages[0].blocks:
        assert block.id in digest, f"{block.id} absent du digest"


def test_the_digest_truncates_the_text_it_shows():
    """Un manuscrit de 395 pages ne tient pas dans une fenêtre de contexte. Le
    modèle décide de la STRUCTURE : un extrait lui suffit, le texte intégral
    reste chez Ely."""
    from app.services.pdf_layout import build_layout_digest, extract_layout

    doc = fitz.open()
    long_line = "Un texte tres long qui depasse largement ce qu il faut montrer"
    _page(doc, [(long_line, 0, _BODY_SIZE, False)] * 6)

    layout = extract_layout(doc)
    digest = build_layout_digest(layout, first_page=1, last_page=1)

    full = layout.pages[0].blocks[0].text
    assert len(full) > 120, "le bloc de test doit être long pour prouver la troncature"
    assert full not in digest, "le digest transporte le texte intégral"


def test_the_digest_is_restricted_to_the_requested_window():
    """Le découpage en tranches est ce qui rend le manuscrit traitable. Une
    fenêtre qui déborde ramènerait le problème d'échelle."""
    from app.services.pdf_layout import build_layout_digest, extract_layout

    doc = fitz.open()
    for _ in range(4):
        _page(doc, _body(3))

    layout = extract_layout(doc)
    digest = build_layout_digest(layout, first_page=2, last_page=3)

    assert "p2b0" in digest and "p3b0" in digest
    assert "p1b0" not in digest and "p4b0" not in digest


# ─────────────────────────────────────────────────────────────────────
# 3. Le balisage — ce que le modèle REND
# ─────────────────────────────────────────────────────────────────────


def test_the_plan_reads_a_role_per_block():
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan(
        "p1b0 TITRE1\n"
        "p1b1 CORPS\n"
        "p1b2 ARTEFACT\n"
    )

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.role_of("p1b1") == "CORPS"
    assert plan.role_of("p1b2") == "ARTEFACT"


def test_the_plan_reads_the_page_break_the_model_asked_for():
    """LE point du lot. C'est cette décision-là qui n'existait nulle part."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan("p2b0 CORPS SAUT\np2b1 CORPS\n")

    assert plan.breaks_before("p2b0") is True
    assert plan.breaks_before("p2b1") is False


def test_the_plan_reads_a_continuation_across_pages():
    """L'inverse du saut : le paragraphe déborde, il ne faut PAS couper."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan("p3b0 CORPS SUITE\n")

    assert plan.continues("p3b0") is True
    assert plan.breaks_before("p3b0") is False


def test_the_plan_survives_a_model_that_chats_around_its_answer():
    """Un modèle préfixe volontiers son balisage de « Voici le plan : » et le
    ceint de ```. Échouer là-dessus rendrait la chaîne inutilisable en
    production pour une raison cosmétique."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan(
        "Voici le plan de conversion :\n\n"
        "```\n"
        "p1b0 TITRE1 SAUT\n"
        "p1b1 CORPS\n"
        "```\n\n"
        "J'ai classé le folio en artefact."
    )

    assert plan.role_of("p1b0") == "TITRE1"
    assert plan.breaks_before("p1b0") is True


def test_an_unknown_role_is_ignored_rather_than_trusted():
    """Contrat inconnu = on ne sait pas ce que le modèle a voulu dire. Le
    défaut d'Ely vaut mieux qu'une invention appliquée au document."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan("p1b0 SOUS_TITRE_MAJEUR\np1b1 CORPS\n")

    assert plan.role_of("p1b0") is None
    assert plan.role_of("p1b1") == "CORPS"


def test_an_empty_plan_decides_nothing():
    """Échouer OUVERT : modèle en panne, verdict vide → Ely garde son défaut,
    elle ne rend pas un document mutilé."""
    from app.services.pdf_layout import parse_conversion_plan

    plan = parse_conversion_plan("")

    assert plan.is_empty is True
    assert plan.role_of("p1b0") is None
    assert plan.breaks_before("p1b0") is False
