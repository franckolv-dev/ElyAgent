# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_all_configured_models_resolve.py
# @brief      Les 16 modèles réellement déclarés doivent tous résoudre.
# @license    MIT
# =============================================================================
"""Pins de couverture des modèles réellement configurés.

Le contrôle de réalité (#265) a signalé **18 valeurs** au premier démarrage —
et notamment que ma correction de la veille (#263) était **incomplète** : je
n'avais traité que les 10 modèles que j'avais vus dans une sortie tronquée,
alors que ``llm_instances`` en déclare **16**. Cinq restaient donc tronqués à
8 192 tokens.

C'est la démonstration du principe : l'instrument voit ce que la lecture
manuelle manque. Ce test fige la liste au 26/07/2026 pour que la CI garde le
niveau ; **la dérive future est attrapée par le contrôle au démarrage**, pas
ici — un modèle ajouté depuis l'interface n'apparaîtrait jamais dans un
fichier de test.

Run with:  cd backend && python -m pytest tests/test_all_configured_models_resolve.py -v
"""
from __future__ import annotations

import pytest

# `SELECT DISTINCT model FROM llm_instances` au 26/07/2026.
_CONFIGURED = [
    "deepseek-v4-flash", "deepseek-v4-pro",
    "mistral-small-latest", "mistral-medium-latest", "mistral-large-latest",
    "gpt-5.6-terra",
    "qwen/qwen3.5-9b", "qwen/qwen2.5-coder-14b",
    "lmstudio-community/gemma-4-E4B-it-MLX-8bit",
    "lmstudio-community/Qwen3-4B-Instruct-2507-MLX-8bit",
    "gemini-3.1-flash-lite-preview",
    "kimi-k2.6", "qwen3-vl-plus", "qwen3.6-flash", "qwen3.6-plus",
]


@pytest.mark.parametrize("model", _CONFIGURED)
def test_every_configured_model_has_a_context_window(model):
    """Un modèle sans fenêtre déclarée est tronqué à 8 192 tokens en silence."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    assert get_context_window(model) != _CONTEXT_WINDOWS["_default"], (
        f"{model} sera tronqué à 8 192 tokens"
    )


@pytest.mark.asyncio
async def test_no_configured_model_falls_back_on_its_window():
    """Formulé via le contrôle lui-même : c'est lui qui tournera au démarrage."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(models=_CONFIGURED, bound_tools=[])
    windows = [f.subject for f in findings if f.kind == "model_window"]

    assert not windows, f"modèles sans fenêtre : {windows}"


# Ceux dont le coût par token est nul PAR NATURE : les modèles locaux (LM
# Studio, aucune facturation) et ceux consommés via un forfait (gpt-5.6-terra
# passe par l'abonnement ChatGPT). Les inscrire à 0.0 dit « gratuit », ce qui
# est vrai — au lieu du tarif générique inventé de $1/$3 par million.
_ZERO_COST = [
    "gpt-5.6-terra",
    "qwen/qwen3.5-9b", "qwen/qwen2.5-coder-14b",
    "lmstudio-community/gemma-4-E4B-it-MLX-8bit",
    "lmstudio-community/Qwen3-4B-Instruct-2507-MLX-8bit",
]


@pytest.mark.parametrize("model", _ZERO_COST)
def test_a_model_billed_by_subscription_or_local_costs_nothing_per_token(model):
    """Avant : `_PRICING.get(model, (1.0, 3.0))` leur inventait un prix. Le
    coût affiché des modèles locaux était donc faux — et faux à la HAUSSE,
    ce qui décourage précisément l'usage local qu'on veut favoriser."""
    from app.services.analytics_service import _PRICING, estimate_cost

    assert model in _PRICING, f"{model} reçoit encore un tarif générique inventé"
    assert estimate_cost(model, 1_000_000, 1_000_000) == 0.0
