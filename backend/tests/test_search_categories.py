# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_search_categories.py
# @brief      `web_search` peut viser une famille de sources — sans jamais
#             perdre les généralistes.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du paramètre `categories` de la recherche.

**Le besoin.** SearXNG range ses moteurs par catégorie. Une requête sans
paramètre n'interroge que `general` : GitHub, StackOverflow, Docker Hub,
Reuters, Adobe Stock ou Dailymotion ne sont **jamais appelés**. Configurés mais
morts.

**La règle, posée par Franck le 01/08 et mesurée.** La catégorie d'intention
**s'ajoute** à `general`, elle ne la remplace pas :

> *« Si je demande des news sur l'IA, il faut interroger Reuters via la
> catégorie news mais il faut également interroger les généralistes, sinon on
> n'aura qu'une seule source. »*

Mesuré sur une instance réelle :

```
« nginx reverse proxy »   general,it     top 5 = 4 généralistes + MDN   ✓
« actualités IA »         general,news   top 5 = actualités réelles      ✓
« capitale de la France » general        top 5 = Wikipédia, Paris        ✓
```

⚠️ **Et pourquoi le choix revient au MODÈLE.** Mesuré aussi : forcer `it` sur
une question non technique détruit la réponse.

```
« capitale de la France » avec general,it
    1. [mdn] Using HTML form validation…
    2. [stackoverflow] change the police/font-size in javascript

« meilleur restaurant Lille » avec general,it
    1. [docker hub] lilleborge/prefixgame-service
```

Deux personnes compétentes choisiraient différemment selon la question : c'est
un **jugement**, donc le modèle le pose, conformément au cadrage du projet.
Une catégorie figée en configuration se tromperait la moitié du temps.

Run with:  cd backend && python -m pytest tests/test_search_categories.py -v
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_general_is_always_included(monkeypatch) -> None:
    """LE PIN QUI COMPTE — l'intention s'ajoute à `general`, ne la remplace pas.

    Sans lui, « les actualités sur l'IA » n'interrogerait que Reuters : une
    source unique là où l'on veut un recoupement.
    """
    from app.agent.tools import search_tool as st

    vues: list[str] = []

    async def _capture(query: str, count: int, base_url: str, categories: str = ""):
        vues.append(categories)
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _capture)

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    await st._dispatch_search("actualités IA", 3, categories="news")

    assert vues, "SearXNG n'a pas été appelé"
    assert "general" in vues[0], (
        f"catégories transmises = {vues[0]!r} — « general » manque, la recherche "
        f"n'aurait qu'une seule famille de sources"
    )
    assert "news" in vues[0]


@pytest.mark.asyncio
async def test_no_category_means_general_only(monkeypatch) -> None:
    """Sans intention déclarée, on reste sur les généralistes.

    C'est le comportement par défaut, et il est mesuré comme le bon : ajouter
    `it` à une question quelconque remonte de la documentation JavaScript en
    tête d'une question de géographie.
    """
    from app.agent.tools import search_tool as st

    vues: list[str] = []

    async def _capture(query: str, count: int, base_url: str, categories: str = ""):
        vues.append(categories)
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _capture)

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    await st._dispatch_search("capitale de la France", 3)

    assert vues == ["general"]


@pytest.mark.asyncio
async def test_an_unknown_category_is_ignored_not_forwarded(monkeypatch) -> None:
    """Une catégorie inventée par le modèle ne part pas telle quelle.

    SearXNG répondrait sans rien trouver, et la chaîne le lirait comme « ce
    fournisseur n'a rien » — l'erreur de #311 rejouée par le haut.
    """
    from app.agent.tools import search_tool as st

    vues: list[str] = []

    async def _capture(query: str, count: int, base_url: str, categories: str = ""):
        vues.append(categories)
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _capture)

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())
    st.reset_quota_state()

    await st._dispatch_search("test", 3, categories="cuisine-moleculaire")

    assert vues == ["general"], (
        f"catégorie inconnue transmise telle quelle : {vues[0]!r}"
    )


def test_the_tool_documents_the_allowed_categories() -> None:
    """Le modèle doit lire QUELLES catégories existent, sinon il en invente.

    La description part dans le prompt : c'est là que se joue le choix.
    """
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry

    register_all()
    outil = next(t for t in get_skill_registry().all_tools if t.name == "web_search")
    d = (outil.description or "").lower()

    for cat in ("it", "news", "images", "videos"):
        assert cat in d, f"la description ne mentionne pas la catégorie « {cat} »"


def test_the_config_enables_franck_engines() -> None:
    """Les moteurs demandés sont activés, et qwant écarté.

    ⚠️ `adobe stock`, `gitlab` et `mojeek` sont `disabled: true` dans les
    réglages livrés par l'image : sans bascule explicite ils ne tournent pas.
    Les autres sont déjà actifs — on ne les redéclare PAS, c'est ce qui faisait
    échouer le chargement (chaque moteur a ses propres paramètres).

    Qwant est écarté : il tape une API non documentée et se heurte à DataDome.
    """
    from pathlib import Path

    conf = (Path(__file__).resolve().parents[2] / "config" / "searxng"
            / "settings.yml").read_text(encoding="utf-8")

    for moteur in ("adobe stock", "gitlab", "mojeek"):
        assert f"name: {moteur}" in conf, f"{moteur} n'est pas activé"
    assert "name: qwant" in conf and "disabled: true" in conf, (
        "qwant doit être explicitement désactivé — il est actif par défaut"
    )
    assert "json" in conf, "formats: [json] reste indispensable à l'API"
