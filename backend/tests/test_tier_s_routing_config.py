# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tier_s_routing_config.py
# @brief      Tier S lit la config de routage admin (onglet Routage), plus
#             une chaîne codée en dur.
# =============================================================================
"""Tier S devient un niveau de routage comme les autres.

Constat du 22/07/2026 : tier S — la voie qui génère les outils et les
compétences — était la SEULE à ne pas lire ``llm_instances``. Sa chaîne
(``anthropic,deepseek``) et son modèle (``claude-opus-4-5``) étaient codés en
dur, surchargeables uniquement par des variables d'environnement non
documentées, et invisibles dans l'interface. Résultat : Opus 4.5 facturé sur
la clé Anthropic de l'admin, sans qu'il l'ait choisi ni pu le voir.

Ce que ces tests verrouillent : ce que l'admin voit dans l'onglet Routage
est ce qui tourne. Y compris un modèle local — un Qwen coder en LM Studio
est un candidat sérieux pour cette voie, dont les prompts sont courts
(~1,7k tokens en entrée) contrairement aux tiers agentiques.
"""
from __future__ import annotations

import pytest

from app.services.learning.tier_s import get_tier_s_llm
from app.services.llm_provider import DEFAULT_TIER_CONFIG

_A, _B, _C = object(), object(), object()


@pytest.fixture
def built(monkeypatch):
    """Enregistre les ids demandés à ``build_llm_for_provider`` et renvoie
    un LLM factice pour ceux qu'on déclare constructibles."""
    calls: list[str] = []
    buildable: dict[str, object] = {}

    def _fake_build(provider_id, tier=None):
        calls.append(provider_id)
        return buildable.get(provider_id)

    monkeypatch.setattr(
        "app.services.llm_provider.build_llm_for_provider", _fake_build
    )
    return {"calls": calls, "buildable": buildable}


@pytest.fixture
def tier_cfg(monkeypatch):
    """Installe une config de niveau ``skill`` arbitraire."""
    def _set(providers, fallback_enabled=True):
        monkeypatch.setattr(
            "app.services.llm_provider.get_tier_config",
            lambda: {
                "skill": {
                    "providers": providers,
                    "fallback_enabled": fallback_enabled,
                }
            },
        )

    return _set


@pytest.fixture(autouse=True)
def _budget_ok(monkeypatch):
    monkeypatch.setenv("LLM_TIER_S_MONTHLY_BUDGET_USD", "0")  # 0 = pas de plafond
    monkeypatch.delenv("LLM_TIER_S_CHAIN", raising=False)


# ── Le niveau existe et n'est plus Opus par défaut ───────────────────────────
def test_skill_tier_exists_in_default_config():
    assert "skill" in DEFAULT_TIER_CONFIG


def test_default_skill_tier_is_not_anthropic():
    """Non-régression de l'incident : le défaut ne doit plus facturer Opus."""
    assert "anthropic" not in DEFAULT_TIER_CONFIG["skill"]["providers"]


# ── La config admin pilote réellement le choix ───────────────────────────────
@pytest.mark.asyncio
async def test_uses_the_configured_chain(tier_cfg, built):
    tier_cfg(["mistral", "deepseek"])
    built["buildable"]["mistral"] = _A

    llm, pick = await get_tier_s_llm()

    assert llm is _A
    assert pick == "mistral"


@pytest.mark.asyncio
async def test_falls_through_to_the_next_item(tier_cfg, built):
    tier_cfg(["mistral", "deepseek"])
    built["buildable"]["deepseek"] = _B  # mistral non constructible

    llm, pick = await get_tier_s_llm()

    assert llm is _B
    assert pick == "deepseek"
    assert built["calls"] == ["mistral", "deepseek"]


@pytest.mark.asyncio
async def test_an_instance_uuid_is_routable(tier_cfg, built):
    """Une instance nommée (ex. un Qwen coder local) doit être sélectionnable
    exactement comme un provider — c'est tout l'intérêt du chantier."""
    uuid = "3f1c2b7e-0000-4000-8000-000000000042"
    tier_cfg([uuid])
    built["buildable"][uuid] = _C

    llm, pick = await get_tier_s_llm()

    assert llm is _C
    assert pick == uuid


@pytest.mark.asyncio
async def test_fallback_disabled_tries_only_the_first(tier_cfg, built):
    tier_cfg(["mistral", "deepseek"], fallback_enabled=False)
    built["buildable"]["deepseek"] = _B  # constructible mais hors chaîne

    llm, pick = await get_tier_s_llm()

    assert llm is None
    assert pick == "none"
    assert built["calls"] == ["mistral"]


@pytest.mark.asyncio
async def test_nothing_buildable_returns_none(tier_cfg, built):
    tier_cfg(["mistral", "deepseek"])

    llm, pick = await get_tier_s_llm()

    assert llm is None
    assert pick == "none"


# ── Règles historiques préservées ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_force_fallback_skips_the_first(tier_cfg, built):
    tier_cfg(["mistral", "deepseek"])
    built["buildable"]["mistral"] = _A
    built["buildable"]["deepseek"] = _B

    llm, pick = await get_tier_s_llm(force_fallback=True)

    assert llm is _B
    assert built["calls"] == ["deepseek"]


@pytest.mark.asyncio
async def test_force_fallback_on_single_item_chain_still_tries_it(tier_cfg, built):
    """Une chaîne à un seul élément n'a pas d'alternative — on ne saute pas."""
    tier_cfg(["deepseek"])
    built["buildable"]["deepseek"] = _B

    llm, pick = await get_tier_s_llm(force_fallback=True)

    assert llm is _B


@pytest.mark.asyncio
async def test_empty_chain_returns_none(tier_cfg, built):
    tier_cfg([])

    llm, pick = await get_tier_s_llm()

    assert llm is None
    assert pick == "none"


@pytest.mark.asyncio
async def test_missing_skill_entry_falls_back_to_default(monkeypatch, built):
    """Une config sauvegardée AVANT ce chantier n'a pas de clé ``skill`` :
    on retombe sur le défaut au lieu de ne rien router."""
    monkeypatch.setattr(
        "app.services.llm_provider.get_tier_config",
        lambda: {"medium": {"providers": ["deepseek"], "fallback_enabled": True}},
    )
    for prov in DEFAULT_TIER_CONFIG["skill"]["providers"]:
        built["buildable"][prov] = _A

    llm, pick = await get_tier_s_llm()

    assert llm is _A
    assert pick == DEFAULT_TIER_CONFIG["skill"]["providers"][0]
