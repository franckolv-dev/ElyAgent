# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_escalation_panel.py
# @brief      Quand ça n'avance plus, Ely demande à plusieurs modèles au lieu
#             d'abandonner — et te dit lequel a répondu, et ce que ça a coûté.
# @license    Elastic License 2.0
# =============================================================================
"""Lot 2 du plan de marche — la chaîne de repli devient un panel.

Ce que Franck a demandé, le 28/07/2026
---------------------------------------
    « On a utilisé les fallback au cas où un modèle n'est plus disponible, il
      faut modifier cette approche et les utiliser également si les résultats
      ne sont pas convenables […] demander à 2 ou 3 modèles simultanément,
      prendre le meilleur retour et me le proposer. »

Mesuré : les huit déclencheurs de repli existants sont **tous techniques**
(``rate_limit``, ``timeout``, ``billing``, ``unavailable``…). Aucun ne regarde
la QUALITÉ. Un modèle qui répond vite et mal ne déclenche rien.

Le déclencheur : le progrès, pas un compteur
---------------------------------------------
Franck avait proposé « après 3 tentatives ». On a mesuré en #289 que le
compteur fixe était mauvais et on l'a remplacé par le progrès. Le panel se
branche donc exactement là où #289 constate que ça n'avance plus : aujourd'hui
la boucle ABANDONNE et rédige un constat d'échec, demain elle ESCALADE. C'est
mieux qu'un compteur dans les deux sens — plus tôt quand c'est bloqué, jamais
quand ça progresse.

⚠️ Ce que le panel peut, et ce qu'il ne peut pas
-------------------------------------------------
Les modèles du panel répondent **sans outils**. Ils améliorent donc une
RÉPONSE, pas le RÉSULTAT d'un outil : sur « la conversion a aplati les pages »,
aucun d'eux ne peut reconvertir le PDF. C'est délibéré — trois agents outillés
en parallèle enverraient trois mails et écriraient trois fichiers. Le panel est
en lecture seule par construction, et c'est ce qui le rend sûr.

Budget — décision de Franck
----------------------------
    « Si le modèle est de type forfait (GPT 5.6), pas de plafond et si c'est
      via API, on établira un plafond par demande et qu'Ely me le dise. »

Le tarif ``(0.0, 0.0)`` d'``analytics_service._PRICING`` identifie déjà les
modèles au forfait et les locaux. Un modèle facturé n'entre au panel que si le
plafond de la demande le permet — et ce qui a été écarté est DIT.

Run with:  cd backend && python -m pytest tests/test_escalation_panel.py -v
"""
from __future__ import annotations

import pytest


class _Model:
    """Un faux modèle qui rend une réponse fixe et note ce qu'on lui envoie."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, payload, **kwargs):
        self.prompts.append(payload[0].content if isinstance(payload, list) else str(payload))

        class _R:
            content = self.reply

        return _R()


@pytest.fixture
def panel(monkeypatch):
    """Trois modèles distincts, chacun identifiable par sa réponse."""
    models = {
        "id-a": _Model("Réponse de A"),
        "id-b": _Model("Réponse de B"),
        "id-c": _Model("Réponse de C"),
    }
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": list(models), "fallback_enabled": True}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance",
        lambda iid, **kw: models.get(iid),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: "modèle-test",
    )
    return models


# ─────────────────────────────────────────────────────────────────────
# Le panel interroge plusieurs modèles, en parallèle
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_several_distinct_models_are_asked(panel):
    """Interroger deux fois le même modèle ne vaut pas un panel : c'est la
    DIVERSITÉ qui donne une chance d'obtenir mieux."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis ce texte en néerlandais.",
        produit="[résultat d'outil] traduction en anglais",
        ecarts="- la langue demandée était le néerlandais",
    )

    interroges = [m for m in panel.values() if m.prompts]
    assert len(interroges) >= 2, f"{len(interroges)} modèle(s) interrogé(s)"


@pytest.mark.asyncio
async def test_the_panel_receives_the_gaps_not_just_the_request(panel):
    """Sans les écarts, les modèles referaient la même erreur : c'est
    précisément ce que la reprise a déjà tenté sans succès."""
    from app.agent.escalation import escalate_to_panel

    await escalate_to_panel(
        demande="Traduis ce texte en néerlandais.",
        produit="traduction en anglais",
        ecarts="- la langue demandée était le néerlandais",
    )

    prompt = next(m.prompts[0] for m in panel.values() if m.prompts)
    assert "néerlandais" in prompt
    assert "la langue demandée" in prompt


@pytest.mark.asyncio
async def test_the_best_answer_is_returned_with_its_author(panel):
    """« Prendre le meilleur retour et me le proposer » — et savoir d'où il
    vient, sinon Franck ne peut ni arbitrer ni corriger."""
    from app.agent.escalation import escalate_to_panel

    result = await escalate_to_panel(
        demande="Traduis en néerlandais.", produit="anglais", ecarts="- langue",
    )

    assert result is not None
    assert result.answer.startswith("Réponse de")
    assert result.model, "la réponse ne dit pas quel modèle l'a produite"


# ─────────────────────────────────────────────────────────────────────
# Échouer OUVERT — une escalade cassée ne retient rien
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_panel_that_fails_returns_nothing_rather_than_blocking(monkeypatch):
    """Même règle que la boucle de conformité : l'utilisateur reçoit la réponse
    d'origine plutôt qu'une erreur. Une amélioration qui tombe ne doit jamais
    coûter le résultat déjà obtenu."""
    class _Broken:
        async def ainvoke(self, payload, **kwargs):
            raise RuntimeError("quota épuisé")

    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": ["a", "b"]}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance", lambda iid, **kw: _Broken(),
    )
    from app.agent.escalation import escalate_to_panel

    assert await escalate_to_panel(demande="x", produit="y", ecarts="- z") is None


@pytest.mark.asyncio
async def test_a_single_available_model_is_not_a_panel(monkeypatch):
    """Un seul modèle disponible, c'est ce que la reprise vient déjà de faire.
    Le refaire coûterait un appel pour rien."""
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"complex": {"providers": ["seul"]}},
    )
    monkeypatch.setattr(
        "app.services.llm_provider._make_llm_for_instance",
        lambda iid, **kw: _Model("Réponse unique"),
    )
    from app.agent.escalation import escalate_to_panel

    assert await escalate_to_panel(demande="x", produit="y", ecarts="- z") is None


# ─────────────────────────────────────────────────────────────────────
# Le budget — décision de Franck du 28/07
# ─────────────────────────────────────────────────────────────────────


def test_the_real_describe_llm_yields_a_usable_model_name():
    """⚠️ Le doublon anti-stub, et il a servi.

    Les pins ci-dessus stubbent ``describe_llm`` par ``lambda llm: "modèle"``.
    La VRAIE fonction rend un **tuple** ``(provider, model)`` : ``_model_name``
    rendait donc un tuple, ``is_flat_rate`` recevait un tuple, ``_PRICING.get``
    répondait ``None``, et **tous les modèles au forfait passaient pour
    facturés** — le plafond de budget les aurait écartés du panel, donc aucun
    panel n'aurait jamais eu lieu en production.

    Aucun test stubbé ne pouvait le voir. C'est la leçon de #288, à appliquer
    chaque fois qu'un test stubbe une fonction partagée : en doubler un qui
    appelle la vraie.
    """
    from app.agent.escalation import _model_name
    from app.services.llm_provider import describe_llm

    class _Fake:
        model = "gpt-5.6-terra"

    assert isinstance(describe_llm(_Fake()), tuple), "le contrat a changé"
    name = _model_name(_Fake(), "repli")
    assert isinstance(name, str), f"_model_name rend {type(name).__name__}"
    assert name == "gpt-5.6-terra"


def test_a_flat_rate_model_name_survives_the_real_pipeline():
    """Le bout de la chaîne : ce que ``_model_name`` produit doit être
    reconnaissable par ``is_flat_rate``, sinon le budget se trompe en silence."""
    from app.agent.escalation import _model_name, is_flat_rate

    class _Fake:
        model = "gpt-5.6-terra"

    assert is_flat_rate(_model_name(_Fake(), "repli")) is True


def test_a_flat_rate_model_has_no_ceiling():
    """« Si le modèle est de type forfait (GPT 5.6), pas de plafond. »
    Le tarif (0.0, 0.0) l'identifie déjà dans ``_PRICING``."""
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("gpt-5.6-terra") is True
    assert is_flat_rate("qwen/qwen3.5-9b") is True


def test_a_metered_model_is_not_flat_rate():
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("deepseek-v4-pro") is False


def test_an_unknown_model_is_treated_as_metered():
    """Prudence sur l'argent : un modèle dont on ignore le tarif est supposé
    facturé. Se tromper dans l'autre sens ferait payer sans plafond."""
    from app.agent.escalation import is_flat_rate

    assert is_flat_rate("modele-jamais-vu") is False


@pytest.mark.asyncio
async def test_what_the_escalation_cost_is_reported(panel):
    """« Qu'Ely me le dise. » Une escalade muette sur son coût empêche
    d'arbitrer si elle vaut ce qu'elle rapporte."""
    from app.agent.escalation import escalate_to_panel

    result = await escalate_to_panel(demande="x", produit="y", ecarts="- z")

    assert result is not None
    assert result.models_asked >= 2
    assert result.cost_usd >= 0.0


# ─────────────────────────────────────────────────────────────────────
# Le déclencheur — le progrès, jamais un compteur
# ─────────────────────────────────────────────────────────────────────


def test_the_panel_is_convened_only_when_progress_stops():
    """Le garde-fou de la facture. Un tour qui progresse (6 écarts → 2 → 1) se
    règle tout seul : convoquer le panel à chaque reprise multiplierait le coût
    de toutes les demandes qui allaient très bien."""
    from app.agent.escalation import should_escalate

    assert should_escalate(new_count=3, previous_count=3) is True   # bloqué
    assert should_escalate(new_count=5, previous_count=3) is True   # empiré
    assert should_escalate(new_count=1, previous_count=3) is False  # progresse
    assert should_escalate(new_count=2, previous_count=0) is False  # 1re vérification
