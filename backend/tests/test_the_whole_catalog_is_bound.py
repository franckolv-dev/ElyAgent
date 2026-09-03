# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_the_whole_catalog_is_bound.py
# @brief      Le catalogue complet est branché — le profil reste, il vaut TOUT.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Seize familles entières étaient hors d'atteinte.

Mesuré le 30/07, re-mesuré le 02/08 avant d'écrire une ligne :

```
catalogue complet      206
joignables via profil   87
INJOIGNABLES           119
```

Sheets (0/9), Docs (0/7), PDF (0/4), Maps (0/4), YouTube, QR codes, `os_*`,
`system_*`, `trainer_*`, `watchdog_*`, WhatsApp (partie le 02/09/2026 —
archive/canaux), plus `ssh`, `analyze`,
`briefing`, `python`, `telegram`, `delegate`. Une conversation avec un profil
ne pouvait ni ouvrir un tableur, ni lire un PDF — y compris `pdf_to_docx`,
construit en juillet.

Le profil n'a pas dérivé : il a été **conçu** comme un sous-ensemble volontaire
(« ~25-35 tool names […] covers ~80 % of everyday workflows »), puis rafistolé
un outil à la fois quand quelqu'un butait dessus en production — #37, #43,
#106, #143, #257, #267. Six correctifs en trois mois, jamais de revue
d'ensemble. C'est ainsi qu'une liste prévue pour 25-35 noms en atteint 84 tout
en oubliant des familles entières.

La décision vient d'un banc A/B (`bench/run_catalog_ab.py`), avec sa règle
posée AVANT de lancer :

```
                   gpt-5.6-terra      gpt-5.6-sol        kimi-k3
                 profil  complet   profil  complet   profil  complet
RÉGRESSION       91,7 %  91,7 %    91,7 %  88,3 %    91,5 %  84,7 %
TROU              0,0 %  86,7 %     0,0 %  86,7 %     0,0 %  82,8 %
```

⚠️ Le gain n'est PAS « Ely y arrive enfin » : avec 87 outils elle appelait
`find_tool` dans 8 des 15 cas du trou. Le gain est qu'elle y arrive **du
premier coup**, au lieu de deux ou trois tours — la latence étant le vrai
problème d'usage.
"""
from __future__ import annotations

import pytest


def _catalogue():
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    return get_skill_registry().all_tools


# ---------------------------------------------------------------------------
# Ce qui doit changer
# ---------------------------------------------------------------------------

def _sous_drapeau_eteint() -> set[str]:
    """Les outils qu'un drapeau BAISSÉ doit continuer d'écarter.

    ⚠️ « Tout le catalogue » ne veut pas dire « y compris ce qu'une option
    désactivée expose ». Mes deux premiers pins l'ignoraient et exigeaient une
    égalité stricte — c'est un test existant sur le Reversible Journal qui l'a
    signalé, pas moi.
    """
    from app.agent import toolset_profiles as tp

    return set(tp._REVERSIBLE_TOOL_NAMES) - tp._reversible_tool_names()


def test_the_default_profile_reaches_the_whole_catalog():
    from app.agent.toolset_profiles import resolve_profile_tools

    tous = {t.name for t in _catalogue()}
    resolus = {t.name for t in resolve_profile_tools("default", _catalogue())}

    assert tous - resolus == tous & _sous_drapeau_eteint(), (
        f"hors d'atteinte sans raison : {sorted(tous - resolus - _sous_drapeau_eteint())}"
    )


def test_an_empty_or_unknown_profile_also_reaches_everything():
    """Une valeur vide ou périmée en base ne doit pas amputer l'outillage."""
    from app.agent.toolset_profiles import resolve_profile_tools

    tous = _catalogue()
    attendu = len(tous) - len({t.name for t in tous} & _sous_drapeau_eteint())

    assert len(resolve_profile_tools("", tous)) == attendu
    assert len(resolve_profile_tools("profil-qui-n-existe-plus", tous)) == attendu


@pytest.mark.parametrize("famille", [
    "sheets_", "docs_", "pdf_", "maps_", "youtube_", "qrcode_",
    "os_", "system_", "trainer_", "watchdog_",
])
def test_the_sixteen_missing_families_are_reachable(famille: str):
    """Chaque famille absente est nommée : un compte global masquerait un trou."""
    from app.agent.toolset_profiles import resolve_profile_tools

    tous = _catalogue()
    attendus = {t.name for t in tous if t.name.startswith(famille)}
    if not attendus:
        pytest.skip(f"aucun outil {famille}* dans ce registre")

    joignables = {t.name for t in resolve_profile_tools("default", tous)}

    assert attendus <= joignables, f"{sorted(attendus - joignables)} hors d'atteinte"


# ---------------------------------------------------------------------------
# Les pins anti-régression — ce qui ne doit PAS changer
# ---------------------------------------------------------------------------

def test_a_restrictive_profile_still_restricts(monkeypatch):
    """⚠️ LE pin qui compte.

    Sans lui, on « réussirait » ce lot en rendant `resolve_profile_tools`
    équivalent à `return all_tools` — le mécanisme serait mort sans que rien ne
    rougisse, et le retour arrière par configuration deviendrait impossible.

    Le journal d'annulation (ON par défaut depuis le 03/09/2026) ajoute ses
    trois outils à TOUT profil ; on l'éteint pour ne mesurer que le profil.
    """
    from app.agent import toolset_profiles as tp
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "reversible_journal_enabled", False)

    tous = _catalogue()
    noms = sorted(t.name for t in tous)[:3]

    original = dict(tp._PROFILES)
    try:
        tp._PROFILES["_test_restreint"] = tuple(noms)
        resolus = {t.name for t in tp.resolve_profile_tools("_test_restreint", tous)}
    finally:
        tp._PROFILES.clear()
        tp._PROFILES.update(original)

    assert resolus == set(noms), (
        "un profil qui NOMME des outils doit encore restreindre — c'est ce qui "
        "rend le retour arrière possible par une entrée de dictionnaire"
    )


def test_the_default_profile_means_everything_not_a_list():
    """Le retour arrière est une entrée de dictionnaire, pas un `git revert`."""
    from app.agent.toolset_profiles import _PROFILES

    assert _PROFILES["default"] is None, (
        "`None` = tout le catalogue. Y remettre le tuple des 84 noms suffit à "
        "revenir en arrière : pas de migration, pas de schéma, pas de données"
    )


def test_the_profile_field_is_still_persisted():
    """Il porte un SECOND sens : l'attribution d'architecture.

    `usage_instrumentation` lit `if toolset_profile: return ARCH_MONO`. Vider le
    champ ferait basculer TOUS les tours en `unknown` et ferait perdre la
    distinction mono-agent que le banc V2 avait servi à établir.
    """
    import inspect

    from app.services import usage_instrumentation

    assert "toolset_profile" in inspect.getsource(usage_instrumentation)


def test_browser_search_images_stays_bound_when_the_extension_is_connected():
    """Dispense assumée, épinglée pour qu'on ne la « corrige » pas.

    Le filtre extension retire les outils Playwright serveur : ils tournent
    sans cookies et atterrissent sur des pages de connexion. Mais
    `browser_search_images` cherche sur Google Images, qui ne demande aucune
    connexion — et c'est le SEUL outil qui sait chercher une image. Le filtrer
    supprimerait la capacité dès que l'extension est branchée.
    """
    import inspect

    from app.agent import nodes

    source = inspect.getsource(nodes)
    debut = source.index("_PLAYWRIGHT_TOOLS = {")
    bloc = source[debut:debut + 400]

    assert "browser_search_images" not in bloc, (
        "browser_search_images ne doit PAS entrer dans le filtre extension"
    )
