# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_search_degraded_and_news_tools.py
# @brief      Ely ne présente plus une recherche dégradée comme un résultat
#             normal, et ses outils d'actualité deviennent atteignables.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la recherche dégradée et des outils d'actualité.

**L'incident du 26/07.** Franck demande les news IA des dernières 48 h — une
demande qu'Ely honorait sans problème auparavant. Elle répond qu'elle n'y
arrive pas : *« les moteurs ne me renvoient quasiment aucun résultat
pertinent […] soit des pages d'accueil génériques, soit du contenu
hors-sujet »*, puis *« je n'ai aucun outil dédié à l'actualité récente »*.

**Trois causes distinctes, mesurées :**

1. **Le compte Serper n'a plus de crédits.** Réponse réelle de l'API :
   ``{"message":"Not enough credits","statusCode":400}``. La chaîne retombe
   silencieusement sur DuckDuckGo, qui rend des pages d'accueil
   (news.google.com, franceinfo, openai.com) au lieu d'articles.
2. **``news_get_headlines`` et ``web_search_news`` existent mais ne sont pas
   dans le profil ``default``** — Ely disait donc VRAI : elle ne les voit
   pas. Le catalogue a la capacité, l'agent n'y a pas accès.
3. **L'échec part en ``logger.warning``** et rien ne remonte au modèle. Ely a
   donc présenté des pages d'accueil DuckDuckGo comme si c'étaient des
   résultats de recherche, puis en a déduit que « les moteurs » étaient en
   cause. C'est une façade : le résultat a l'air normal, il ne l'est pas.

Ce lot traite 2 et 3. Le 1 appartient à Franck (recharger, ou changer de
fournisseur) — mais après ce lot, Ely le lui DIRA au lieu de le deviner.

Run with:  cd backend && python -m pytest tests/test_search_degraded_and_news_tools.py -v
"""
from __future__ import annotations

import pytest


# ------------------------------------------- les outils d'actualité existent

@pytest.mark.parametrize("tool_name", ["news_get_headlines", "web_search_news"])
def test_the_news_tools_are_reachable_by_the_agent(tool_name):
    """Ils étaient dans le catalogue mais absents du profil : Ely ne pouvait
    pas les appeler, et affirmait honnêtement n'avoir aucun outil
    d'actualité."""
    from app.agent.toolset_profiles import _DEFAULT_TOOLS

    assert tool_name in _DEFAULT_TOOLS, (
        f"{tool_name} existe dans le catalogue mais reste invisible pour l'agent"
    )


def test_the_news_tools_really_exist_in_the_catalog():
    """Garde-fou : binder un nom qui n'existe pas créerait un trou silencieux."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    names = {t.name for t in get_skill_registry().all_tools}

    assert "news_get_headlines" in names
    assert "web_search_news" in names


# ------------------------------ une recherche dégradée le DIT au modèle

@pytest.mark.asyncio
async def test_a_credit_exhausted_provider_is_reported_not_hidden(monkeypatch):
    """LE test du lot. Quand le fournisseur principal tombe, le repli ne doit
    pas se faire passer pour un résultat normal — sinon le modèle conclut que
    « les moteurs ne trouvent rien » alors que le compte est à sec."""
    import app.agent.tools.search_tool as st

    async def _serper_ko(query, count, api_key):
        return None  # échec (crédits épuisés, clé invalide, réseau…)

    async def _ddg_ok(query, count):
        return [{"title": "Google Actualités", "url": "https://news.google.com",
                 "content": "page d'accueil générique"}]

    monkeypatch.setattr(st, "_search_serper", _serper_ko)
    monkeypatch.setattr(st, "_search_ddgs", _ddg_ok)
    monkeypatch.setattr(st, "_search_searchcans", lambda *a, **k: None, raising=False)

    class _S:
        serper_api_key = "une-cle"
        google_search_api_key = ""
        google_search_cx = ""
        tavily_api_key = ""

    # `_dispatch_search` importe get_settings LOCALEMENT : patcher l attribut
    # du module n a aucun effet. Ce test passait donc pour une raison
    # differente de celle qu il annonçait (la cle Serper est absente en test,
    # donc la branche n etait meme pas prise). On patche la source.
    import app.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: _S())
    st.reset_quota_state()

    results, provider = await st._dispatch_search("actualités IA", 5)

    assert "DuckDuckGo" in provider
    assert st.is_degraded(provider), (
        "un repli après échec du fournisseur principal doit être signalé "
        "comme dégradé"
    )


@pytest.mark.asyncio
async def test_the_degraded_notice_reaches_the_model(monkeypatch):
    """Le modèle doit LIRE que la recherche est dégradée, pas le deviner."""
    import app.agent.tools.search_tool as st

    async def _fake(query, count):
        return ([{"title": "Accueil", "url": "https://x.fr", "content": "générique"}],
                "DuckDuckGo (repli — Serper indisponible)")

    monkeypatch.setattr(st, "_dispatch_search", _fake)

    out = await st.web_search.ainvoke({"query": "actualités IA"})

    low = str(out).lower()
    assert "dégradé" in low or "repli" in low, (
        f"rien n'avertit le modèle que la recherche est dégradée : {out[:200]}"
    )


@pytest.mark.asyncio
async def test_a_healthy_search_carries_no_warning(monkeypatch):
    """Pas de bruit quand tout va bien : l'avertissement doit rester un
    signal, pas un décor permanent."""
    import app.agent.tools.search_tool as st

    async def _fake(query, count):
        return ([{"title": "Un article", "url": "https://x.fr", "content": "du contenu"}],
                "Serper/Google")

    monkeypatch.setattr(st, "_dispatch_search", _fake)

    out = await st.web_search.ainvoke({"query": "actualités IA"})

    assert "dégradé" not in str(out).lower()


def test_the_primary_provider_is_not_considered_degraded():
    from app.agent.tools.search_tool import is_degraded

    assert is_degraded("Serper/Google") is False
    assert is_degraded("Google CSE") is False
    assert is_degraded("Tavily") is False
    assert is_degraded("DuckDuckGo") is True
