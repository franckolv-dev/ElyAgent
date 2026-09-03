# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_version_is_one_number.py
# @brief      Quatre fichiers déclarent la version. Ils doivent dire la même.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La version d'Ely vit à QUATRE endroits, et rien ne les tenait ensemble.

    backend/pyproject.toml      version = "…"
    backend/app/main.py         FastAPI(version="…")   → sert /health
    frontend/package.json       "version": "…"
    backend/uv.lock             [[package]] cyber-entity-backend

⚠️ La quatrième s'est signalée toute seule, et c'est instructif : je n'en
connaissais que trois en écrivant ce pin, et `uv sync` a réécrit `uv.lock`
pendant la même session pour y reporter la version de `pyproject.toml`. Une
source de vérité qu'on ne savait pas être une source — exactement ce que ce
fichier existe pour attraper. Elle n'aurait divergé qu'au premier `uv sync`
oublié, c'est-à-dire longtemps après le bump.

Le DEUXIÈME est celui qui compte pour l'utilisateur : le panneau SESSION
affiche `VER:` en lisant `/health`, donc `main.py`. Les trois autres sont lus
par les outils de build et par quiconque inspecte le dépôt.

⚠️ POURQUOI CE PIN EXISTE (22/08). Une montée de version se fait à la main, en
quatre endroits, à quatre formats différents. Il suffit d'en oublier un pour que
`/health` annonce une version que le dépôt ne porte pas — et personne ne s'en
aperçoit, parce qu'un numéro de version faux ne casse rien. C'est exactement le
profil des dérives que ce dépôt traque : ça ne plante pas, ça ment.

⚠️ ET LE CHANGELOG. Un numéro bumpé sans entrée correspondante fait installer
une version dont personne ne peut dire ce qu'elle contient. Le pin l'exige
aussi — la ligne du haut du CHANGELOG doit nommer la version courante.

⚠️ IL Y A UNE CINQUIÈME SOURCE, ET C'EST LA SEULE QUE GITHUB AFFICHE (23/08).
Le **tag git**. Les quatre fichiers ci-dessus sont passés à 2.4.0 et mergés, et
la page d'accueil du dépôt a continué d'annoncer **v2.3.0** — parce que la
barre latérale « Releases » lit les tags, pas `pyproject.toml`. Franck l'a
signalé deux fois ; la deuxième, la cause n'était plus le bump, c'était le tag
absent.

    git tag -a vX.Y.Z <sha du commit de release> -F -   # message = le lot
    git push origin vX.Y.Z

**Elle n'est délibérément PAS épinglée ici**, et la raison vaut d'être écrite :
le commit qui bumpe précède forcément le tag qui le désigne. Un test exigeant
le tag serait rouge sur *toutes* les PR de version, par construction — un pin
qui rougit quand tout va bien apprend à ignorer les pins. La garde est donc
procédurale, pas mécanique : c'est la dernière ligne de la montée de version.

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


def _depuis_lock() -> str:
    """La version que `uv.lock` attribue au paquet du dépôt lui-même.

    Elle est réécrite par `uv sync`, donc elle suit `pyproject.toml` — mais
    seulement quand quelqu'un lance la commande. Entre le bump et le premier
    `uv sync`, le verrou annonce l'ancienne version.
    """
    texte = (RACINE / "backend" / "uv.lock").read_text(encoding="utf-8")
    trouve = re.search(
        r'name = "cyber-entity-backend"\s*\nversion = "([^"]+)"', texte,
    )
    assert trouve, "uv.lock ne déclare plus la version du paquet du dépôt"
    return trouve.group(1)


def test_the_four_sources_agree():
    """LE pin. Quatre formats, quatre fichiers, une seule vérité."""
    sources = {
        "backend/pyproject.toml": _depuis_pyproject(),
        "backend/app/main.py": _depuis_main(),
        "frontend/package.json": _depuis_package(),
        "backend/uv.lock": _depuis_lock(),
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
    "backend/uv.lock",
    "CHANGELOG.md",
])
def test_every_source_exists(fichier):
    """Un pin qui lit un fichier absent passerait en silence si on le laissait
    faire — ici il rougit, ce qui force à venir voir."""
    assert (RACINE / fichier).exists(), f"{fichier} a disparu"
