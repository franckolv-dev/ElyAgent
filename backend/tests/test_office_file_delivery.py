# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_office_file_delivery.py
# @brief      Un fichier bureautique produit par Ely doit être téléchargeable.
# @license    MIT
# =============================================================================
"""Le verrou de livraison des fichiers bureautiques (constat d'audit 25/07).

`pdf_to_docx` écrit dans ``/tmp/ely-docx`` (pdf_tool.py:215) et rend le
chemin à l'utilisateur. Mais les deux listes blanches de livraison —
``media_router`` (qui transforme un ``MEDIA:<path>`` en pièce jointe) et le
routeur ``/api/attachments`` (qui sert le fichier) — n'autorisaient **ni
l'extension `.docx`, ni le répertoire `/tmp/ely-docx`**.

Conséquence vécue : Ely convertit un PDF en Word, annonce le fichier… et
l'utilisateur ne peut pas le récupérer depuis le chat. Le seul contournement
était de passer par Drive.

Ces tests verrouillent la cohérence des deux listes et la présence des
formats bureautiques courants.

Run with:  cd backend && python -m pytest tests/test_office_file_delivery.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.routers.attachments import _ALLOWED_DIRS as ATT_DIRS
from app.routers.attachments import _ALLOWED_EXTS as ATT_EXTS
from app.services.media_router import _ALLOWED_DIRS as MEDIA_DIRS
from app.services.media_router import _ALLOWED_EXTS as MEDIA_EXTS


# Les formats qu'Ely sait produire ou recevoir et qu'un utilisateur attend
# de pouvoir ouvrir : bureautique + ebook.
_OFFICE_EXTS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".epub"}


@pytest.mark.parametrize("ext", sorted(_OFFICE_EXTS))
def test_office_extensions_are_deliverable(ext):
    """Un .docx produit par pdf_to_docx doit pouvoir être livré ET servi."""
    assert ext in MEDIA_EXTS, f"{ext} absent de media_router — pièce jointe refusée"
    assert ext in ATT_EXTS, f"{ext} absent de /api/attachments — téléchargement refusé"


def test_docx_output_dir_is_whitelisted():
    """`pdf_to_docx` écrit dans /tmp/ely-docx : sans ce répertoire dans les
    listes, le fichier existe mais reste inatteignable."""
    from app.agent.tools.pdf_tool import _DOCX_OUT_DIR

    out = str(_DOCX_OUT_DIR)
    assert any(out.startswith(d) for d in MEDIA_DIRS), (
        f"{out} hors des répertoires de media_router"
    )
    assert any(out.startswith(d) for d in ATT_DIRS), (
        f"{out} hors des répertoires de /api/attachments"
    )


def test_the_two_allowlists_stay_in_sync():
    """Les deux listes doivent rester identiques : une divergence produit le
    pire des cas — une pièce jointe annoncée dans le chat puis refusée au
    téléchargement (ou l'inverse)."""
    assert MEDIA_EXTS == ATT_EXTS, (
        f"extensions désynchronisées : "
        f"media seul={sorted(MEDIA_EXTS - ATT_EXTS)} "
        f"attachments seul={sorted(ATT_EXTS - MEDIA_EXTS)}"
    )
    assert set(MEDIA_DIRS) == set(ATT_DIRS), (
        f"répertoires désynchronisés : "
        f"media seul={sorted(set(MEDIA_DIRS) - set(ATT_DIRS))} "
        f"attachments seul={sorted(set(ATT_DIRS) - set(MEDIA_DIRS))}"
    )


def test_executables_are_still_refused():
    """La liste blanche reste une liste BLANCHE : on élargit aux formats
    bureautiques, on n'ouvre pas la porte aux binaires."""
    for dangerous in (".exe", ".sh", ".py", ".dylib", ".so", ".app", ".bat"):
        assert dangerous not in MEDIA_EXTS
        assert dangerous not in ATT_EXTS


def test_path_traversal_still_refused(tmp_path, monkeypatch):
    """Élargir les listes ne doit pas affaiblir la garde anti-traversal."""
    from fastapi import HTTPException

    from app.routers.attachments import _resolve_safe_path

    with pytest.raises(HTTPException):
        _resolve_safe_path("/tmp/ely-docx/../../etc/passwd")
    with pytest.raises(HTTPException):
        _resolve_safe_path("/etc/passwd")
