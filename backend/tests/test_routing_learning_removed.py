# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_routing_learning_removed.py
# @brief      Ménage lot 1 — le routing learning n'a plus de consommateur,
#             il ne doit plus rien coûter : ni code, ni route, ni table.
# @license    MIT
# =============================================================================
"""Pins de suppression du service `routing_learning`.

**Pourquoi.** Le service apprenait des mots-clés pour la passe rapide du
routeur. Ce routeur a disparu avec `supervisor.py` (V1 temps 2, #259). Depuis,
la boucle tourne sans lecteur : mesuré le 29/07, la table compte **0 ligne**,
`match_learned_keywords()` et `mark_match()` n'ont **aucun appelant**, et
`analyze_reformulations_tick()` sort sur un `return` anticipé qui laisse
**41 lignes injoignables** derrière lui.

L'endpoint `/api/settings/routing` n'a lui non plus **aucun client** : ni le
frontend, ni l'extension, ni le desktop, ni Android, ni iOS. La suppression est
donc backend-only, contrairement à ce que supposait la note de mémoire.

**Ce que ces pins garantissent** — et pourquoi chacun est là :

1. les trois modules ne s'importent plus (le code est parti, pas juste
   débranché) ;
2. `app.main` ne les câble plus — vérifié en **important** l'app, pas en
   lisant son source : un pin source-grep ne verrait pas un `NameError` ;
3. la table quitte `Base.metadata`, sinon `create_all` la **recréerait** au
   prochain boot d'une base fraîche et la suppression serait cosmétique ;
4. une migration Alembic la retire des bases **existantes** — `create_all` ne
   sait pas supprimer, et la base de prod porte la table depuis mai.

Run with:  cd backend && python -m pytest tests/test_routing_learning_removed.py -v
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Le code est parti
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", [
    "app.services.routing_learning",
    "app.routers.settings_routing",
    "app.models.learned_routing_keyword",
])
def test_module_no_longer_importable(module: str) -> None:
    """Les trois modules du service ont disparu."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


@pytest.mark.parametrize("relpath", [
    "app/services/routing_learning.py",
    "app/routers/settings_routing.py",
    "app/models/learned_routing_keyword.py",
])
def test_file_no_longer_on_disk(relpath: str) -> None:
    """Le fichier est supprimé, pas seulement vidé de ses imports."""
    assert not (_BACKEND / relpath).exists(), f"{relpath} existe encore"


# ---------------------------------------------------------------------------
# 2. L'application ne le câble plus — vérifié par IMPORT, pas par grep
# ---------------------------------------------------------------------------

def test_app_exposes_no_routing_settings_route() -> None:
    """Plus aucune route sous /api/settings/routing.

    On importe l'app réelle : si `main.py` référençait encore le router
    supprimé, l'import lèverait — ce que ce test veut aussi attraper.
    """
    from app.main import app

    offending = [
        r.path for r in app.routes
        if getattr(r, "path", "").startswith("/api/settings/routing")
    ]
    assert offending == [], f"routes encore exposées : {offending}"


def test_main_schedules_no_routing_learning_tick() -> None:
    """Le job planifié toutes les 6 h a disparu du source de démarrage.

    Le job est enregistré dans le lifespan, qui ne tourne pas à l'import :
    on épingle donc ici l'absence de son identifiant dans `main.py`. Le pin
    d'import ci-dessus couvre, lui, le cas du symbole resté câblé.
    """
    main_src = (_BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "routing_learning" not in main_src
    assert "routing_learning_tick" not in main_src
    assert "settings_routing" not in main_src


# ---------------------------------------------------------------------------
# 3. La table ne sera pas recréée sur une base fraîche
# ---------------------------------------------------------------------------

def test_table_absent_from_metadata() -> None:
    """`create_all` ne doit plus connaître `learned_routing_keywords`."""
    from app.database import Base
    import app.models  # noqa: F401 — enregistre toutes les tables

    assert "learned_routing_keywords" not in Base.metadata.tables


# ---------------------------------------------------------------------------
# 4. La table part aussi des bases EXISTANTES
# ---------------------------------------------------------------------------

def test_a_migration_drops_the_table() -> None:
    """Une révision Alembic retire la table des bases déjà déployées."""
    versions = _BACKEND / "migrations" / "versions"
    dropping = [
        p.name for p in versions.glob("*.py")
        if "learned_routing_keywords" in p.read_text(encoding="utf-8")
        and "drop_table" in p.read_text(encoding="utf-8")
    ]
    assert dropping, (
        "aucune migration ne supprime learned_routing_keywords — la table "
        "resterait sur la base de production"
    )
