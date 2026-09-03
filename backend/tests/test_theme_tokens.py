# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_theme_tokens.py
# @brief      Un jeton défini dans un seul thème casse l'autre en silence.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Les jetons de thème, épinglés depuis le brouillard du 21/08.

Franck, après un `make build` : « on dirait qu'il y a un voile blanc sur les
gris. Comme du brouillard... »

Le diagnostic était mesurable. Les FONDS du #324 étaient exactement ceux de la
maquette ; c'est le TEXTE que j'avais remonté de mon propre chef — secondaire
0.76 au lieu de 0.72, muted 0.61 au lieu de 0.54 — au nom du contraste WCAG.
Les tiers se sont resserrés entre eux et rapprochés des fonds clairs : de la
luminance tassée, c'est-à-dire du brouillard.

⚠️ La leçon n'est pas « le WCAG a tort ». C'est qu'un arbitrage défendable
ligne à ligne peut détruire un rendu d'ensemble, et que l'écran tranche. La
maquette est reposée telle quelle, et le contraste de `--text-muted` (2.41:1
sur le fond) est un choix ASSUMÉ, écrit dans le CSS.

CE QUE CE FICHIER ÉPINGLE, en revanche, est mécanique et sans arbitrage : un
jeton qui n'existe que dans un thème. En ajoutant `--dot-off` au sombre j'ai
oublié le clair — `var(--dot-off)` n'y résolvait rien, et le point d'état
héritait d'une couleur au hasard. Aucun outil du dépôt ne l'aurait vu : le CSS
ne lève pas, `tsc` ne lit pas les feuilles de style, et le défaut ne se voit
que dans le thème qu'on n'a pas ouvert.

Run with:  cd backend && python -m pytest tests/test_theme_tokens.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "styles" / "globals.css"


def _bloc(css: str, selecteur: str) -> dict[str, str]:
    """Les propriétés personnalisées déclarées dans un bloc de sélecteur."""
    i = css.index(selecteur)
    j = css.index("\n}", i)
    return dict(re.findall(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", css[i:j], re.M))


@pytest.fixture(scope="module")
def css() -> str:
    assert CSS.exists(), f"feuille de style introuvable : {CSS}"
    return CSS.read_text(encoding="utf-8")


def test_theme_tokens_exist_in_both_themes(css):
    """LE pin. Un jeton propre à un thème laisse l'autre sans valeur.

    Tolérance : un jeton absent d'un bloc est acceptable s'il est défini dans
    `:root`, qui sert de socle commun — c'est le cas de `--accent` et de ses
    variantes, que chaque thème redéfinit ou non selon ses besoins.
    """
    sombre = set(_bloc(css, '[data-theme="dark"]'))
    clair = set(_bloc(css, '[data-theme="light"]'))
    racine = set(_bloc(css, "\n:root {"))

    orphelins = sorted((sombre ^ clair) - racine)
    assert not orphelins, (
        f"jeton(s) défini(s) dans un seul thème et absent(s) de `:root` : "
        f"{', '.join(orphelins)}. Dans le thème qui ne l'a pas, `var()` ne "
        f"résout rien et la propriété hérite — un défaut invisible tant qu'on "
        f"n'ouvre pas ce thème-là."
    )


def test_the_dark_ramp_matches_the_design_values(css):
    """Les valeurs fournies par la maquette, posées telles quelles.

    ⚠️ Ce pin existe parce que je les ai déjà modifiées une fois « pour bien
    faire », et que c'est ce qui a produit le brouillard. Les changer à nouveau
    doit être un geste DÉLIBÉRÉ, qui casse ce test et oblige à revenir ici.

    Mis à jour à la refonte 09/2026 (« Ely Agent.dc.html », claude.ai/design) :
    la maquette repose tout le ramp en oklch sur la teinte 262, et l'accent
    passe du cyan (h=196) au bleu-indigo (h=276). Les hex du 21/08 ont donc été
    remplacés — délibérément, par ce commit-ci, et non dérivés « pour bien
    faire » comme la fois précédente.

    ⚠️ Le fond descend de #31363c à oklch(28 %), soit trois points de luminance
    plus bas. Si l'ensemble paraît trop sombre à l'usage, le levier est
    `--bg-app` SEUL : c'est la remontée des TEXTES qui avait produit le
    brouillard d'août, pas celle des fonds.
    """
    sombre = _bloc(css, '[data-theme="dark"]')
    maquette = {
        "--bg-app": "oklch(28% 0.018 262)",
        "--bg-surface": "oklch(32% 0.018 262)",
        "--bg-surface-2": "oklch(36% 0.020 262)",
        "--border-default": "oklch(40% 0.020 262)",
        "--text-primary": "oklch(95% 0.006 262)",
        "--text-secondary": "oklch(76% 0.012 262)",
        "--text-muted": "oklch(60% 0.012 262)",
        "--dot-off": "oklch(60% 0.012 262)",
    }
    for jeton, attendu in maquette.items():
        actuel = (sombre.get(jeton) or "").strip().lower()
        assert actuel == attendu, (
            f"{jeton} vaut « {actuel} », la maquette du 09/2026 dit « {attendu} ». "
            f"Si c'est voulu, mets à jour ce pin dans le même commit."
        )


def test_the_accent_is_blue(css):
    """La teinte de l'accent, épinglée.

    Le seul changement de couleur que Franck a nommé explicitement : « du vert
    au bleu ». Toute l'interface — jusqu'au wireframe de l'avatar — lit
    `--accent-h`, donc cette ligne unique porte la bascule. La repasser à 196
    (cyan) sans y penser reteindrait tout d'un coup ; ce pin l'interdit en
    silence.
    """
    racine = _bloc(css, "\n:root {")
    assert racine.get("--accent-h", "").strip() == "276", (
        f"`--accent-h` vaut « {racine.get('--accent-h')} » ; la refonte 09/2026 "
        f"pose 276 (bleu-indigo). 196 était le cyan d'avant."
    )


def test_the_conversation_thread_sits_below_the_rest(css):
    """La demande explicite : le fil plus foncé que le châssis, en sombre.

    Le sens s'INVERSE en clair — « se détacher » y veut dire plus clair. Le
    pin vérifie donc une relation, pas une valeur, et il la vérifie dans le
    bon sens pour chaque thème.
    """
    # La maquette 09/2026 écrit le ramp en oklch, la précédente en hex. Le pin
    # vérifie une RELATION entre deux fonds, pas une notation : il accepte donc
    # les deux et compare dans le même espace. Sans ça, changer d'écriture
    # cassait le test pour une raison qui n'a rien à voir avec ce qu'il garde.
    def lum(couleur: str) -> float:
        c = couleur.strip().lower()
        if c.startswith("oklch("):
            nombres = re.findall(r"-?[\d.]+", c[6:])
            lightness = float(nombres[0])
            # `oklch(28% ...)` et `oklch(0.28 ...)` désignent la même chose.
            return lightness / 100 if "%" in c.split()[0] else lightness
        h = c.lstrip("#")
        def canal(v: int) -> float:
            x = v / 255
            return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
        r, g, b = (canal(int(h[k:k + 2], 16)) for k in (0, 2, 4))
        # Oklab est perceptuel, la luminance relative ne l'est pas : on ramène
        # l'hex vers la même échelle par la clarté L* approchée, sinon les deux
        # branches ne seraient pas comparables entre elles. Ici les deux
        # opérandes de chaque assertion partagent toujours la même notation,
        # donc seule la MONOTONIE compte.
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) ** (1 / 3)

    sombre = _bloc(css, '[data-theme="dark"]')
    clair = _bloc(css, '[data-theme="light"]')

    assert lum(sombre["--bg-chat"]) < lum(sombre["--bg-app"]), (
        "en thème sombre le fil doit passer SOUS le châssis"
    )
    assert lum(clair["--bg-chat"]) > lum(clair["--bg-app"]), (
        "en thème clair il doit passer AU-DESSUS — descendre y poserait une "
        "bande grise au milieu de la page"
    )


def test_the_thread_surface_is_actually_applied(css):
    """Un jeton que personne n'utilise ne change rien à l'écran."""
    page = CSS.parents[1] / "app" / "chat" / "page.tsx"
    assert ".chat-thread" in css, "la règle `.chat-thread` a disparu du CSS"
    assert "var(--bg-chat)" in css, "`.chat-thread` ne consomme plus `--bg-chat`"
    assert "chat-thread" in page.read_text(encoding="utf-8"), (
        "la classe n'est plus posée sur la colonne de conversation"
    )
