# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_ghost_tools_resolved.py
# @brief      Quatre noms étaient bindés au profil sans exister au catalogue.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de la résolution des outils fantômes.

**Le constat**, produit par le contrôle de réalité (#265) dès son premier
démarrage et confirmé en production : le profil ``default`` déclarait
**86 noms d'outils, dont 82 existaient**. Quatre étaient bindés dans le vide —
écrits dans le code, jamais ajoutés à la liste ``tools=[…]`` de leur skill :

- ``browser_history_search``, ``browser_bookmarks_search``,
  ``browser_downloads_search`` — définis dans ``browser_extension_tool.py``,
  absents des 12 outils déclarés par ``browser_extension_skill`` ;
- ``gmail_empty_trash`` — défini dans ``gmail_tool.py``, absent de
  ``gmail_skill``.

Un nom bindé sans existence ne lève rien : l'agent ne voit simplement jamais
l'outil et affirme de bonne foi qu'il ne l'a pas. C'est le défaut de #257
(``web_search_news``), reproduit quatre fois.

**Arbitrage de Franck** : enregistrer les trois outils navigateur — ils
donnent accès à SON historique, ses favoris et ses téléchargements Chrome, une
capacité écrite mais inatteignable jusqu'ici — et **retirer
``gmail_empty_trash`` du profil** : il supprime DÉFINITIVEMENT des mails, et
``gmail_trash_emails`` couvre déjà le besoin normal.

Run with:  cd backend && python -m pytest tests/test_ghost_tools_resolved.py -v
"""
from __future__ import annotations

import pytest

_BROWSER_SEARCHES = [
    "browser_history_search",
    "browser_bookmarks_search",
    "browser_downloads_search",
]


def _catalog() -> set[str]:
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    return {t.name for t in get_skill_registry().all_tools}


@pytest.mark.parametrize("name", _BROWSER_SEARCHES)
def test_the_browser_searches_are_registered(name):
    """LE test du lot : ils existaient dans le code, ils entrent au catalogue."""
    assert name in _catalog(), f"{name} reste introuvable pour l'agent"


@pytest.mark.parametrize("name", _BROWSER_SEARCHES)
def test_the_browser_searches_stay_bound_to_the_profile(name):
    """Exister au catalogue ne suffit pas — encore faut-il que l'agent les
    voie (c'est très exactement la leçon de #257)."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    assert name in _DEFAULT_TOOLS


def test_emptying_the_gmail_trash_is_no_longer_bound():
    """Il supprime définitivement — aucune API Gmail ne récupère un message
    passé par batchDelete. Le besoin courant est couvert par
    gmail_trash_emails, qui reste réversible 30 jours."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    assert "gmail_empty_trash" not in _DEFAULT_TOOLS


def test_the_profile_has_no_ghost_left():
    """La raison d'être du lot : plus aucun nom bindé sans existence."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    catalog = _catalog()
    if "orchestrate" not in catalog:
        pytest.skip("auto-découverte incomplète dans ce contexte de test")

    ghosts = sorted(set(_DEFAULT_TOOLS) - catalog)
    assert not ghosts, f"noms bindés qui n'existent pas : {ghosts}"
