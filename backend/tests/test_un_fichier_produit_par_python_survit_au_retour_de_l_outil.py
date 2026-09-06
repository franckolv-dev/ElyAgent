# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_un_fichier_produit_par_python_survit_au_retour_de_l_outil.py
# @brief      Audit GPT-6 F05 (06/09/2026) : `python_execute` annonçait une
#             image puis la supprimait avec son répertoire temporaire.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Le code tournait dans un ``TemporaryDirectory`` ; les PNG produits étaient
LISTÉS dans la réponse (« Fichier(s) généré(s) dans le sandbox : audit.png »)
puis effacés à la sortie du contexte — avant que le modèle, l'utilisateur ou
un outil de livraison puisse les toucher. Reproduit par l'audit avec une
image PIL de 1 × 1 pixel.

Désormais les fichiers autorisés sont copiés dans le dépôt de pièces jointes
d'Ely — celui que le chat sert (`/api/attachments`), que Gmail attache et que
Drive téléverse — et la réponse porte leur chemin absolu avec le mode d'emploi
de livraison, comme `browser_screenshot`.

Run with:  cd backend && python -m pytest tests/test_un_fichier_produit_par_python_survit_au_retour_de_l_outil.py -v
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytest.importorskip("PIL")

_CODE_IMAGE = """
from PIL import Image
Image.new("RGB", (1, 1), (255, 0, 0)).save("audit.png")
print("image écrite")
"""


@pytest.mark.asyncio
async def test_une_image_produite_par_python_survit_au_retour_de_l_outil(tmp_path, monkeypatch):
    from app.agent.tools import python_tool

    monkeypatch.setattr(python_tool, "_dossier_livrables", lambda: tmp_path)

    reponse = await python_tool.python_execute.ainvoke({"code": _CODE_IMAGE})

    chemins = re.findall(r"(/\S+audit\.png)", reponse)
    assert chemins, f"la réponse ne nomme pas le fichier par son chemin : {reponse!r}"
    fichier = Path(chemins[0])
    assert fichier.exists(), "l'image a été supprimée avec le sandbox"
    assert fichier.stat().st_size > 0
    assert fichier.parent == tmp_path
    assert "MEDIA:" in reponse, "le mode d'emploi de livraison manque"
    assert "image écrite" in reponse


@pytest.mark.asyncio
async def test_deux_executions_ne_s_ecrasent_pas(tmp_path, monkeypatch):
    from app.agent.tools import python_tool

    monkeypatch.setattr(python_tool, "_dossier_livrables", lambda: tmp_path)

    await python_tool.python_execute.ainvoke({"code": _CODE_IMAGE})
    await python_tool.python_execute.ainvoke({"code": _CODE_IMAGE})

    assert len([p for p in tmp_path.iterdir() if p.name.endswith("audit.png")]) == 2


def test_le_depot_par_defaut_est_servi_par_le_chat_et_attachable():
    """Le contrat qui rend le fichier UTILE : le répertoire par défaut est
    dans la liste blanche du routeur de pièces jointes et de Gmail."""
    from app.agent.tools import python_tool
    from app.agent.tools.gmail_tool import _ALLOWED_ATTACHMENT_DIRS
    from app.routers.attachments import _ALLOWED_DIRS

    dossier = os.path.normpath(str(python_tool._dossier_livrables()))
    assert any(dossier == d or dossier.startswith(d + os.sep) for d in _ALLOWED_DIRS)
    assert any(dossier == d or dossier.startswith(d + os.sep) for d in _ALLOWED_ATTACHMENT_DIRS)
