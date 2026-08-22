# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_version_is_one_number.py
# @brief      Trois fichiers déclarent la version. Ils doivent dire la même.
# @license    Elastic License 2.0
# =============================================================================
"""La version d'Ely vit à TROIS endroits, et rien ne les tenait ensemble.

    backend/pyproject.toml      version = "…"
    backend/app/main.py         FastAPI(version="…")   → sert /health
    frontend/package.json       "version": "…"

Le troisième est celui qui compte pour l'utilisateur : le panneau SESSION
affiche `VER:` en lisant `/health`, donc `main.py`. Les deux autres sont lus
par les outils de build et par quiconque inspecte le dépôt.

⚠️ POURQUOI CE PIN EXISTE (22/08). Une montée de version se fait à la main, en
trois endroits, à trois formats différents. Il suffit d'en oublier un pour que
`/health` annonce une version que le dépôt ne porte pas — et personne ne s'en
aperçoit, parce qu'un numéro de version faux ne casse rien. C'est exactement le
profil des dérives que ce dépôt traque : ça ne plante pas, ça ment.

⚠️ ET LE CHANGELOG. Un numéro bumpé sans entrée correspondante fait installer
une version dont personne ne peut dire ce qu'elle contient. Le pin l'exige
aussi — la ligne du haut du CHANGELOG doit nommer la version courante.

Run with:  cd backend && python -m pytest tests/test_version_is_one_number.py -v
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def _depuis_pyproject() -> str:
    texte = (RACINE / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    trouve = re.search(r'^version\s*=\s*"([^"]+)"', texte, re.M)
    assert trouve, "pyproject.toml ne déclare plus de version"
    return trouve.group(1)


def _depuis_main() -> str:
    texte = (RACINE / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    trouve = re.search(r'version="([0-9][^"]*)"', texte)
    assert trouve, "main.py ne passe plus de version à FastAPI"
    return trouve.group(1)


def _depuis_package() -> str:
    data = json.loads(
        (RACINE / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert "version" in data, "package.json ne déclare plus de version"
    return data["version"]


def test_the_three_sources_agree():
    """LE pin. Trois formats, trois fichiers, une seule vérité."""
    sources = {
        "backend/pyproject.toml": _depuis_pyproject(),
        "backend/app/main.py": _depuis_main(),
        "frontend/package.json": _depuis_package(),
    }
    distinctes = set(sources.values())
    assert len(distinctes) == 1, (
        "les sources de version divergent : "
        + ", ".join(f"{f} = {v}" for f, v in sources.items())
        + ". `/health` sert celle de main.py — c'est elle que l'utilisateur "
        "voit dans le panneau SESSION."
    )


def test_the_version_is_semver():
    """Un numéro qui ne se compare pas ne sert à rien pour décider d'une mise
    à jour."""
    version = _depuis_main()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"« {version} » n'est pas un numéro sémantique X.Y.Z"
    )


def test_the_changelog_documents_the_current_version():
    """⚠️ Un numéro bumpé sans entrée correspondante fait installer une version
    dont personne ne peut dire ce qu'elle contient.

    On regarde la PREMIÈRE entrée versionnée du fichier : le changelog est
    antichronologique, donc c'est la plus récente. Les sections non versionnées
    (`[Non versionné]`) sont ignorées — elles existent délibérément, pour un lot
    livré dont le numéro n'a jamais été attribué, et inventer ce numéro
    graverait dans l'historique public une version qui n'a jamais été taguée.
    """
    texte = (RACINE / "CHANGELOG.md").read_text(encoding="utf-8")
    entrees = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", texte, re.M)
    assert entrees, "le CHANGELOG ne contient aucune entrée versionnée"
    assert entrees[0] == _depuis_main(), (
        f"le code annonce {_depuis_main()}, le CHANGELOG ouvre sur "
        f"{entrees[0]}. Une version sans entrée n'est pas descriptible."
    )


@pytest.mark.parametrize("fichier", [
    "backend/pyproject.toml",
    "backend/app/main.py",
    "frontend/package.json",
    "CHANGELOG.md",
])
def test_every_source_exists(fichier):
    """Un pin qui lit un fichier absent passerait en silence si on le laissait
    faire — ici il rougit, ce qui force à venir voir."""
    assert (RACINE / fichier).exists(), f"{fichier} a disparu"
