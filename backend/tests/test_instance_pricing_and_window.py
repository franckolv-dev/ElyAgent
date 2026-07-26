# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_instance_pricing_and_window.py
# @brief      Fenêtre et tarifs vivent sur l'INSTANCE, là où l'utilisateur les
#             configure — plus dans des tables du code qui dérivent.
# @license    Elastic License 2.0
# =============================================================================
"""Pins des tarifs et de la fenêtre portés par l'instance.

**Pourquoi ce lot supprime la classe de défaut, et pas seulement ses cas.**

Le 26/07, ``get_context_window()`` renvoyait 8 192 pour tous les modèles, et
``_PRICING`` en ignorait 9 sur 16. Chaque correction manuelle a été rattrapée
par la suivante : ma passe de #263 en a oublié 5, que le contrôle de réalité a
trouvés le lendemain. La raison est structurelle — **Franck ajoute ses modèles
depuis l'interface, et aucune table du code ne peut le savoir.**

Porter fenêtre et tarifs SUR L'INSTANCE renverse ça : la valeur est saisie au
moment où le modèle est déclaré, par la personne qui lit la page tarifaire du
fournisseur. Plus de dérive possible entre le déclaré et le connu, puisque
c'est le même geste.

**Ordre de résolution retenu**, du plus spécifique au plus général :

1. la valeur portée par l'instance — vérité configurée par l'utilisateur ;
2. la table du code — utile pour les modèles courants non encore configurés ;
3. le défaut prudent (8 192 tokens) — et le contrôle de réalité le signale.

Les colonnes sont NULLABLE : « non déclaré » doit rester distinct de
« déclaré à zéro ». Un modèle local à 0,0 est gratuit ; un modèle sans tarif
est inconnu, et ça ne se confond pas.

**Devise** : les tarifs sont stockés en **USD par million de tokens**, comme
les fournisseurs les publient. Convertir à la saisie produirait une valeur
vraie un jour, puis vieillissant en silence — très exactement le défaut qu'on
supprime ici. La conversion en euros est un réglage d'affichage.

Run with:  cd backend && python -m pytest tests/test_instance_pricing_and_window.py -v
"""
from __future__ import annotations

import pytest


# ------------------------------------------------------- le schéma

def test_the_instance_carries_its_window_and_prices():
    from app.models.llm_instance import LLMInstance

    for column in ("context_window", "input_price_per_million", "output_price_per_million"):
        assert hasattr(LLMInstance, column), f"colonne absente : {column}"


def test_the_columns_are_nullable_so_undeclared_differs_from_zero():
    """« Pas de tarif » et « gratuit » sont deux états distincts : un modèle
    local à 0,0 est gratuit pour de vrai, un modèle sans valeur est inconnu et
    doit continuer d'être signalé."""
    from app.models.llm_instance import LLMInstance

    for column in ("context_window", "input_price_per_million", "output_price_per_million"):
        assert LLMInstance.__table__.columns[column].nullable


# ------------------------------------------- la priorité de résolution

def test_an_instance_window_wins_over_the_code_table():
    """LE test du lot : ce que l'utilisateur déclare prime."""
    from app.services.context_manager import get_context_window, set_instance_overrides

    set_instance_overrides(windows={"deepseek-v4-pro": 128_000}, prices={})
    try:
        assert get_context_window("deepseek-v4-pro") == 128_000
    finally:
        set_instance_overrides(windows={}, prices={})


def test_the_code_table_still_serves_an_unconfigured_model():
    """Le socle reste : un modèle courant non encore configuré garde une
    valeur raisonnable plutôt que le défaut prudent."""
    from app.services.context_manager import get_context_window, set_instance_overrides

    set_instance_overrides(windows={}, prices={})
    assert get_context_window("deepseek-v4-pro") == 64_000


def test_an_unknown_model_still_falls_back_conservatively():
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    assert get_context_window("modele-jamais-vu") == _CONTEXT_WINDOWS["_default"]


def test_an_instance_price_wins_over_the_code_table():
    from app.services.analytics_service import estimate_cost
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides(windows={}, prices={"deepseek-v4-flash": (2.0, 6.0)})
    try:
        assert estimate_cost("deepseek-v4-flash", 1_000_000, 1_000_000) == 8.0
    finally:
        set_instance_overrides(windows={}, prices={})


def test_a_zero_price_declared_on_the_instance_is_honoured():
    """Le cas des modèles locaux : 0,0 doit rester 0,0 et ne pas être pris
    pour « non déclaré », sinon le tarif générique revient par la fenêtre."""
    from app.services.analytics_service import estimate_cost
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides(windows={}, prices={"un-modele-local": (0.0, 0.0)})
    try:
        assert estimate_cost("un-modele-local", 5_000_000, 5_000_000) == 0.0
    finally:
        set_instance_overrides(windows={}, prices={})


# --------------------------------------- le contrôle de réalité s'aligne

@pytest.mark.asyncio
async def test_a_model_priced_on_its_instance_is_no_longer_reported():
    """Le contrôle doit se taire dès que l'utilisateur a fait le geste — sinon
    il réclame pour toujours ce qui est déjà réglé."""
    from app.services.config_reality import check_config_reality
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides(
        windows={"kimi-k3": 1_000_000}, prices={"kimi-k3": (0.6, 2.5)},
    )
    try:
        findings = await check_config_reality(
            models=["kimi-k3"], bound_tools=[], resolved_models={},
        )
        assert findings == [], f"réclame encore : {findings}"
    finally:
        set_instance_overrides(windows={}, prices={})


@pytest.mark.asyncio
async def test_a_model_without_any_declaration_is_still_reported():
    from app.services.config_reality import check_config_reality
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides(windows={}, prices={})
    findings = await check_config_reality(
        models=["un-modele-jamais-declare"], bound_tools=[], resolved_models={},
    )

    assert {f.kind for f in findings} == {"model_window", "model_pricing"}


# ------------------------------------------------- robustesse

def test_setting_overrides_never_raises_on_odd_input():
    """Ces valeurs viennent d'un formulaire : elles arriveront un jour vides,
    négatives ou en texte."""
    from app.services.context_manager import get_context_window, set_instance_overrides

    for windows in (None, {}, {"x": None}, {"x": "pas un nombre"}, {"x": -5}):
        set_instance_overrides(windows=windows, prices=None)
        assert isinstance(get_context_window("x"), int)
    set_instance_overrides(windows={}, prices={})
