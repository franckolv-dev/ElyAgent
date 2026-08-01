# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_service_probe.py
# @brief      La sonde exerce RÉELLEMENT chaque tête de chaîne — un service
#             constructible qui ne répond pas doit se voir au démarrage.
# @license    Elastic License 2.0
# =============================================================================
"""Pins de la sonde de têtes de chaîne.

**Le trou qu'elle bouche.** `config_reality` vérifie qu'un service est
**constructible** : le modèle est connu des tables de fenêtre et de tarif, il
est déclaré par une instance, ses outils existent. Il ne vérifie **jamais qu'il
répond**.

Deux pannes en une journée sont passées par ce trou :

```
30/07  kimi-k3      se construit parfaitement, rend 400 au premier appel
                    → tête du tier C, jamais servi depuis le 6 mai,
                      17 bascules silencieuses en 3 jours
31/07  searchcans   répond 200 OK avec « API key has no balance »
                    → toute la chaîne de recherche muette
```

Dans les deux cas le contrôle au démarrage était **vert**.

**Ce que la sonde fait.** Un appel réel par tête de chaîne — LLM *et*
recherche — et un `Finding` pour chacune qui ne répond pas.

**Ce qu'elle ne fait PAS, volontairement** :

- elle ne sonde pas les 11 instances mais les **4 têtes distinctes**. Une tête
  morte est une panne immédiate ; un repli mort dégrade proprement, et sonder
  Kimi (25 s) ou DeepSeek pro (payant) pour surveiller une position de secours
  coûterait plus que ça ne rapporte ;
- elle **ne corrige rien** : elle constate. Échouer au démarrage ne veut pas
  dire échouer toujours, et réordonner une chaîne serait une décision de
  politique, pas un diagnostic ;
- elle **ne bloque pas le démarrage**.

⚠️ Module **séparé** de `config_reality` à dessein : greffer un contrôle sur
une fonction partagée avait cassé quatre pins existants en #296, dont le
contrat est « liste vide = rien à signaler ».

Run with:  cd backend && python -m pytest tests/test_service_probe.py -v
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. Un modèle qui se construit mais ne répond pas est SIGNALÉ
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_model_that_builds_but_never_answers_is_reported(monkeypatch) -> None:
    """Le cas kimi-k3 : constructible, 400 au premier appel."""
    from app.services import service_probe as sp

    class _LlmMuet:
        model_name = "modele-qui-refuse"

        async def ainvoke(self, _messages):
            raise RuntimeError("Error code: 400 - invalid temperature")

    monkeypatch.setattr(sp, "_chain_heads", lambda: {"complex": ("id-x", "modele-qui-refuse")})
    monkeypatch.setattr(sp, "_build", lambda _pid: _LlmMuet())
    monkeypatch.setattr(sp, "_search_providers", lambda: {})

    findings = await sp.probe_services()

    assert findings, "un modèle qui refuse tout appel doit produire un constat"
    f = findings[0]
    assert "modele-qui-refuse" in f.subject
    assert "400" in f.detail or "invalid" in f.detail.lower(), (
        "le constat doit porter la CAUSE, pas seulement « ne répond pas » — "
        "sinon il se noie comme l'avertissement « Unknown model » de juillet"
    )


@pytest.mark.asyncio
async def test_a_model_that_answers_produces_no_finding(monkeypatch) -> None:
    """Contrat partagé avec config_reality : liste vide = rien à signaler."""
    from app.services import service_probe as sp

    class _LlmOk:
        model_name = "modele-sain"

        async def ainvoke(self, _messages):
            class _R:
                content = "OK"
            return _R()

    monkeypatch.setattr(sp, "_chain_heads", lambda: {"complex": ("id-x", "modele-sain")})
    monkeypatch.setattr(sp, "_build", lambda _pid: _LlmOk())
    monkeypatch.setattr(sp, "_search_providers", lambda: {})

    assert await sp.probe_services() == []


# ---------------------------------------------------------------------------
# 2. La recherche aussi — le cas SearchCans
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_search_provider_returning_nothing_is_reported(monkeypatch) -> None:
    """Le cas searchcans : répond 200 et ne rend rien.

    ⚠️ C'est la moitié que `config_reality` ne pouvait pas voir : il n'a aucune
    notion de fournisseur de recherche.
    """
    from app.services import service_probe as sp

    async def _muet(query: str, count: int):
        return []

    monkeypatch.setattr(sp, "_chain_heads", lambda: {})
    monkeypatch.setattr(sp, "_search_providers", lambda: {"searchcans": _muet})

    findings = await sp.probe_services()

    assert findings, "un fournisseur de recherche muet doit produire un constat"
    assert "searchcans" in findings[0].subject


@pytest.mark.asyncio
async def test_a_working_search_provider_is_silent(monkeypatch) -> None:
    from app.services import service_probe as sp

    async def _ok(query: str, count: int):
        return [{"title": "France", "url": "https://exemple.fr", "content": "…"}]

    monkeypatch.setattr(sp, "_chain_heads", lambda: {})
    monkeypatch.setattr(sp, "_search_providers", lambda: {"tavily": _ok})

    assert await sp.probe_services() == []


# ---------------------------------------------------------------------------
# 3. LE PIN QUI COMPTE — la sonde ne doit jamais casser le démarrage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_probe_never_raises(monkeypatch) -> None:
    """Une sonde qui tue le boot serait pire que le trou qu'elle bouche.

    Elle tourne au démarrage sur des services réseau : timeouts, DNS, panne
    de fournisseur. Tout ça doit devenir un constat, jamais une exception.
    """
    from app.services import service_probe as sp

    def _explose():
        raise RuntimeError("la configuration elle-même est cassée")

    monkeypatch.setattr(sp, "_chain_heads", _explose)
    monkeypatch.setattr(sp, "_search_providers", _explose)

    findings = await sp.probe_services()          # ne doit pas lever
    assert isinstance(findings, list)


@pytest.mark.asyncio
async def test_the_probe_does_not_reorder_anything(monkeypatch) -> None:
    """Elle constate, elle ne corrige pas.

    Réordonner une chaîne ou écarter un fournisseur est une décision de
    politique. Une sonde qui agit sur un échec transitoire au démarrage
    déciderait pour Franck sur la foi d'un seul appel.
    """
    from app.services import service_probe as sp
    from app.agent.tools import search_tool as st

    async def _muet(query: str, count: int):
        return []

    st.reset_quota_state()
    monkeypatch.setattr(sp, "_chain_heads", lambda: {})
    monkeypatch.setattr(sp, "_search_providers", lambda: {"searchcans": _muet})

    await sp.probe_services()

    assert not st.is_quota_exhausted("searchcans"), (
        "la sonde a écarté un fournisseur — elle doit constater, pas décider"
    )


# ---------------------------------------------------------------------------
# 4. Le constat doit dire LEQUEL des deux échecs s'est produit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failing_provider_is_not_described_as_answering(monkeypatch) -> None:
    """`None` = le fournisseur a ÉCHOUÉ ; `[]` = il a répondu sans résultat.

    ⚠️ Constaté au premier démarrage réel (31/07) : la sonde annonçait
    « répond mais ne rend AUCUN résultat » pour **Serper**, qui avait en fait
    rendu un `400`. `_search_serper` attrape l'exception et rend `None`,
    `_search_searchcans` rend `[]` — la distinction existe dans le code et la
    sonde la jetait.

    Un diagnostic qui se trompe sur la nature de la panne envoie chercher au
    mauvais endroit : « pas de résultat » fait penser à un quota, « a échoué »
    fait lire l'erreur.
    """
    from app.services import service_probe as sp

    async def _echoue(query: str, count: int):
        return None                    # le fournisseur signale son échec

    async def _vide(query: str, count: int):
        return []                      # il répond, sans résultat

    monkeypatch.setattr(sp, "_chain_heads", lambda: {})
    monkeypatch.setattr(sp, "_search_providers",
                        lambda: {"qui-echoue": _echoue, "qui-est-vide": _vide})

    par_sujet = {f.subject: f.detail for f in await sp.probe_services()}

    assert set(par_sujet) == {"qui-echoue", "qui-est-vide"}
    assert "échoué" in par_sujet["qui-echoue"], (
        "un fournisseur qui rend None a ÉCHOUÉ — ne pas dire qu'il répond"
    )
    assert "répond" not in par_sujet["qui-echoue"]
    assert "aucun résultat" in par_sujet["qui-est-vide"].lower()


# ---------------------------------------------------------------------------
# 5. Chaque sonde doit partir avec SA clé
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_provider_probe_carries_its_own_key(monkeypatch) -> None:
    """Une fermeture capture la VARIABLE, pas sa valeur.

    ⚠️ Défaut réel, trouvé en production le 01/08 : `_search_providers`
    réutilisait le même nom `cle` pour Serper, SearchCans et Tavily. Les trois
    fermetures voyaient donc la **dernière** affectation — la clé Tavily. La
    sonde annonçait « SearchCans : Invalid API key » alors que la clé de Franck
    était bonne et que le service répondait (12/12 en appel direct).

    👉 Une sonde qui se trompe de clé accuse un service sain. C'est exactement
    la panne qu'elle est censée empêcher, retournée contre elle.

    Ce test exerce le VRAI `_search_providers()` — tous les autres le
    remplacent par un stub, c'est pour ça que le défaut a survécu à sa propre
    suite de tests.
    """
    from app.agent.tools import search_tool as st
    from app.services import service_probe as sp

    cles = {
        "searxng_url": "http://searxng:8080",
        "exa_api_key": "cle-exa",
        "serper_api_key": "cle-serper",
        "searchcans_api_key": "cle-searchcans",
        "tavily_api_key": "cle-tavily",
    }

    class _Reglages:
        def __init__(self) -> None:
            self.__dict__.update(cles)

    monkeypatch.setattr("app.config.get_settings", lambda: _Reglages())

    recues: dict[str, str] = {}

    def _mouchard(nom: str):
        async def _stub(query: str, count: int, secret: str):
            recues[nom] = secret
            return [{"title": "t", "url": "u", "content": "c"}]
        return _stub

    monkeypatch.setattr(st, "_search_searxng", _mouchard("searxng"))
    monkeypatch.setattr(st, "_search_exa", _mouchard("exa"))
    monkeypatch.setattr(st, "_search_serper", _mouchard("serper"))
    monkeypatch.setattr(st, "_search_searchcans", _mouchard("searchcans"))
    monkeypatch.setattr(st, "_search_tavily", _mouchard("tavily"))

    sondes = sp._search_providers()
    assert set(sondes) == {"searxng", "exa", "serper", "searchcans", "tavily"}, (
        "les cinq fournisseurs sont déclarés, les cinq doivent être sondés"
    )
    for sonde in sondes.values():
        await sonde("France", 3)

    assert recues == {
        "searxng": cles["searxng_url"],
        "exa": cles["exa_api_key"],
        "serper": cles["serper_api_key"],
        "searchcans": cles["searchcans_api_key"],
        "tavily": cles["tavily_api_key"],
    }, (
        "chaque fournisseur doit recevoir SA clé ; si plusieurs fermetures "
        "partagent un nom de variable, elles reçoivent toutes la dernière"
    )
