# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_searxng_search.py
# @brief      SearXNG en tête de chaîne — une recherche auto-hébergée, sans clé
#             et sans quota, avec les fournisseurs à crédits en repli.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du fournisseur de recherche SearXNG.

**Pourquoi.** Le 31/07, deux fournisseurs sur trois étaient à court de crédits
et la chaîne était muette. Les quotas gratuits mensuels sont une dépendance
que rien ne contrôle côté Ely.

SearXNG est un **méta-moteur auto-hébergé** : pas de clé, pas de compte, pas de
quota. Il n'a pas d'index propre — il interroge les moteurs amont depuis l'IP
du serveur. On ne supprime donc pas la dépendance à Google ou Bing : on
supprime l'intermédiaire payant, et on récupère le risque de blocage. Pour un
usage personnel c'est le bon échange ; c'est aussi pour ça que les fournisseurs
à crédits restent **en repli**.

Il sert enfin la ligne de souveraineté du projet : aujourd'hui chaque requête
part chez un tiers **sous la clé de Franck**, donc reliée à lui. Avec SearXNG
elle sort de sa machine sans intermédiaire qui la lui associe.

**Le piège spécifique de cette installation**, et c'est lui que le pin
principal garde : l'API JSON de SearXNG **n'est pas active par défaut** dans
plusieurs images. Sans `formats: [json]` dans `settings.yml`, le conteneur est
vert, il répond, et il ne rend rien d'exploitable. C'est exactement la panne du
31/07 — un service qui échoue poliment.

⚠️ D'où la distinction, héritée de #311 et #313 :

```
pas de `results` dans la réponse  → None  = ÉCHEC (API mal configurée)
`results: []`                    → []    = il a cherché, rien trouvé
```

Confondre les deux ferait taire toute la chaîne derrière SearXNG.

Run with:  cd backend && python -m pytest tests/test_searxng_search.py -v
"""
from __future__ import annotations

import pytest


def _faux_client(payload: dict | None, statut: int = 200):
    """Client httpx minimal — signature alignée sur l'usage réel, pas `**kwargs`."""
    class _Resp:
        status_code = statut

        def raise_for_status(self) -> None:
            if statut >= 400:
                raise RuntimeError(f"HTTP {statut}")

        def json(self) -> dict:
            if payload is None:
                raise ValueError("réponse illisible")
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def get(self, *_a, **_kw) -> "_Resp":
            return _Resp()

    return _Client


# ---------------------------------------------------------------------------
# 1. Le cas nominal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_searxng_parses_its_results(monkeypatch) -> None:
    from app.agent.tools import search_tool as st
    import httpx

    payload = {
        "query": "France",
        "number_of_results": 2,
        "results": [
            {"url": "https://fr.wikipedia.org/wiki/France", "title": "France",
             "content": "pays d'Europe de l'Ouest", "engine": "duckduckgo"},
            {"url": "https://www.britannica.com/place/France", "title": "France | Britannica",
             "content": "History, maps, flag", "engine": "google"},
        ],
        "unresponsive_engines": [],
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _faux_client(payload)())

    got = await st._search_searxng("France", 3, "http://searxng:8080")

    assert got is not None and len(got) == 2
    assert got[0]["title"] == "France"
    assert got[0]["url"].startswith("https://fr.wikipedia.org")
    assert "Europe" in got[0]["content"]


@pytest.mark.asyncio
async def test_searxng_honours_the_requested_count(monkeypatch) -> None:
    from app.agent.tools import search_tool as st
    import httpx

    payload = {"results": [
        {"url": f"https://ex{i}.fr", "title": f"t{i}", "content": f"c{i}"}
        for i in range(10)
    ]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _faux_client(payload)())

    got = await st._search_searxng("France", 3, "http://searxng:8080")
    assert len(got) == 3


# ---------------------------------------------------------------------------
# 2. LE PIN QUI COMPTE — API JSON désactivée ≠ zéro résultat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_response_without_results_key_is_a_failure(monkeypatch) -> None:
    """Pas de clé `results` = l'API JSON n'est pas active → None, pas [].

    Sans ça, un SearXNG mal configuré ferait taire Serper, SearchCans, Tavily
    et DuckDuckGo derrière lui — la panne exacte du 31/07, rejouée par le
    fournisseur censé la prévenir.
    """
    from app.agent.tools import search_tool as st
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **_kw: _faux_client({"detail": "Invalid settings"})())

    assert await st._search_searxng("France", 3, "http://searxng:8080") is None


@pytest.mark.asyncio
async def test_an_empty_results_list_is_an_answer(monkeypatch) -> None:
    """`results: []` = il a cherché et n'a rien trouvé. C'est une réponse."""
    from app.agent.tools import search_tool as st
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **_kw: _faux_client({"results": []})())

    assert await st._search_searxng("zzz-introuvable", 3, "http://searxng:8080") == []


@pytest.mark.asyncio
async def test_an_http_error_is_a_failure(monkeypatch) -> None:
    from app.agent.tools import search_tool as st
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **_kw: _faux_client({}, statut=403)())

    assert await st._search_searxng("France", 3, "http://searxng:8080") is None


# ---------------------------------------------------------------------------
# 3. Sa place dans la chaîne
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_searxng_comes_first_when_configured(monkeypatch) -> None:
    """Configuré, il passe AVANT les fournisseurs à crédits."""
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    attendu = [{"title": "France", "url": "https://ex.fr", "content": "…"}]

    async def _searxng(query: str, count: int, base_url: str,
                       categories: str = "general"):
        return attendu

    async def _jamais(query: str, count: int, api_key: str):
        raise AssertionError("un fournisseur à crédits a été appelé avant SearXNG")

    monkeypatch.setattr(st, "_search_searxng", _searxng)
    monkeypatch.setattr(st, "_search_serper", _jamais)
    monkeypatch.setattr(st, "_search_searchcans", _jamais)
    monkeypatch.setattr(st, "_search_tavily", _jamais)

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = "k"
        searchcans_api_key = "k"
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = "k"

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    results, source = await st._dispatch_search("France", 3)
    assert results == attendu
    assert "searxng" in source.lower()


@pytest.mark.asyncio
async def test_a_dead_searxng_falls_through_to_the_paid_ones(monkeypatch) -> None:
    """S'il est absent ou muet, les fournisseurs à crédits prennent le relais."""
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    attendu = [{"title": "France", "url": "https://ex.fr", "content": "…"}]

    async def _mort(query: str, count: int, base_url: str,
                    categories: str = "general"):
        return None

    async def _tavily(query: str, count: int, api_key: str):
        return attendu

    async def _vide(query: str, count: int, api_key: str):
        return []

    monkeypatch.setattr(st, "_search_searxng", _mort)
    monkeypatch.setattr(st, "_search_serper", _vide)
    monkeypatch.setattr(st, "_search_searchcans", _vide)
    monkeypatch.setattr(st, "_search_tavily", _tavily)

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = "k"
        searchcans_api_key = "k"
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = "k"

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    results, _ = await st._dispatch_search("France", 3)
    assert results == attendu


@pytest.mark.asyncio
async def test_searxng_is_skipped_when_not_configured(monkeypatch) -> None:
    """Sans URL, on ne l'appelle pas du tout.

    Ne pas le sonder n'est pas un constat : c'est son état déclaré. Un
    aller-retour vers un service qu'on sait absent est de la latence pure —
    c'est la leçon du disjoncteur.
    """
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    appele = False

    async def _searxng(query: str, count: int, base_url: str,
                       categories: str = "general"):
        nonlocal appele
        appele = True
        return []

    async def _tavily(query: str, count: int, api_key: str):
        return [{"title": "x", "url": "https://ex.fr", "content": "…"}]

    monkeypatch.setattr(st, "_search_searxng", _searxng)
    monkeypatch.setattr(st, "_search_tavily", _tavily)

    class _S:
        searxng_url = ""            # non configuré
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = "k"

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    await st._dispatch_search("France", 3)
    assert not appele, "SearXNG a été appelé alors qu'aucune URL n'est configurée"


# ---------------------------------------------------------------------------
# 4. La sonde doit le couvrir
# ---------------------------------------------------------------------------

def test_the_probe_covers_searxng_when_configured(monkeypatch) -> None:
    """Un SearXNG debout mais mal configuré doit se voir au démarrage."""
    from app.services import service_probe as sp

    class _S:
        searxng_url = "http://searxng:8080"
        serper_api_key = ""
        searchcans_api_key = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    assert "searxng" in sp._search_providers()
