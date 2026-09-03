# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_exa_search.py
# @brief      Exa en repli de la chaîne — recherche sémantique, appelée
#             seulement quand SearXNG n'a rien rendu.
# @license    MIT
# =============================================================================
"""Pins du fournisseur de recherche Exa.

**Pourquoi en repli et pas dans SearXNG.** SearXNG sait interroger Exa
(`exaapi`), mais il le ferait à **chaque** recherche, mélangé aux vingt autres
moteurs. Franck brûlerait ses crédits Exa en permanence — l'inverse exact du
but de tout le chantier, qui est de ne plus dépendre des quotas.

Deux raisons de plus :

- La clé devrait alors vivre dans `config/searxng/settings.yml`, **suivi par
  git dans un dépôt public** — le chargeur de SearXNG n'interpole aucune
  variable d'environnement dans ces valeurs. En repli, elle reste dans le
  `.env` racine avec les autres.
- Exa fait de la recherche **sémantique**, pas du mot-clé. Dilué parmi vingt
  moteurs généralistes il perdrait sa spécificité ; en repli, il apporte un
  angle que les autres n'ont pas.

**Contrat d'API** relevé dans l'implémentation de référence de SearXNG
(`searx/engines/exaapi.py`), pas deviné :

```
POST https://api.exa.ai/search
en-tête   x-api-key
corps     {"query", "type", "numResults", "contents"}
réponse   {"results": [{"url", "title", "highlights"|"text", …}]}
```

⚠️ Comme tous les fournisseurs depuis #311 : `None` = échec (on continue),
`[]` = a cherché sans rien trouver (on continue aussi).

Run with:  cd backend && python -m pytest tests/test_exa_search.py -v
"""
from __future__ import annotations

import pytest


def _faux_client(payload: dict | None, statut: int = 200):
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

        async def post(self, *_a, **_kw) -> "_Resp":
            return _Resp()

    return _Client


@pytest.mark.asyncio
async def test_exa_parses_highlights(monkeypatch) -> None:
    """Le mode par défaut rend des `highlights` — une liste d'extraits."""
    from app.agent.tools import search_tool as st
    import httpx

    payload = {"results": [
        {"url": "https://fr.wikipedia.org/wiki/France", "title": "France",
         "highlights": ["pays d'Europe", "capitale Paris"]},
        {"url": "https://exemple.fr", "title": "Autre", "highlights": []},
    ]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _faux_client(payload)())

    got = await st._search_exa("France", 3, "cle")

    assert got is not None and len(got) == 2
    assert got[0]["title"] == "France"
    assert "Europe" in got[0]["content"], "les extraits doivent être concaténés"


@pytest.mark.asyncio
async def test_exa_falls_back_to_text_when_present(monkeypatch) -> None:
    """Si l'API rend `text` plutôt que `highlights`, on le lit quand même."""
    from app.agent.tools import search_tool as st
    import httpx

    payload = {"results": [
        {"url": "https://ex.fr", "title": "T", "text": "le contenu de la page"},
    ]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _faux_client(payload)())

    got = await st._search_exa("q", 3, "cle")
    assert got and "contenu de la page" in got[0]["content"]


@pytest.mark.asyncio
async def test_a_result_without_url_is_dropped(monkeypatch) -> None:
    """Un résultat sans URL n'est pas exploitable — l'implémentation de
    référence le jette, on fait pareil."""
    from app.agent.tools import search_tool as st
    import httpx

    payload = {"results": [
        {"title": "sans url", "highlights": ["x"]},
        {"url": "https://ex.fr", "title": "avec url", "highlights": ["y"]},
    ]}
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _faux_client(payload)())

    got = await st._search_exa("q", 3, "cle")
    assert got is not None and len(got) == 1
    assert got[0]["url"] == "https://ex.fr"


@pytest.mark.asyncio
async def test_an_http_error_is_a_failure_not_an_empty_answer(monkeypatch) -> None:
    """`None`, pas `[]` — sinon la chaîne s'arrêterait là (leçon de #311)."""
    from app.agent.tools import search_tool as st
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **_kw: _faux_client({}, statut=401)())

    assert await st._search_exa("q", 3, "mauvaise-cle") is None


@pytest.mark.asyncio
async def test_exa_is_called_only_after_searxng(monkeypatch) -> None:
    """LE PIN QUI COMPTE — Exa est un REPLI, pas un fournisseur du quotidien.

    S'il passait avant SearXNG, chaque recherche consommerait un crédit :
    l'inverse du but poursuivi.
    """
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    ordre: list[str] = []

    async def _searxng(query: str, count: int, base_url: str,
                       categories: str = "general"):
        ordre.append("searxng")
        return [{"title": "t", "url": "https://ex.fr", "content": "c"}]

    async def _exa(query: str, count: int, api_key: str):
        ordre.append("exa")
        return [{"title": "x", "url": "https://x.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_searxng", _searxng)
    monkeypatch.setattr(st, "_search_exa", _exa)

    class _S:
        searxng_url = "http://searxng:8080"
        exa_api_key = "cle"
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    await st._dispatch_search("France", 3)

    assert ordre == ["searxng"], (
        f"Exa a été appelé alors que SearXNG avait répondu (ordre={ordre})"
    )


@pytest.mark.asyncio
async def test_exa_takes_over_when_searxng_is_dry(monkeypatch) -> None:
    """Mais il prend bien le relais quand SearXNG ne rend rien."""
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    attendu = [{"title": "x", "url": "https://x.fr", "content": "c"}]

    async def _searxng(query: str, count: int, base_url: str,
                       categories: str = "general"):
        return None

    async def _exa(query: str, count: int, api_key: str):
        return attendu

    monkeypatch.setattr(st, "_search_searxng", _searxng)
    monkeypatch.setattr(st, "_search_exa", _exa)

    class _S:
        searxng_url = "http://searxng:8080"
        exa_api_key = "cle"
        serper_api_key = ""
        searchcans_api_key = ""
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    results, source = await st._dispatch_search("France", 3)
    assert results == attendu
    assert "exa" in source.lower()


def test_the_probe_covers_exa_when_configured(monkeypatch) -> None:
    """Un Exa à sec ou à clé invalide doit se voir au démarrage."""
    from app.services import service_probe as sp

    class _S:
        searxng_url = ""
        exa_api_key = "cle"
        serper_api_key = ""
        searchcans_api_key = ""
        tavily_api_key = ""

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    assert "exa" in sp._search_providers()
