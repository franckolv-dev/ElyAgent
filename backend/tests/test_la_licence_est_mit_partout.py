# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_la_licence_est_mit_partout.py
# @brief      Un dépôt qui se dit MIT ne distribue aucun fichier qui dit
#             autre chose.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Passage sous MIT (03/09/2026).

Le dépôt a raconté jusqu'à trois histoires de licence à la fois : `LICENSE`
disait Elastic 2.0, `COMMERCIAL_LICENSE.md` disait PolyForm, et des en-têtes
gardaient l'un ou l'autre. La première passe MIT avait réécrit 973 en-têtes
et laissé, dans 327 fichiers, le bloc « RÉSUMÉ DES CONDITIONS » qui INTERDIT
la revente — la contradiction même que MIT lève. Un test qui lit tout le
dépôt vaut mieux qu'une relecture des seuls README.

Le CHANGELOG et les README racontent l'histoire (« Ely est passée de
l'Elastic License 2.0 à MIT ») : ils ont le droit de nommer l'ancienne
licence, pas d'en porter les termes.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]

# Ce qu'un fichier du dépôt n'a plus le droit de porter.
_TERMES_INTERDITS = (
    "@license    Elastic",
    "@license    PolyForm",
    "elastic.co/licensing",
    "polyformproject.org",
    "All rights reserved",
    "RÉSUMÉ DES CONDITIONS",
    "RESUME DES CONDITIONS",
    "INTERDIT : Revente",
    "INTERDIT : Toute utilisation commerciale",
)
# Les textes d'histoire : ils nomment l'ancienne licence, sans ses termes.
_HISTOIRE = {"CHANGELOG.md", "README.md", "README.fr.md"}
_BINAIRES = (".png", ".jpg", ".jpeg", ".glb", ".ico", ".woff", ".woff2", ".lock", ".pdf")


def _fichiers_suivis() -> list[Path]:
    try:
        sortie = subprocess.check_output(["git", "ls-files"], cwd=RACINE, text=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("pas de dépôt git (image applicative)")
    return [RACINE / f for f in sortie.split("\n") if f and not f.endswith(_BINAIRES)]


def test_le_fichier_licence_est_mit():
    texte = (RACINE / "LICENSE").read_text(encoding="utf-8")
    assert texte.lstrip().startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in texte
    assert not (RACINE / "COMMERCIAL_LICENSE.md").exists()
    assert not (RACINE / "licence-ELY.md").exists()


def test_les_manifestes_declarent_mit():
    pyproject = (RACINE / "backend/pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "MIT"' in pyproject or 'license = {text = "MIT"}' in pyproject
    package = json.loads((RACINE / "frontend/package.json").read_text(encoding="utf-8"))
    assert package.get("license") == "MIT"


def test_aucun_fichier_suivi_ne_porte_les_termes_de_l_ancienne_licence():
    fautifs: list[str] = []
    for chemin in _fichiers_suivis():
        # Ce fichier-ci porte les termes interdits dans sa liste : il se
        # prendrait lui-même en défaut (vu en CI, pas en local où il n'était
        # pas encore suivi par git).
        if chemin.name in _HISTOIRE or chemin == Path(__file__).resolve():
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for terme in _TERMES_INTERDITS:
            if terme in texte:
                fautifs.append(f"{chemin.relative_to(RACINE)} : {terme}")
                break
    assert fautifs == [], "\n".join(fautifs)


def test_les_en_tetes_qui_declarent_une_licence_declarent_mit():
    """Tout fichier portant un `@license` le porte en MIT, avec l'URL qui va
    avec sur la ligne suivante."""
    mauvais: list[str] = []
    for chemin in _fichiers_suivis():
        try:
            lignes = chemin.read_text(encoding="utf-8").splitlines()[:40]
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for i, ligne in enumerate(lignes):
            if "@license" in ligne:
                if "MIT" not in ligne or i + 1 >= len(lignes) or "opensource.org/licenses/MIT" not in lignes[i + 1]:
                    mauvais.append(str(chemin.relative_to(RACINE)))
                break
    assert mauvais == [], "\n".join(mauvais)
