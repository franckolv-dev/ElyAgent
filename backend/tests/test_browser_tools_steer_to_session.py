# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_browser_tools_steer_to_session.py
# @brief      Deux familles de navigateur, un seul nom évident — et c'est le
#             mauvais. Les descriptions doivent aiguiller vers la bonne.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de l'aiguillage entre navigateur sans session et Chrome de l'utilisateur.

**Le constat, mesuré le 26/07.** Ely dispose de DEUX familles d'outils
navigateur, toutes deux bindées dans le profil ``default`` :

===============================  ==========================================
Playwright serveur — AUCUNE      Extension — le vrai Chrome de Franck,
session, aucun cookie            avec ses cookies et ses sessions
===============================  ==========================================
``browser_navigate``             ``browser_tab_navigate``
``browser_get_text``             ``browser_tab_read_text``
``browser_screenshot``           ``browser_tab_screenshot``
===============================  ==========================================

Les noms ne diffèrent que d'un mot, et **le plus évident est le mauvais** pour
tout site derrière authentification. Franck a vérifié qu'Ely sait consulter
LinkedIn et Doctolib **déjà connectée** via son Chrome ; mais une consigne qui
dit « utilise le navigateur web » laisse le modèle choisir, et
``browser_navigate`` se présente comme l'outil de navigation général.

``browser_tab_read_text`` fait déjà sa part du travail :

    « USE THIS for anything behind authentication: LinkedIn profile,
      post impressions, Gmail UI, Amazon orders, X timeline… »

Mais ``browser_navigate`` ne dit **nulle part** qu'il n'a pas de session. Le
modèle n'a donc aucun moyen de choisir correctement : il apprend l'échec en
recevant une page de connexion, et en déduit — comme Ely l'a fait — qu'elle
« ne peut pas accéder à LinkedIn ».

Ce lot ne change aucun comportement d'exécution : il rend une capacité déjà
présente **atteignable**, en corrigeant l'information sur laquelle le modèle
choisit. Même classe que ``web_search_news`` absent du profil (#257).

Run with:  cd backend && python -m pytest tests/test_browser_tools_steer_to_session.py -v
"""
from __future__ import annotations

import pytest

# Les outils Playwright qui RAMÈNENT DU CONTENU : ceux dont la sortie peut
# être une page de connexion sans que le modèle s'en doute.
_SESSIONLESS_FETCHERS = ["browser_navigate", "browser_get_text", "browser_screenshot"]


def _tools() -> dict:
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    return {t.name: t for t in get_skill_registry().all_tools}


# ------------------------------------------------- la famille sans session

@pytest.mark.parametrize("name", _SESSIONLESS_FETCHERS)
def test_a_sessionless_tool_says_it_has_no_session(name):
    """LE test du lot. Un outil qui rendra une page de connexion sur tout site
    authentifié doit l'annoncer — sinon le modèle le découvre par l'échec."""
    desc = (_tools()[name].description or "").lower()

    assert "no login" in desc or "not logged in" in desc or "no session" in desc, (
        f"{name} ne dit pas qu'il navigue sans session : le modèle le choisira "
        f"pour LinkedIn et recevra une page de connexion.\n---\n{desc[:400]}"
    )


@pytest.mark.parametrize("name", _SESSIONLESS_FETCHERS)
def test_a_sessionless_tool_names_the_alternative(name):
    """Dire « je ne peux pas » ne suffit pas : il faut dire quoi appeler à la
    place, sous son nom exact, sinon le modèle abandonne la tâche."""
    desc = _tools()[name].description or ""

    assert "browser_open_tab" in desc or "browser_tab_" in desc, (
        f"{name} signale sa limite sans nommer la famille qui, elle, sait "
        f"faire — le modèle conclura que la capacité n'existe pas."
    )


def test_the_authenticated_family_still_advertises_itself():
    """Garde-fou : l'aiguillage vaut par sa destination. Si un jour cette
    mention disparaît, l'aiguillage pointe vers le vide."""
    desc = (_tools()["browser_tab_read_text"].description or "").lower()

    assert "authentication" in desc or "authentifi" in desc
    assert "linkedin" in desc


# ------------------------------------------------------ les deux familles

def test_both_families_are_bound_so_the_choice_is_real():
    """L'aiguillage ne sert à rien si l'une des deux familles est absente du
    profil : le modèle ne peut pas appeler ce qu'il ne voit pas (#257)."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    assert "browser_navigate" in _DEFAULT_TOOLS
    for needed in ("browser_open_tab", "browser_tab_read_text", "browser_tab_wait_loaded"):
        assert needed in _DEFAULT_TOOLS, (
            f"{needed} absent du profil : Ely ne peut pas atteindre un site "
            f"authentifié même en le voulant"
        )


def test_the_notice_stays_short():
    """Ces descriptions partent à CHAQUE tour, sur chaque appel de modèle, et
    sur les trois outils. Un avertissement bavard se paie en tokens à vie —
    cf. la ventilation du contexte (#255) : les schémas d'outils sont un poste
    permanent, pas un coût ponctuel."""
    from app.skills.builtin.browser_skill import _NO_SESSION_NOTICE

    assert len(_NO_SESSION_NOTICE) < 220, (
        f"l'aiguillage coûte {len(_NO_SESSION_NOTICE)} caractères × 3 outils × "
        f"chaque tour"
    )


def test_the_notice_has_a_single_source():
    """Trois docstrings recopiées dériveraient. Une seule constante, appliquée
    aux trois — sinon le jour où l'un des noms d'outil change, deux
    descriptions sur trois mentent."""
    from app.skills.builtin import browser_skill

    tools = _tools()
    for name in _SESSIONLESS_FETCHERS:
        assert browser_skill._NO_SESSION_NOTICE in (tools[name].description or "")
