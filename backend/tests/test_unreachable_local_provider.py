# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_unreachable_local_provider.py
# @brief      Un serveur local éteint ne doit pas capturer la chaîne de repli.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du repli quand un fournisseur LOCAL ne répond pas.

**Mesuré le 27/07 sur un clone vierge**, en suivant le Quick start du README à
la lettre : clé Gemini renseignée, ``ACTIVE_LLM_PROVIDER=gemini``.

``DEFAULT_TIER_CONFIG`` fait pointer ``simple`` et ``maintenance`` sur
``["ollama"]``. Or ``_make_llm_for_provider("ollama")`` renvoie **toujours** un
objet : aucune clé n'est requise, et rien ne vérifie qu'un serveur écoute. La
boucle de repli s'arrête au premier objet non-nul — donc sur Ollama, installé
ou non.

Conséquence pour un nouveau venu : ses messages classés « simple » partent vers
un serveur inexistant et échouent, tandis que ses messages complexes
fonctionnent. Un agent qui rate une question sur deux, dès la première minute.

**Et le correctif indiqué par le README ne corrige pas.**
``ACTIVE_LLM_PROVIDER`` n'alimente que ``get_llm()``, le repli ultime — jamais
atteint, puisque la chaîne a « réussi » à produire un objet Ollama mort.

C'est mot pour mot le défaut ``gpt-5.5`` de la veille : **le réglage qu'on
demande à l'utilisateur de changer n'atteint pas ce qui décide.**

**Le correctif retenu.** Un fournisseur local injoignable est traité comme un
fournisseur sans clé : il rend ``None``, la chaîne continue, et le repli final
utilise le fournisseur réellement configuré. Aucune table à réécrire, aucune
configuration mutée dans le dos de l'utilisateur.

La sonde est un simple TCP, avec un délai court et un cache : le résolveur est
appelé à chaque tour, il ne peut pas payer un aller-retour réseau à chaque
fois. Le cache expire, pour qu'un Ollama démarré après coup soit vu.

Run with:  cd backend && python -m pytest tests/test_unreachable_local_provider.py -v
"""
from __future__ import annotations

import pytest


def test_a_reachable_server_is_used():
    """Ne pas casser l'installation de Franck : son LM Studio répond, il doit
    continuer d'être choisi."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    assert lp.is_local_server_reachable("http://127.0.0.1:0", _probe=lambda h, p: True)


def test_an_unreachable_server_is_reported_as_such():
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    assert not lp.is_local_server_reachable("http://127.0.0.1:0", _probe=lambda h, p: False)


def test_the_probe_result_is_cached():
    """Le résolveur est appelé à chaque tour : une sonde réseau par appel
    coûterait plus cher que le problème qu'elle résout."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    calls = []

    def _probe(host, port):
        calls.append((host, port))
        return False

    for _ in range(5):
        lp.is_local_server_reachable("http://localhost:11434", _probe=_probe)

    assert len(calls) == 1, f"{len(calls)} sondes pour 5 appels"


def test_a_malformed_url_never_raises():
    """Cette valeur vient d'un `.env` : elle arrivera un jour vide ou tordue."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    for bad in ("", "pas-une-url", "http://", None):
        assert lp.is_local_server_reachable(bad, _probe=lambda h, p: True) in (True, False)


# ------------------------------------------- l'effet sur la chaîne de repli

def test_an_unreachable_ollama_yields_no_llm(monkeypatch):
    """LE test du lot : rendre None laisse la chaîne continuer."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    monkeypatch.setattr(lp, "is_local_server_reachable", lambda *a, **k: False)

    from app.config import get_settings

    llm = lp._make_llm_for_provider("ollama", get_settings())

    assert llm is None, (
        "un Ollama éteint capture encore la chaîne : les messages « simple » "
        "échoueront au lieu de retomber sur le fournisseur configuré"
    )


def test_a_reachable_ollama_still_works(monkeypatch):
    """Le correctif ne doit pas priver de local ceux qui en ont un."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    monkeypatch.setattr(lp, "is_local_server_reachable", lambda *a, **k: True)

    from app.config import get_settings

    assert lp._make_llm_for_provider("ollama", get_settings()) is not None


def test_lm_studio_gets_the_same_treatment(monkeypatch):
    """LM Studio ne demande pas de clé non plus : même piège, même correctif."""
    import app.services.llm_provider as lp

    lp.reset_local_probe_cache()
    monkeypatch.setattr(lp, "is_local_server_reachable", lambda *a, **k: False)

    from app.config import get_settings

    assert lp._make_llm_for_provider("lm_studio", get_settings()) is None
