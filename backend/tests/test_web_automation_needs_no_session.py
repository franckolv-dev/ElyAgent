# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_web_automation_needs_no_session.py
# @brief      Une tâche planifiée n'a pas de « page courante ».
# @license    Elastic License 2.0
# =============================================================================
"""Automatisation web « un coup » — chantier de roadmap livré le 22/08.

CE QUE LA ROADMAP DISAIT, ET CE QUI ÉTAIT INEXACT
--------------------------------------------------
« L'extension Chrome couvre l'interactif, pas le batch. Playwright est déjà
là ; il manque la surface d'exposition. »

Le premier point était faux : `browser_skill` expose DÉJÀ `browser_screenshot`
et `browser_get_text`, côté serveur, via Playwright. Le trou réel était plus
étroit — et le vérifier a évité d'écrire deux outils en double.

Ces deux-là travaillent sur la page COURANTE d'une session utilisateur. Une
tâche planifiée n'en a pas :

- elle tourne sans personne devant ;
- elle peut tourner PENDANT que l'utilisateur navigue — réutiliser sa session
  la lui déplacerait sous les yeux, et le résultat dépendrait de l'endroit où
  il l'a laissée ;
- `navigate` puis `screenshot`, c'est deux tours de modèle là où un suffit.

CE QUE CES PINS TIENNENT
-------------------------
1. L'ISOLEMENT : le contexte est jetable et fermé quoi qu'il arrive. Un
   contexte oublié garde un process Chromium enfant vivant ; une tâche horaire
   en fuirait un par heure jusqu'à la limite mémoire du conteneur.
2. LE REFUS DE `file://` : un outil qui annonce « web » ne doit pas pouvoir
   lire le disque du conteneur.
3. LA CLASSIFICATION : invariant 2 du dépôt — un outil non classé est traité
   comme engageant. Quatre outils ajoutés sans entrée dans `TOOL_NATURE`
   demanderaient une confirmation humaine à chaque capture.
4. LA TRONCATURE QUI S'ANNONCE : muette, elle ferait résumer un article sur sa
   première moitié en croyant l'avoir lu entier.

Run with:  cd backend && python -m pytest tests/test_web_automation_needs_no_session.py -v
"""
from __future__ import annotations

import inspect
import json

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — L'isolement : jamais la session de quelqu'un
# ─────────────────────────────────────────────────────────────────────

def test_no_one_shot_tool_touches_a_user_session():
    """LE pin du chantier. `get_page(user_id)` rend la page COURANTE d'un
    utilisateur : s'en servir ici déplacerait sa navigation sous ses yeux."""
    from app.agent.tools import web_tool

    src = inspect.getsource(web_tool)
    assert "get_page(" not in src, (
        "un outil « un coup » utilise la session d'un utilisateur — il doit "
        "passer par `one_shot_page`, qui crée un contexte jetable"
    )
    assert src.count("one_shot_page(") == 4, (
        "les quatre outils doivent tous passer par le contexte jetable"
    )


@pytest.mark.asyncio
async def test_the_throwaway_context_is_always_closed():
    """⚠️ Un contexte oublié garde un process Chromium vivant. Une tâche
    horaire en fuirait un par heure jusqu'à saturer la limite mémoire.

    On vérifie la fermeture MÊME quand le corps lève — c'est le cas qui
    fuirait, et c'est celui qu'on n'observe jamais à la main.
    """
    from app.services.browser_manager import BrowserManager

    ferme: list[str] = []

    class _Contexte:
        async def new_page(self):
            return object()

        async def close(self):
            ferme.append("fermé")

    class _Navigateur:
        async def new_context(self, **_k):
            return _Contexte()

    mgr = BrowserManager()
    mgr._browser = _Navigateur()
    mgr._available = True

    with pytest.raises(RuntimeError):
        async with mgr.one_shot_page():
            raise RuntimeError("la page explose en plein travail")

    assert ferme == ["fermé"], (
        "le contexte doit être fermé même quand le corps lève"
    )


@pytest.mark.asyncio
async def test_a_throwaway_context_is_not_stored_as_a_session():
    """Le contexte jetable ne doit pas atterrir dans `_sessions` : il y
    survivrait à l'appel et serait resservi à un utilisateur."""
    from app.services.browser_manager import BrowserManager

    class _Contexte:
        async def new_page(self):
            return object()

        async def close(self):
            pass

    class _Navigateur:
        async def new_context(self, **_k):
            return _Contexte()

    mgr = BrowserManager()
    mgr._browser = _Navigateur()
    mgr._available = True

    async with mgr.one_shot_page():
        pass

    assert mgr._sessions == {}, "un contexte jetable ne doit laisser aucune session"


# ─────────────────────────────────────────────────────────────────────
# 2 — Le périmètre : le web, pas le disque
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mauvaise", [
    "file:///etc/passwd",
    "file:///app/data/cyberentity.db",
    "javascript:alert(1)",
    "data:text/html,<h1>x</h1>",
    "",
    "   ",
])
def test_only_http_urls_are_accepted(mauvaise):
    """⚠️ Un outil qui annonce « web » ne doit pas pouvoir lire le disque du
    conteneur. `file://` y donnerait accès par la porte d'un outil que
    personne ne surveille pour ça."""
    from app.agent.tools.web_tool import _valider_url

    assert _valider_url(mauvaise) is not None, (
        f"« {mauvaise} » est acceptée — elle ne devrait pas l'être"
    )


@pytest.mark.parametrize("bonne", [
    "https://example.com",
    "http://example.com/page?a=1",
    "HTTPS://EXAMPLE.COM",
])
def test_real_web_urls_pass(bonne):
    """Le refus ne doit pas déborder sur ce qui est légitime."""
    from app.agent.tools.web_tool import _valider_url

    assert _valider_url(bonne) is None


@pytest.mark.asyncio
async def test_a_refused_url_never_opens_a_browser():
    """La validation passe AVANT le navigateur. Sinon on paierait un contexte
    Chromium pour refuser une entrée qu'on savait mauvaise."""
    from app.agent.tools.web_tool import web_extract

    # Aucun double n'est posé : si l'outil touchait au navigateur, il lèverait
    # ou tenterait un vrai lancement. Il doit rendre son refus sans rien ouvrir.
    brut = await web_extract.ainvoke({"url": "file:///etc/passwd"})
    charge = json.loads(brut)
    assert charge["ok"] is False
    assert "http" in charge["error"].lower()


# ─────────────────────────────────────────────────────────────────────
# 3 — La classification (invariant 2 du dépôt)
# ─────────────────────────────────────────────────────────────────────

def test_every_new_tool_is_classified():
    """Invariant 2 : « Un outil non classé est traité comme engageant. »

    Sans entrée dans `TOOL_NATURE`, chaque capture demanderait une
    confirmation humaine — ce qui rendrait ces outils inutilisables dans une
    tâche planifiée, c'est-à-dire exactement leur raison d'être.
    """
    from app.agent.tool_nature import TOOL_NATURE

    for nom in ("web_screenshot", "web_to_pdf", "web_extract", "web_compare"):
        assert nom in TOOL_NATURE, f"{nom} n'est pas classé"


def test_the_two_that_write_a_file_are_classified_as_writes():
    """⚠️ Le piège du classement : « ils ne font que lire le web ».

    L'effet qu'on classe est celui de l'outil sur LE SYSTÈME, pas son
    intention. Ces deux-là déposent un fichier — réversible et privé, donc
    ECRITURE, comme `qrcode_generate`.
    """
    from app.agent.tool_nature import TOOL_NATURE

    assert TOOL_NATURE["web_screenshot"].effect == "ECRITURE"
    assert TOOL_NATURE["web_to_pdf"].effect == "ECRITURE"
    assert TOOL_NATURE["web_extract"].effect == "LECTURE"
    assert TOOL_NATURE["web_compare"].effect == "LECTURE"


def test_none_of_them_arbitrates():
    """Aucun ne tranche de choix de forme : le modèle choisit l'URL et le
    sélecteur, jamais l'apparence du résultat. Une capture est ce que la page
    montre — deux personnes compétentes n'en feraient pas deux versions."""
    from app.agent.tool_nature import TOOL_NATURE

    for nom in ("web_screenshot", "web_to_pdf", "web_extract", "web_compare"):
        assert TOOL_NATURE[nom].arbitrates is False, (
            f"{nom} est marqué arbitre — si c'est voulu, la demande de "
            f"l'utilisateur doit pouvoir l'atteindre (cf. #294)"
        )


# ─────────────────────────────────────────────────────────────────────
# 4 — Ce que les résultats disent d'eux-mêmes
# ─────────────────────────────────────────────────────────────────────

def test_the_descriptions_say_which_family_to_pick():
    """Deux paires proches dans un catalogue de ~145 outils, c'est une
    occasion de se tromper. On la ferme par le texte : chaque description
    nomme son usage ET l'autre outil."""
    from app.agent.tools.web_tool import web_extract, web_screenshot

    assert "browser_screenshot" in (web_screenshot.description or ""), (
        "web_screenshot ne dit pas quand utiliser l'outil de session à la place"
    )
    assert "browser_get_text" in (web_extract.description or ""), (
        "web_extract ne dit pas quand utiliser browser_get_text à la place"
    )


def test_truncation_announces_itself():
    """⚠️ Une troncature muette ferait résumer un article sur sa première
    moitié en croyant l'avoir lu entier — l'erreur qu'aucune relecture ne
    rattrape, parce que rien ne la signale."""
    from app.agent.tools import web_tool

    src = inspect.getsource(web_tool)
    assert '"truncated"' in src and '"note"' in src, (
        "l'extraction doit signaler qu'elle a coupé, et dire quoi faire"
    )
    assert '"diff_truncated"' in src, (
        "la comparaison doit signaler un diff coupé"
    )


def test_an_error_is_json_not_prose():
    """Une erreur en prose se fait interpréter par le modèle, qui raconte
    alors ce qu'il croit avoir compris. `ok: false` se lit sans jugement."""
    from app.agent.tools.web_tool import _erreur

    charge = json.loads(_erreur("quelque chose a cassé", "https://x.test"))
    assert charge["ok"] is False
    assert charge["error"] and charge["url"]


@pytest.mark.asyncio
async def test_compare_refuses_an_empty_reference():
    """Sans référence, « la page a changé » n'a aucun sens.

    Et rendre `changed: true` sur une première exécution déclencherait une
    alerte de veille à chaque NOUVELLE surveillance — le bruit qui fait
    désactiver la fonctionnalité au bout de trois jours.

    Le refus arrive avant tout accès réseau : aucun double n'est nécessaire.
    """
    from app.agent.tools.web_tool import web_compare

    charge = json.loads(await web_compare.ainvoke({
        "url": "https://example.com", "reference_text": "   ",
    }))
    assert charge["ok"] is False
    assert "web_extract" in charge["error"], (
        "le refus doit dire COMMENT obtenir une référence, pas seulement "
        "qu'elle manque"
    )


# ─────────────────────────────────────────────────────────────────────
# 5 — L'outil est réellement branché
# ─────────────────────────────────────────────────────────────────────

def test_the_skill_is_imported_at_startup():
    """Un outil non importé n'existe pas. Le fichier peut être parfait et le
    catalogue l'ignorer complètement."""
    from pathlib import Path

    init = Path(__file__).resolve().parents[1] / "app" / "skills" / "builtin" / "__init__.py"
    assert "web_automation_skill" in init.read_text(encoding="utf-8"), (
        "la compétence n'est pas importée au démarrage — ses outils ne seront "
        "jamais dans le catalogue"
    )
