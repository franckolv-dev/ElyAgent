# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_max_output_tokens.py
# @brief      Le plafond de réponse cesse d'être 4 096 pour tout le monde —
#             et reste cohérent avec le budget de contexte.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Pins du plafond de tokens en sortie.

**Le constat.** ``max_output_tokens`` valait **4 096 en dur à douze endroits**
de ``llm_provider`` (seul Anthropic était à 8 192), quand Gemini 3.6 Flash en
autorise **65 536**. Une réponse longue était donc coupée net, sans erreur et
sans que rien ne le signale — la même famille que la fenêtre à 8 192 et les
tarifs inventés.

**Pourquoi un plafond large et uniforme serait un remède pire que le mal**, et
c'est ce qui justifie un champ par modèle plutôt qu'une constante généreuse :

1. un fournisseur **refuse** une valeur au-dessus de la limite de son modèle —
   erreur dure, pas dégradation ;
2. sur les serveurs locaux (LM Studio, llama.cpp), le plafond de sortie est
   **prélevé sur la fenêtre** : 65 536 en sortie sur un modèle à 32 768 ne
   laisse rien pour l'entrée ;
3. Ely ne réserve que **1 024 tokens** pour la réponse dans son calcul de
   budget (``reserve_for_response``). Autoriser 65 536 en sortie sans toucher
   à ça revient à ajuster l'entrée comme si la réponse tenait en une phrase.

Le point 3 est le cœur de ce lot : **les deux nombres doivent bouger
ensemble**, sinon on remplace un plafond faux par une incohérence.

Run with:  cd backend && python -m pytest tests/test_max_output_tokens.py -v
"""
from __future__ import annotations

import pytest


def test_the_instance_carries_its_output_cap():
    from app.models.llm_instance import LLMInstance

    assert hasattr(LLMInstance, "max_output_tokens")
    assert LLMInstance.__table__.columns["max_output_tokens"].nullable


def test_a_declared_cap_is_returned():
    from app.services.context_manager import instance_max_output, set_instance_overrides

    set_instance_overrides(outputs={"gemini-3.6-flash": 65_536})
    try:
        assert instance_max_output("gemini-3.6-flash") == 65_536
    finally:
        set_instance_overrides()


def test_an_undeclared_model_returns_none_not_a_guess():
    """« Non renseigné » doit rester distinct : c'est l'appelant qui décide de
    son défaut, pas le registre qui invente un chiffre."""
    from app.services.context_manager import instance_max_output, set_instance_overrides

    set_instance_overrides()
    assert instance_max_output("un-modele-sans-plafond") is None


# ------------------------------------ la cohérence entre les deux nombres

def test_the_context_budget_reserves_what_the_answer_may_use():
    """LE test du lot. Réserver 1 024 tokens quand le modèle peut en produire
    65 536 fait tenir l'entrée sur une hypothèse fausse."""
    from app.services.context_manager import (
        reserve_for_model, set_instance_overrides,
    )

    # Cas réel : Franck déclare la fenêtre ET le plafond de sortie.
    set_instance_overrides(
        windows={"gemini-3.6-flash": 1_000_000},
        outputs={"gemini-3.6-flash": 65_536},
    )
    try:
        assert reserve_for_model("gemini-3.6-flash") == 65_536
    finally:
        set_instance_overrides()


def test_an_output_cap_without_a_declared_window_stays_conservative():
    """Effet de bord voulu : sans fenêtre déclarée, on retombe sur le défaut
    prudent de 8 192, et réserver 65 536 dessus n'aurait aucun sens. La
    réserve reste donc bornée — déclarer les deux valeurs va de pair."""
    from app.services.context_manager import reserve_for_model, set_instance_overrides

    set_instance_overrides(outputs={"modele-sans-fenetre": 65_536})
    try:
        assert reserve_for_model("modele-sans-fenetre") < 8_192
    finally:
        set_instance_overrides()


def test_an_undeclared_model_keeps_the_historical_reserve():
    """Pas de changement de comportement pour ce qui n'est pas configuré."""
    from app.services.context_manager import reserve_for_model, set_instance_overrides

    set_instance_overrides()
    assert reserve_for_model("un-modele-sans-plafond") == 1024


def test_the_reserve_never_swallows_the_whole_window():
    """Garde-fou : sur un modèle local à 32 768 dont on déclarerait 32 000 en
    sortie, réserver la totalité ne laisserait plus rien à l'entrée. La
    réserve est plafonnée à une fraction de la fenêtre."""
    from app.services.context_manager import reserve_for_model, set_instance_overrides

    set_instance_overrides(
        windows={"un-local": 32_768}, outputs={"un-local": 32_000},
    )
    try:
        reserve = reserve_for_model("un-local")
        assert reserve < 32_768 / 2, (
            f"réserve de {reserve} sur une fenêtre de 32 768 : l'entrée n'a "
            f"plus la place d'exister"
        )
    finally:
        set_instance_overrides()


def test_fitting_messages_uses_the_model_reserve():
    """Bout en bout : la troncature doit tenir compte de la place que la
    réponse va prendre."""
    from langchain_core.messages import HumanMessage

    from app.services.context_manager import (
        fit_messages_to_context, set_instance_overrides,
    )

    msgs = [HumanMessage(content="mot " * 3_000) for _ in range(4)]
    set_instance_overrides(windows={"m": 16_000}, outputs={"m": 8_000})
    try:
        kept_large = fit_messages_to_context(msgs, system_prompt="x", model="m")
    finally:
        set_instance_overrides()

    set_instance_overrides(windows={"m": 16_000})
    try:
        kept_small = fit_messages_to_context(msgs, system_prompt="x", model="m")
    finally:
        set_instance_overrides()

    assert len(kept_large) <= len(kept_small), (
        "réserver plus pour la réponse doit laisser MOINS de place à l'entrée"
    )


# ---------------------------------------------------- le plafond est utilisé

def test_the_provider_builders_stop_hardcoding_4096():
    """Douze occurrences de 4 096 en dur : le champ ne sert à rien tant
    qu'elles décident à sa place."""
    from pathlib import Path

    src = Path("app/services/llm_provider.py").read_text(encoding="utf-8")

    assert "instance_max_output" in src, (
        "llm_provider ne consulte jamais le plafond déclaré"
    )


@pytest.mark.asyncio
async def test_a_model_without_an_output_cap_is_reported():
    """Le contrôle de réalité doit le signaler comme le reste : un plafond non
    déclaré, c'est une réponse coupée à 4 096 sans avertissement."""
    from app.services.config_reality import check_config_reality
    from app.services.context_manager import set_instance_overrides

    set_instance_overrides()
    findings = await check_config_reality(
        models=["un-modele-sans-rien"], bound_tools=[], resolved_models={},
    )

    assert "model_output_cap" in {f.kind for f in findings}
