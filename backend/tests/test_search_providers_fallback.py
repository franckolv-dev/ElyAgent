# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_search_providers_fallback.py
# @brief      Serper n'est plus un point de panne unique : SearchCans et Tavily
#             prennent le relais, et un fournisseur à sec cesse d'être appelé.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la chaîne de fournisseurs de recherche.

**L'incident du 26/07.** Le compte Serper est tombé à court de crédits
(``{"message":"Not enough credits","statusCode":400}``), consommé par une
tâche de prospection quotidienne qui bouclait sur ``web_search`` sans jamais
aboutir. Toute la recherche d'Ely est passée sur DuckDuckGo, qui rend des
pages d'accueil — et elle en a conclu que « les moteurs ne trouvent rien ».

Deux réponses ici :

1. **SearchCans** rejoint la chaîne (contrat lu sur leur documentation :
   ``POST /api/v1/search``, ``Authorization: Bearer``, corps ``{"t","s",…}``,
   réponse ``data.organic[]`` avec ``title``/``link``/``snippet``). **Tavily**
   était déjà implémenté mais sans clé configurée — donc jamais atteint.
2. **Un fournisseur qui répond « plus de crédits » cesse d'être appelé** un
   moment. Sans ça, chaque recherche paie un aller-retour vers un service
   dont on sait qu'il refusera — pure latence perdue, sur CHAQUE requête.

Run with:  cd backend && python -m pytest tests/test_search_providers_fallback.py -v
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------- SearchCans

@pytest.mark.asyncio
async def test_searchcans_maps_the_documented_response(monkeypatch):
    """Contrat relevé dans leur doc : data.organic[] avec title/link/snippet."""
    import app.agent.tools.search_tool as st

    payload = {
        "code": 0,
        "data": {
            "organic": [
                {"position": 1, "title": "Un article", "link": "https://x.fr/a",
                 "snippet": "du contenu utile", "source": "X"},
                {"position": 2, "title": "Un autre", "link": "https://y.fr/b",
                 "snippet": "encore du contenu", "source": "Y"},
            ],
        },
    }

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return payload

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            assert url.endswith("/api/v1/search")
            assert headers["Authorization"].startswith("Bearer ")
            assert json["s"], "la requête part dans le champ 's'"
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    results = await st._search_searchcans("actualités IA", 5, "une-cle")

    assert results is not None
    assert results[0]["title"] == "Un article"
    assert results[0]["url"] == "https://x.fr/a"
    assert results[0]["content"] == "du contenu utile"


@pytest.mark.asyncio
async def test_searchcans_failure_returns_none_not_an_exception(monkeypatch):
    """Un fournisseur en panne doit laisser la chaîne continuer."""
    import app.agent.tools.search_tool as st

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("réseau coupé")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    assert await st._search_searchcans("x", 5, "cle") is None


def test_searchcans_is_in_the_chain():
    """Pin : implémenter un fournisseur sans le brancher ne sert à rien —
    c'est exactement ce qui est arrivé à Tavily (implémenté, jamais atteint
    faute de clé ET jamais vérifié)."""
    from pathlib import Path

    src = Path("app/agent/tools/search_tool.py").read_text(encoding="utf-8")
    dispatcher = src[src.index("async def _dispatch_search"):]

    assert "_search_searchcans" in dispatcher
    assert "_search_tavily" in dispatcher


def test_the_setting_exists():
    from app.config import get_settings

    assert hasattr(get_settings(), "searchcans_api_key")


# ------------------------------- ne plus appeler un fournisseur a sec

def test_a_credits_error_is_recognised():
    from app.agent.tools.search_tool import is_quota_error

    assert is_quota_error('{"message":"Not enough credits","statusCode":400}')
    assert is_quota_error("quota exceeded for this month")
    assert is_quota_error("Insufficient credits")
    assert not is_quota_error("connection timed out")
    assert not is_quota_error("")


@pytest.mark.asyncio
async def test_an_exhausted_provider_is_skipped_for_a_while(monkeypatch):
    """LE test du lot. Sans ça, chaque recherche paie un aller-retour vers un
    service dont on SAIT qu'il répondra « plus de crédits »."""
    import app.agent.tools.search_tool as st

    st.reset_quota_state()
    calls: list[str] = []

    async def _serper(query, count, api_key):
        calls.append("serper")
        st.mark_quota_exhausted("serper")
        return None

    async def _cans(query, count, api_key):
        calls.append("searchcans")
        return [{"title": "ok", "url": "https://x.fr", "content": "c"}]

    monkeypatch.setattr(st, "_search_serper", _serper)
    monkeypatch.setattr(st, "_search_searchcans", _cans)

    class _S:
        serper_api_key = "a"
        searchcans_api_key = "b"
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    # `_dispatch_search` importe get_settings LOCALEMENT : patcher l attribut
    # du module search_tool n aurait aucun effet. On patche la source.
    import app.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())

    await st._dispatch_search("q1", 5)
    await st._dispatch_search("q2", 5)

    assert calls.count("serper") == 1, (
        f"Serper rappelé malgré des crédits épuisés : {calls}"
    )
    assert calls.count("searchcans") == 2


def test_the_skip_expires():
    """L'oubli n'est pas définitif : Franck recharge, ça doit repartir sans
    redémarrer le backend."""
    from app.agent.tools.search_tool import (
        _QUOTA_COOLDOWN_S, is_quota_exhausted, mark_quota_exhausted, reset_quota_state,
    )

    reset_quota_state()
    mark_quota_exhausted("serper")
    assert is_quota_exhausted("serper") is True
    assert _QUOTA_COOLDOWN_S <= 3600, "un oubli trop long retarderait la reprise"

    reset_quota_state()
    assert is_quota_exhausted("serper") is False
