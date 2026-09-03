# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_search_chain_never_goes_mute.py
# @brief      Un fournisseur à sec ne doit pas faire taire toute la chaîne.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de l'incident « Ely ne trouve plus rien » (31/07/2026).

**Le symptôme.** Franck demande une recherche sur « France » — le terme le plus
générique possible — et n'obtient **aucun résultat**.

**Ce que la mesure a montré.** Trois défauts empilés :

```
serper       à court de crédits (400)      → correctement écarté
searchcans   « API key has no balance »    → NON détecté
google CSE   pas de clé
tavily       FONCTIONNE (3 résultats)      → jamais atteint
duckduckgo                                  → jamais atteint
```

1. **SearchCans signale l'épuisement DANS LE CORPS, pas par le code HTTP.**
   Il répond `200 OK` avec `{"code": -2011, "msg": "API key has no balance"}`.
   `raise_for_status()` passe, le parseur ne trouve ni `organic` ni
   `knowledgeGraph`, et rend une **liste vide**. La détection de quota ne vit
   que dans le `except`, jamais atteint faute d'exception.

2. **La chaîne lit une liste vide comme un succès.** `if results is not None:
   return results` — `[]` n'est pas `None`. La cascade s'arrête sur le premier
   fournisseur muet et n'essaie jamais les suivants.

3. **`_QUOTA_MARKERS` ne connaît pas « no balance ».** Même en faisant remonter
   le message, il ne serait pas reconnu comme un épuisement.

Le premier défaut rend SearchCans muet ; le deuxième transforme ce mutisme en
panne totale ; le troisième empêche le disjoncteur de l'écarter ensuite.

⚠️ **La leçon générale, et c'est elle qu'on épingle** : dans une cascade de
replis, « zéro résultat » n'est pas une réponse — c'est un motif pour essayer
le suivant. Un fournisseur qui répond poliment `[]` est plus dangereux qu'un
fournisseur qui plante.

Run with:  cd backend && python -m pytest tests/test_search_chain_never_goes_mute.py -v
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. SearchCans doit reconnaître un épuisement annoncé en HTTP 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_searchcans_no_balance_returns_none_not_empty(monkeypatch) -> None:
    """Un corps « no balance » rend None — pour que la chaîne continue."""
    from app.agent.tools import search_tool as st

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"code": -2011, "data": None,
                    "msg": "API key has no balance", "requestId": None}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def post(self, *_a, **_kw) -> "_Resp":
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
    st.reset_quota_state()

    got = await st._search_searchcans("France", 3, "cle-bidon")

    assert got is None, (
        "SearchCans rend une liste vide au lieu de None : la chaîne la lira "
        "comme un succès et n'essaiera jamais Tavily"
    )
    assert st.is_quota_exhausted("searchcans"), (
        "le disjoncteur n'a pas retenu l'épuisement — chaque recherche repaiera "
        "un aller-retour vers un service qu'on sait à sec"
    )


def test_quota_markers_know_no_balance() -> None:
    """Le vocabulaire d'épuisement couvre la formulation de SearchCans."""
    from app.agent.tools.search_tool import is_quota_error

    assert is_quota_error("API key has no balance")


# ---------------------------------------------------------------------------
# 2. LE PIN QUI COMPTE — une liste vide n'arrête pas la cascade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_empty_provider_does_not_silence_the_chain(monkeypatch) -> None:
    """Un fournisseur qui rend [] passe la main, il ne clôt pas la recherche.

    C'est le pin général : il ne dépend d'aucun fournisseur en particulier et
    resterait rouge si on « corrigeait » seulement SearchCans.

    ⚠️ Les faux sont alignés EXPLICITEMENT sur les vraies signatures — un stub
    à ``**kwargs`` masquerait une signature incompatible (piège vu cinq fois
    sur ce projet).
    """
    from app.agent.tools import search_tool as st

    st.reset_quota_state()
    attendu = [{"title": "France", "url": "https://fr.wikipedia.org",
                "content": "pays d'Europe"}]

    async def _serper_vide(query: str, count: int, api_key: str):
        return []                      # ← poliment vide, pas une erreur

    async def _searchcans_vide(query: str, count: int, api_key: str):
        return []

    async def _cse_vide(query: str, count: int, gse_key: str, gse_cx: str):
        return []

    async def _tavily_ok(query: str, count: int, api_key: str):
        return attendu

    async def _ddgs_jamais(query: str, count: int):
        raise AssertionError("la chaîne ne devait pas descendre jusqu'à DDG")

    monkeypatch.setattr(st, "_search_serper", _serper_vide)
    monkeypatch.setattr(st, "_search_searchcans", _searchcans_vide)
    monkeypatch.setattr(st, "_search_google_cse", _cse_vide)
    monkeypatch.setattr(st, "_search_tavily", _tavily_ok)
    monkeypatch.setattr(st, "_search_ddgs", _ddgs_jamais)

    class _S:
        serper_api_key = "k"
        searchcans_api_key = "k"
        google_search_api_key = "k"
        google_search_cx = "cx"
        tavily_api_key = "k"

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    results, source = await st._dispatch_search("France", 3)

    assert results == attendu, (
        f"la chaîne s'est arrêtée sur un fournisseur vide (source={source!r}) "
        f"alors que Tavily avait la réponse"
    )
    assert "tavily" in source.lower()


@pytest.mark.asyncio
async def test_a_genuinely_empty_web_still_ends_the_chain(monkeypatch) -> None:
    """Si TOUS rendent vide, on rend vide — sans boucler ni lever.

    Le pendant du test précédent : « continuer sur vide » ne doit pas devenir
    « ne jamais s'arrêter ».
    """
    from app.agent.tools import search_tool as st

    st.reset_quota_state()

    async def _vide3(query: str, count: int, api_key: str):
        return []

    async def _vide_cse(query: str, count: int, gse_key: str, gse_cx: str):
        return []

    async def _vide_ddgs(query: str, count: int):
        return []

    monkeypatch.setattr(st, "_search_serper", _vide3)
    monkeypatch.setattr(st, "_search_searchcans", _vide3)
    monkeypatch.setattr(st, "_search_google_cse", _vide_cse)
    monkeypatch.setattr(st, "_search_tavily", _vide3)
    monkeypatch.setattr(st, "_search_ddgs", _vide_ddgs)

    class _S:
        serper_api_key = "k"
        searchcans_api_key = "k"
        google_search_api_key = "k"
        google_search_cx = "cx"
        tavily_api_key = "k"

    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _S())

    results, source = await st._dispatch_search("zzzz-terme-introuvable", 3)

    assert results == []
    assert source, "la source doit rester nommée même sans résultat"
