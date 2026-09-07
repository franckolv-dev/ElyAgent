# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_l_extension_remplit_tous_les_controles.py
# @brief      Menus déroulants, cases à cocher, boutons radio : les outils
#             navigateur les remplissent, le modèle sait qu'ils le peuvent.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Inscription SensCritique du 07/09/2026 : la mission a rempli e-mail, mot de
passe et pseudonyme, puis a cliqué sur l'option « Homme » et sur le libellé
des CGU — sans effet sur un formulaire React. Elle a dû demander à
l'utilisateur de finir à la main. Objectif de Franck : autonomie complète
sur ces formulaires, le paiement seul exclu.

Le script de l'extension est testé côté frontend (jsdom). Ici : ce que le
modèle LIT (docstrings), ce que l'outil lui RAPPORTE (état du contrôle), et
le navigateur serveur (Playwright), qui doit savoir faire la même chose.

Run with:  cd backend && python -m pytest tests/test_l_extension_remplit_tous_les_controles.py -v
"""
from __future__ import annotations

import pytest


# ── L'extension : ce que le modèle lit et ce qu'on lui rapporte ─────────────


def test_les_docstrings_disent_que_select_et_cases_se_remplissent():
    from app.agent.tools.browser_extension_tool import browser_tab_click, browser_tab_fill

    fill = browser_tab_fill.description or ""
    assert "select" in fill.lower() and ("checkbox" in fill.lower() or "case" in fill.lower())
    assert "true" in fill, "la valeur d'une case à cocher doit être documentée"
    click = browser_tab_click.description or ""
    assert "browser_tab_fill" in click, "le clic doit renvoyer vers fill pour les select et les cases"


@pytest.mark.asyncio
async def test_le_resultat_du_fill_rapporte_l_etat_du_controle(monkeypatch):
    import app.agent.tools.browser_extension_tool as ext

    reponses = [
        {"ok": True, "value": "male", "text": "Homme", "control": "select"},
        {"ok": True, "checked": True, "control": "checkbox"},
        {"ok": True, "value_length": 6, "control": "text"},
    ]

    async def _send(_uid, _cmd, _payload, **_kw):
        return reponses.pop(0)

    monkeypatch.setattr(ext, "_send_and_wait", _send)

    a = await ext.browser_tab_fill.ainvoke({"selector": "select", "value": "Homme", "user_id": "u"})
    b = await ext.browser_tab_fill.ainvoke({"selector": "#cgu", "value": "true", "user_id": "u"})
    c = await ext.browser_tab_fill.ainvoke({"selector": "#email", "value": "a@b.fr", "user_id": "u"})

    assert "male" in a and "Homme" in a
    assert "coch" in b.lower()
    assert "6 caractères" in c


@pytest.mark.asyncio
async def test_un_clic_sur_un_libelle_rapporte_la_case_cochee(monkeypatch):
    import app.agent.tools.browser_extension_tool as ext

    async def _send(_uid, _cmd, _payload, **_kw):
        return {"ok": True, "clicked": True, "matched": 1, "tag": "label",
                "text": "J'accepte les CGU", "url": "https://x", "checked": True}

    monkeypatch.setattr(ext, "_send_and_wait", _send)
    out = await ext.browser_tab_click.ainvoke({"selector": "label[for='cgu']", "user_id": "u"})
    assert "coch" in out.lower()


# ── Le navigateur serveur (Playwright) ──────────────────────────────────────


class _FausePage:
    url = "https://exemple.fr/inscription"

    def __init__(self, tag: str, type_: str = ""):
        self._tag, self._type = tag, type_
        self.appels: list[tuple] = []

    async def eval_on_selector(self, selector, script, *a):
        return {"tag": self._tag, "type": self._type}

    async def fill(self, selector, value, **kw):
        self.appels.append(("fill", selector, value))

    async def select_option(self, selector, value=None, label=None, **kw):
        self.appels.append(("select_option", selector, value, label))
        return [value or label]

    async def set_checked(self, selector, checked, **kw):
        self.appels.append(("set_checked", selector, checked))

    async def screenshot(self, **kw):
        return b""

    async def title(self):
        return "Inscription"


def _brancher(monkeypatch, page):
    import app.services.browser_manager as bm

    class _Mgr:
        async def get_page(self, _uid):
            return page

    monkeypatch.setattr(bm, "get_browser_manager", lambda: _Mgr())


@pytest.mark.asyncio
async def test_playwright_fill_choisit_une_option_sur_un_select(monkeypatch):
    from app.skills.builtin.browser_skill import browser_fill

    page = _FausePage("select")
    _brancher(monkeypatch, page)
    out = await browser_fill.ainvoke({"selector": "select[name='gender']", "value": "Homme", "user_id": "u"})
    assert page.appels and page.appels[0][0] == "select_option", page.appels
    assert "Homme" in out


@pytest.mark.asyncio
async def test_playwright_fill_coche_une_case(monkeypatch):
    from app.skills.builtin.browser_skill import browser_fill

    page = _FausePage("input", "checkbox")
    _brancher(monkeypatch, page)
    out = await browser_fill.ainvoke({"selector": "#cgu", "value": "true", "user_id": "u"})
    assert ("set_checked", "#cgu", True) in page.appels, page.appels
    assert "coch" in out.lower()


@pytest.mark.asyncio
async def test_playwright_fill_garde_le_texte_pour_les_champs_texte(monkeypatch):
    from app.skills.builtin.browser_skill import browser_fill

    page = _FausePage("input", "email")
    _brancher(monkeypatch, page)
    await browser_fill.ainvoke({"selector": "#email", "value": "a@b.fr", "user_id": "u"})
    assert ("fill", "#email", "a@b.fr") in page.appels


# ── La consigne : autonome sur les formulaires, jamais sur le paiement ──────


def test_la_consigne_exclut_le_paiement_et_rien_d_autre():
    from app.agent.missions.chat_loop import _consigne

    texte = _consigne("Inscris-moi sur le site X.", "").lower()
    assert "paiement" in texte
    assert "bancaire" in texte
