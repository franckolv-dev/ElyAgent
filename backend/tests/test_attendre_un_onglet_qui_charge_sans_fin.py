# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_attendre_un_onglet_qui_charge_sans_fin.py
# @brief      Un onglet qui n'atteint jamais « complete » mais qui répond
#             n'est pas une erreur ; et la passerelle attend ce qu'on lui
#             demande.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « test 1 » du 03/09/2026, trois sociétés, zéro contact.

Item 1 : LinkedIn répond « Aucun résultat » (la requête de la spec, sept
``OR``, est refusée par LinkedIn — vérifié dans la session de Franck : le
seul nom de la société rend dix profils). Items 2 et 3 : la mission n'a
même pas LU la page :

    browser_tab_wait_loaded(tab_id=…, timeout_s=30)
    → Erreur : timeout after 15.0s.
    EDGE_CASE error … Le chargement de la page LinkedIn a expiré

Deux défauts mécaniques, tous deux ici :

1. La passerelle vers l'extension coupe à ``_DEFAULT_TIMEOUT_S`` (15 s) quel
   que soit le ``timeout_s`` passé à l'outil : l'extension attendait encore
   ses 30 s que le backend avait déjà rendu « timeout ».
2. Une page qui charge en continu (LinkedIn, Gmail) n'atteint parfois jamais
   ``status=complete``. L'onglet RÉPOND pourtant — à l'item 1, le sélecteur
   ``main`` a été trouvé « en 0 ms » juste après le même délai. Rendre
   « Erreur : timeout » fait abandonner l'item ; dire « l'onglet répond, lis-le »
   fait avancer.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.agent.tools import browser_extension_tool as bx


# ── La passerelle attend au moins ce que l'outil a demandé ───────────────────

class _ConnexionMuette:
    """Une extension connectée qui ne répond jamais."""

    def __init__(self) -> None:
        self.pending: dict = {}
        self.websocket = SimpleNamespace(send_text=self._envoi)

    async def _envoi(self, _texte: str) -> None:
        return None


@pytest.mark.asyncio
async def test_la_passerelle_attend_le_delai_demande_par_l_outil(monkeypatch):
    monkeypatch.setattr(bx, "_DEFAULT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(bx.bext_registry, "get", lambda key: _ConnexionMuette())

    debut = time.monotonic()
    res = await bx._send_and_wait("u", "wait_loaded", {"tab_id": 1}, timeout_s=0.3)
    duree = time.monotonic() - debut

    assert res["ok"] is False and res["error"].startswith("timeout")
    assert duree >= 0.3, f"la passerelle a coupé à {duree:.2f}s alors que l'outil demandait 0,3 s"


@pytest.mark.asyncio
async def test_sans_delai_demande_la_passerelle_garde_le_sien(monkeypatch):
    monkeypatch.setattr(bx, "_DEFAULT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(bx.bext_registry, "get", lambda key: _ConnexionMuette())

    debut = time.monotonic()
    res = await bx._send_and_wait("u", "ping", {})
    assert res["ok"] is False
    assert time.monotonic() - debut < 0.3


# ── Un onglet qui répond n'est pas une erreur ────────────────────────────────

def _faux_pont(reponses: dict, recus: list):
    async def _envoi(user_id, command_type, payload, **kw):
        recus.append((command_type, payload, kw))
        return reponses[command_type]
    return _envoi


@pytest.mark.asyncio
async def test_un_delai_depasse_sur_un_onglet_qui_repond_invite_a_lire(monkeypatch):
    recus: list = []
    monkeypatch.setattr(bx, "_send_and_wait", _faux_pont({
        "wait_loaded": {"ok": False, "error": "timeout after 30s"},
        "get_url": {"ok": True, "tab_id": 42, "url": "https://www.linkedin.com/search/results/people/?keywords=Samedia",
                    "title": "Recherche | LinkedIn"},
    }, recus))

    rendu = await bx.browser_tab_wait_loaded.ainvoke({"tab_id": 42, "timeout_s": 30, "user_id": "u"})

    assert not rendu.lstrip().lower().startswith("erreur")
    assert "Recherche | LinkedIn" in rendu
    assert "browser_tab_read_text" in rendu
    assert "browser_tab_wait_for_selector" in rendu
    # Le délai de l'outil est bien transmis à la passerelle, avec une marge.
    attente = next(kw for cmd, _p, kw in recus if cmd == "wait_loaded")
    assert attente.get("timeout_s", 0) >= 30


@pytest.mark.asyncio
async def test_un_delai_depasse_sur_un_onglet_injoignable_reste_une_erreur(monkeypatch):
    recus: list = []
    monkeypatch.setattr(bx, "_send_and_wait", _faux_pont({
        "wait_loaded": {"ok": False, "error": "timeout after 30s"},
        "get_url": {"ok": False, "error": "tab_not_found"},
    }, recus))

    rendu = await bx.browser_tab_wait_loaded.ainvoke({"tab_id": 42, "timeout_s": 30, "user_id": "u"})

    assert rendu.startswith("Erreur")


@pytest.mark.asyncio
async def test_une_autre_erreur_de_chargement_reste_une_erreur(monkeypatch):
    recus: list = []
    monkeypatch.setattr(bx, "_send_and_wait", _faux_pont({
        "wait_loaded": {"ok": False, "error": "tab_not_found"},
    }, recus))

    rendu = await bx.browser_tab_wait_loaded.ainvoke({"tab_id": 42, "user_id": "u"})

    assert rendu.startswith("Erreur")
    assert all(cmd == "wait_loaded" for cmd, _p, _kw in recus)


@pytest.mark.asyncio
async def test_l_attente_d_un_selecteur_transmet_aussi_son_delai(monkeypatch):
    recus: list = []
    monkeypatch.setattr(bx, "_send_and_wait", _faux_pont({
        "wait_for": {"ok": True, "tab_id": 42, "selector": "main", "waited_ms": 12},
    }, recus))

    await bx.browser_tab_wait_for_selector.ainvoke(
        {"tab_id": 42, "selector": "main", "timeout_s": 40, "user_id": "u"},
    )

    attente = next(kw for cmd, _p, kw in recus if cmd == "wait_for")
    assert attente.get("timeout_s", 0) >= 40
