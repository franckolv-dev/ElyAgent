# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_browser_returns_are_bounded.py
# @brief      Une page web ne part plus entière dans le contexte du modèle.
# @license    Elastic License 2.0
# =============================================================================
"""Le tour à 1,76 $ et 8 minutes — mesuré le 29/07/2026.

Ce que la base dit
-------------------
    2026-07-28  browser_tab_click      [deepseek-v4-pro]
        entrée  4 037 491 tokens · sortie 4 552 · 1,76 $ · 489 144 ms
    2026-07-28  browser_tab_read_text  [deepseek-v4-pro]
        entrée  3 342 602 tokens · sortie 4 737 · 1,46 $ · 364 823 ms

**Quatre millions de tokens en entrée pour un clic.** Trois appels navigateur
ont coûté 3,25 $ sur les 7,50 $ facturés de la semaine — 43 % — et 8 minutes
d'attente pour un seul tour.

La cause
---------
``browser_tab_read_text`` et ``browser_tab_read_html`` renvoient le contenu de
la page **entier** : ``f"Contenu (…) :\\n{text}"``. La borne « 200 kB »
mentionnée dans la docstring est appliquée par l'extension Chrome, pas ici —
côté backend, rien ne limite.

Et comme la boucle d'outils **renvoie tout le contexte à chaque itération**, un
retour de 200 kB est repayé à chaque tour de boucle. D'où les millions de
tokens : le coût est quadratique, pas linéaire.

Le voisin qui fait déjà bien
------------------------------
``skills/builtin/browser_skill.py`` tronque à **5 000 caractères**, et
``pdf_read`` à 15 000. Seuls les ``browser_tab_*`` de
``agent/tools/browser_extension_tool.py`` ne bornent rien. Ce lot aligne.

Run with:  cd backend && python -m pytest tests/test_browser_returns_are_bounded.py -v
"""
from __future__ import annotations

import pytest


@pytest.fixture
def fake_page(monkeypatch):
    """L'extension renvoie une page énorme — le cas réel."""
    def _install(**payload):
        async def _send(user_id, action, data, **kwargs):
            return {"ok": True, **payload}

        monkeypatch.setattr(
            "app.agent.tools.browser_extension_tool._send_and_wait", _send,
        )
    return _install


# ─────────────────────────────────────────────────────────────────────
# Le texte d'une page
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_huge_page_does_not_enter_the_context_whole(fake_page):
    """LE pin du lot. 200 kB renvoyés à chaque itération de la boucle d'outils,
    c'est le tour à 4 millions de tokens."""
    from app.agent.tools.browser_extension_tool import (
        MAX_PAGE_CHARS, browser_tab_read_text,
    )

    fake_page(text="x" * 200_000, url="https://exemple.fr", title="T")
    out = await browser_tab_read_text.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert len(out) < MAX_PAGE_CHARS * 1.2, f"{len(out)} caractères rendus"


@pytest.mark.asyncio
async def test_the_truncation_is_announced(fake_page):
    """Un contenu coupé en silence ferait conclure au modèle que la page est
    courte — il répondrait avec assurance sur des données amputées."""
    from app.agent.tools.browser_extension_tool import browser_tab_read_text

    fake_page(text="x" * 200_000, url="https://exemple.fr", title="T")
    out = await browser_tab_read_text.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert "tronqué" in out.lower() or "tronque" in out.lower()


@pytest.mark.asyncio
async def test_the_truncation_says_how_to_get_the_rest(fake_page):
    """Sans issue proposée, le modèle réessaie le même appel — et repaie."""
    from app.agent.tools.browser_extension_tool import browser_tab_read_text

    fake_page(text="x" * 200_000, url="https://exemple.fr", title="T")
    out = await browser_tab_read_text.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert "selector" in out.lower() or "sélecteur" in out.lower()


@pytest.mark.asyncio
async def test_the_real_size_is_still_reported(fake_page):
    """Savoir qu'on a lu 3 000 caractères sur 200 000 change la façon dont on
    interprète le contenu."""
    from app.agent.tools.browser_extension_tool import browser_tab_read_text

    fake_page(text="x" * 200_000, url="https://exemple.fr", title="T")
    out = await browser_tab_read_text.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert "200000" in out.replace(" ", "").replace(" ", "")


@pytest.mark.asyncio
async def test_a_normal_page_is_returned_untouched(fake_page):
    """La borne ne doit rien coûter au cas courant : une page ordinaire passe
    entière, sans mention de troncature."""
    from app.agent.tools.browser_extension_tool import browser_tab_read_text

    fake_page(text="Contenu court et utile.", url="https://exemple.fr", title="T")
    out = await browser_tab_read_text.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert "Contenu court et utile." in out
    assert "tronqué" not in out.lower()


# ─────────────────────────────────────────────────────────────────────
# Le HTML — encore plus verbeux que le texte
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_html_is_bounded_too(fake_page):
    """``browser_tab_read_html`` a coûté 1,42 $ en mai et 0,73 $ en juin sur le
    même défaut : le HTML porte les balises en plus du texte."""
    from app.agent.tools.browser_extension_tool import (
        MAX_PAGE_CHARS, browser_tab_read_html,
    )

    fake_page(html="<div>" + "y" * 200_000 + "</div>", url="https://exemple.fr", title="T")
    out = await browser_tab_read_html.ainvoke({"tab_id": 1, "user_id": "u1"})

    assert len(out) < MAX_PAGE_CHARS * 1.2, f"{len(out)} caractères rendus"


# ─────────────────────────────────────────────────────────────────────
# La borne elle-même
# ─────────────────────────────────────────────────────────────────────


def test_the_bound_is_of_the_same_order_as_the_other_readers():
    """``browser_skill`` tronque à 5 000, ``pdf_read`` à 15 000. Une borne d'un
    autre ordre de grandeur ici serait une incohérence, pas un réglage."""
    from app.agent.tools.browser_extension_tool import MAX_PAGE_CHARS

    assert 3_000 <= MAX_PAGE_CHARS <= 20_000
