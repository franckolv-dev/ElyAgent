# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_real_context_window.py
# @brief      Ely tronquait tout comme si chaque modèle avait 8 K de fenêtre.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins de la fenêtre de contexte réelle.

**Le défaut, mesuré le 26/07/2026 sur un run de production.** Un message de
débordement lâche le chiffre :

    Context overflow: 5677 message tokens + 1516 system tokens = 7193,
    but budget is 7168 tokens (model=medium, window=8192, …)

Deux erreurs superposées :

1. ``nodes.py`` passait ``_tier.value`` — « medium », « complex » — là où
   ``fit_messages_to_context`` attend un **nom de modèle**. Ironie : le vrai
   modèle était résolu deux lignes plus haut par ``describe_llm``… mais
   seulement pour les analytics, avec le commentaire « so analytics shows
   lm_studio/… instead of tier-medium ». La troncature, elle, gardait le tier.
2. La table ``_CONTEXT_WINDOWS`` ne connaissait **aucun modèle réellement
   utilisé** par Ely — seulement ``gemma4:26b``, ``gpt-4o``,
   ``claude-sonnet-4-6``. Même en lui passant le bon nom, elle serait retombée
   sur le défaut.

Conséquence : **8 192 tokens de fenêtre supposée pour tout le monde**, alors
que DeepSeek v4 en offre 64 000 et GPT-5.6 davantage. Ely jetait donc 75 à
95 % du contexte qu'elle avait le droit de garder — 23 débordements en 31
appels d'outils sur le run mesuré, et la consigne de mission emportée avec
(cf. ``test_mission_mandate_survives_truncation``).

**Prudence assumée** : les valeurs retenues sont volontairement inférieures aux
fenêtres annoncées. Sous-estimer coûte un peu de contexte ; surestimer fait
rejeter la requête entière par le fournisseur.

Run with:  cd backend && python -m pytest tests/test_real_context_window.py -v
"""
from __future__ import annotations

import pytest

# Les modèles réellement configurés dans `llm_instances` au 26/07/2026.
_MODELS_IN_USE = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
    "gpt-5.6-terra",
    "qwen/qwen3.5-9b",
    "qwen/qwen2.5-coder-14b",
    "lmstudio-community/gemma-4-E4B-it-MLX-8bit",
    "lmstudio-community/Qwen3-4B-Instruct-2507-MLX-8bit",
]


@pytest.mark.parametrize("model", _MODELS_IN_USE)
def test_a_model_actually_in_use_is_known(model):
    """LE test du lot : aucun modèle qu'Ely fait tourner ne doit retomber sur
    le défaut prudent réservé aux inconnus."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    window = get_context_window(model)

    assert window != _CONTEXT_WINDOWS["_default"], (
        f"{model} retombe sur le défaut ({window}) — Ely tronquera comme si "
        f"elle avait 8 K de fenêtre"
    )
    assert window >= 32_000, f"{model} : fenêtre {window}, invraisemblablement basse"


def test_an_unknown_model_still_falls_back_conservatively():
    """Le défaut reste un défaut : un modèle inconnu ne doit pas hériter d'une
    fenêtre optimiste qui ferait rejeter la requête par le fournisseur."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    assert get_context_window("un-modele-jamais-vu-42") == _CONTEXT_WINDOWS["_default"]


def test_a_tier_name_is_not_a_model_name():
    """Garde-fou : si un jour on repasse un tier au lieu d'un modèle, ce test
    ne le rattrapera pas tout seul — mais il documente que « medium » n'est
    PAS un modèle et retombera sur le défaut."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    for tier in ("simple", "medium", "complex"):
        assert get_context_window(tier) == _CONTEXT_WINDOWS["_default"]


def test_the_agent_node_passes_a_model_not_a_tier():
    """La correction n° 1 : ``nodes.py`` doit passer le modèle résolu, pas
    l'étiquette du tier."""
    from pathlib import Path

    src = Path("app/agent/nodes.py").read_text(encoding="utf-8")

    assert "model=_tier_key," not in src, (
        "nodes.py passe encore le tier à la troncature : la fenêtre retombera "
        "toujours sur 8 192"
    )


def test_a_deepseek_turn_gets_a_real_budget():
    """Effet concret : la conversation qui débordait à 7 168 tokens tient
    désormais largement."""
    from app.services.context_manager import get_context_window

    assert get_context_window("deepseek-v4-pro") - 1024 > 30_000


def test_the_breakdown_percentage_becomes_meaningful():
    """La ventilation de #255 divise par cette fenêtre : tant qu'elle valait
    8 192 pour tout le monde, le pourcentage affiché était faux."""
    from app.services.context_breakdown import compute_context_breakdown

    result = compute_context_breakdown(
        system_prompt="x" * 40_000, tools=[], messages=[], model="deepseek-v4-pro",
    )

    assert result["context_max"] >= 32_000
    assert 0 < result["context_percent"] < 100
