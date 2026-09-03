# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reality_check_resolver.py
# @brief      Contrôler ce que le système UTILISE, pas ce qu'il DÉCLARE.
# @license    MIT
# =============================================================================
"""Pins du contrôle de réalité côté résolveur.

**L'angle mort découvert le 26/07.** Le contrôle de #265 inspectait les
modèles déclarés dans ``llm_instances``. Or l'inventaire a montré que les
tiers *medium*, *complex* et *image* résolvaient vers **``gpt-5.5``** — un
modèle **absent de** ``llm_instances``, imposé par un chemin historique qui le
code en dur (``llm_provider.py`` : ``_make_openai_codex(model="gpt-5.5")``)
dès que la configuration référence le fournisseur par son NOM plutôt que par
l'identifiant d'une instance.

Conséquences réelles, mesurées : ``gpt-5.5`` n'avait aucun tarif, donc
``estimate_cost`` lui appliquait **4,00 USD par million** inventés — sur la
majorité du trafic — alors que l'instance réellement voulue,
``gpt-5.6-terra``, est consommée **au forfait** et coûte 0.

**La leçon de méthode**, et c'est elle qui compte : la bonne question n'est pas
« les modèles déclarés résolvent-ils ? » mais **« ce que le système utilise
réellement est-il connu de ses tables ? »**. Les deux divergent dès qu'un
chemin historique s'intercale — et c'est précisément là que se logent ces
défauts.

Run with:  cd backend && python -m pytest tests/test_reality_check_resolver.py -v
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_resolved_model_absent_from_the_tables_is_reported():
    """LE test du lot : c'est exactement le cas gpt-5.5."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(
        models=[], bound_tools=[],
        resolved_models={"medium": "gpt-4.9-fantome", "complex": "gpt-4.9-fantome"},
    )

    kinds = {f.kind for f in findings}
    assert "resolved_model_unknown" in kinds, (
        "un modèle réellement utilisé mais inconnu des tables passe encore "
        "inaperçu — c'est l'angle mort qui a laissé gpt-5.5 facturé 4 USD/M"
    )


@pytest.mark.asyncio
async def test_the_finding_names_the_tier_so_it_is_actionable():
    """« un modèle inconnu » ne dit pas quoi corriger ; « le tier complex
    utilise X » désigne l'écran de réglage à ouvrir."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(
        models=[], bound_tools=[], resolved_models={"complex": "gpt-4.9-fantome"},
    )
    resolved = [f for f in findings if f.kind == "resolved_model_unknown"]

    assert resolved
    assert "complex" in resolved[0].detail


@pytest.mark.asyncio
async def test_a_resolved_model_that_is_declared_and_priced_is_silent():
    """Pas de bruit sur la configuration saine — sinon le rapport cesse d'être
    lu, ce qui est très exactement ce qui est arrivé à l'avertissement
    « Unknown model »."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(
        models=[], bound_tools=[], resolved_models={"complex": "gpt-5.6-terra"},
    )

    assert findings == [], f"faux positifs : {findings}"


@pytest.mark.asyncio
async def test_a_model_used_but_never_declared_is_reported_even_if_priced():
    """Cas subtil : `gpt-5.5` avait une FENÊTRE (par le préfixe « gpt-5 »)
    mais aucun tarif, et n'était déclaré nulle part. Un modèle qu'aucune
    instance ne déclare doit se signaler même si les tables le couvrent — sinon
    on ignore qu'un chemin historique décide à la place de la configuration."""
    from app.services.config_reality import check_config_reality

    findings = await check_config_reality(
        models=["gpt-5.6-terra"], bound_tools=[],
        resolved_models={"complex": "gpt-5.5"},
    )

    subjects = {f.subject for f in findings}
    assert "gpt-5.5" in subjects


@pytest.mark.asyncio
async def test_the_resolver_probe_never_breaks_the_check():
    """Interroger le résolveur instancie des clients LLM. Si ça échoue — clé
    absente, serveur local éteint — le contrôle doit continuer, pas planter au
    démarrage d'Ely."""
    from app.services.config_reality import check_config_reality

    for bad in ({}, None, {"medium": ""}, {"medium": None}):
        out = await check_config_reality(models=[], bound_tools=[], resolved_models=bad)
        assert isinstance(out, list)


@pytest.mark.asyncio
async def test_without_argument_it_probes_the_real_tiers():
    """Sans argument, le contrôle interroge les vrais tiers — c'est ce qui
    tournera au démarrage."""
    from app.services.config_reality import check_config_reality

    out = await check_config_reality()

    assert isinstance(out, list)
