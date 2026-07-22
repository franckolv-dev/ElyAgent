# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tier_s.py
# @brief      Sprint 4b Phase 2 + Backlog #19 — Tier S provider chain
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Tier S — la voie LLM qui écrit les outils et les compétences d'Ely.

Utilisée par ``skill_creator``, ``skill_eval``, ``skill_iteration`` et
``tool_generator``. Elle garde son propre plafond mensuel, parce qu'une
itération de génération de code peut coûter cher et qu'on ne veut pas la
voir se mélanger aux caches de routage du tier C conversationnel.

Configuration — un niveau de routage comme les autres (22/07/2026)
------------------------------------------------------------------
La chaîne se règle dans **Paramètres → Routage**, niveau « S », exactement
comme les niveaux A/B/C/IMG/SYS : elle est lue depuis
``tier_routing_config`` via ``llm_provider.get_tier_config()``. Chaque
élément est soit un nom de provider, soit un UUID d'instance nommée — un
modèle local y est donc éligible au même titre qu'un provider cloud.

Pourquoi ce changement : jusqu'à cette date, tier S était la SEULE voie à
ne pas lire cette config. Sa chaîne (``anthropic,deepseek``) et son modèle
(``claude-opus-4-5``) étaient codés en dur, surchargeables uniquement par
des variables d'environnement non documentées, et invisibles dans
l'interface. Conséquence constatée en production : 62 appels facturés sur
Opus 4.5 alors que l'administrateur avait configuré Haiku, sans aucune
surface pour s'en apercevoir. ``LLM_TIER_S_CHAIN`` n'est plus lu ; s'il
subsiste dans l'environnement, un avertissement est journalisé une fois.

Un modèle local est un candidat sérieux ici : les prompts de génération
font ~1,7k tokens en entrée et il n'y a pas de boucle agentique — le
prompt-processing qui disqualifie le local sur les tiers B/C ne s'applique
pas à cette voie.

Reste piloté par l'environnement (orthogonal au routage) :
``LLM_TIER_S_MONTHLY_BUDGET_USD`` (défaut 50 $). Au-delà du plafond, le
PREMIER élément de la chaîne est sauté au profit du suivant — la voie
dégrade au lieu de s'arrêter.

La dépense est enregistrée dans ``usage_logs`` avec
``skill_used = "tier_s.<purpose>"``, sur la même surface d'audit que les
appels utilisateur. La remise à zéro du budget est implicite (somme sur le
mois calendaire courant).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.database import async_session

logger = logging.getLogger(__name__)


# ── Plafond mensuel (variable d'env, orthogonal au routage) ────────────────

DEFAULT_MONTHLY_BUDGET_USD = 50.0


# ── Rough cost table (USD per million tokens, input / output) ──────────────
# Numbers from official pricing pages at end-2025; admin can override the
# whole dict via the future settings UI if pricing shifts. Keys are
# prefixes so any "claude-opus-*" variant maps to the same rate.
_COST_PER_MTOKEN_USD: dict[str, tuple[float, float]] = {
    "claude-opus":       (15.00, 75.00),
    "claude-sonnet":     ( 3.00, 15.00),  # kept for completeness, not in default chain
    "mistral-large":     ( 2.00,  6.00),  # 7-12× cheaper than Opus — the budget argument
    "deepseek-reasoner": ( 0.55,  2.19),
    "deepseek-chat":     ( 0.27,  1.10),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of a tier-S call from token counts.

    Linear lookup against `_COST_PER_MTOKEN_USD` by model-name prefix.
    Returns 0.0 for unknown models — better to under-report than crash
    the budget guard.
    """
    model_lc = (model or "").lower()
    for prefix, (in_rate, out_rate) in _COST_PER_MTOKEN_USD.items():
        if prefix in model_lc:
            return round(
                (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0,
                6,
            )
    return 0.0


# ── Spending query ──────────────────────────────────────────────────────────


def _month_start(now: datetime | None = None) -> datetime:
    """First instant of the current calendar month, UTC. Pure helper for tests."""
    n = now or datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_monthly_spend_usd(now: datetime | None = None) -> float:
    """Sum cost_usd over the current month for tier_s.* skill_used rows."""
    from app.models.usage_log import UsageLog

    start = _month_start(now)
    try:
        async with async_session() as db:
            result = await db.execute(
                select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0)).where(
                    UsageLog.timestamp >= start,
                    UsageLog.skill_used.like("tier_s.%"),
                )
            )
            value = result.scalar_one()
            return float(value or 0.0)
    except Exception as exc:
        logger.debug("get_monthly_spend_usd failed (swallowed): %s", exc)
        return 0.0


def _budget_cap_usd() -> float:
    """Monthly cap from env. `<= 0` means no cap (allow forever)."""
    raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_USD")
    if raw is None:
        raw = os.getenv("LLM_TIER_S_MONTHLY_BUDGET_EUR")  # parity ≈ 1:1, either accepted
    try:
        return float(raw) if raw is not None else DEFAULT_MONTHLY_BUDGET_USD
    except ValueError:
        logger.warning(
            "tier_s: invalid LLM_TIER_S_MONTHLY_BUDGET_USD=%r — using default %s",
            raw, DEFAULT_MONTHLY_BUDGET_USD,
        )
        return DEFAULT_MONTHLY_BUDGET_USD


async def is_primary_within_budget() -> bool:
    """True if monthly tier-S spend is still below the cap.

    Treats cap `<= 0` as "disabled" (always allow primary).

    Naming kept for backwards compat (Phase 2 callers + tests). The
    semantics are now : "are we allowed to attempt the first provider
    in the chain, or should we skip straight to the fallback(s)?".
    """
    cap = _budget_cap_usd()
    if cap <= 0:
        return True
    return (await get_monthly_spend_usd()) < cap


# ── Usage recording ─────────────────────────────────────────────────────────


async def record_tier_s_usage(
    *,
    user_id: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    purpose: str,
    conversation_id: str | None = None,
) -> str | None:
    """Persist one tier-S call in `usage_logs`.

    `purpose` is appended to `"tier_s."` to form the `skill_used`
    discriminator (e.g. `"tier_s.skill_creator"`).

    Never raises — best-effort accounting. Returns the new row id or None.
    """
    if not user_id:
        return None
    try:
        from app.models.usage_log import UsageLog

        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        row = UsageLog(
            user_id=user_id,
            model=model,
            provider=provider,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(input_tokens + output_tokens),
            cost_usd=cost,
            skill_used=f"tier_s.{purpose}",
            conversation_id=conversation_id,
            channel="tier_s",
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.debug("record_tier_s_usage failed (swallowed): %s", exc)
        return None


# Type alias for callers — the pick is now the canonical provider name
# (or "none"). Phase 2 callers checked `pick == "none"` only — that
# contract is preserved.
TierSPick = str


_SKILL_TIER = "skill"
_DEPRECATED_CHAIN_ENV = "LLM_TIER_S_CHAIN"
_env_chain_warned = False


def _skill_tier_chain() -> tuple[list[str], bool]:
    """Chaîne du niveau « skill » telle que configurée par l'admin.

    SOURCE DE VÉRITÉ UNIQUE : la config de routage (onglet Routage →
    ``tier_routing_config``), la même que les niveaux A/B/C/IMG/SYS. Les
    éléments sont soit des noms de provider, soit des UUID d'instances
    nommées — un modèle local y est donc éligible comme n'importe quel
    provider cloud.

    ``LLM_TIER_S_CHAIN`` n'est plus lu (incident du 22/07/2026 : une chaîne
    hors UI facturait Opus 4.5 à l'insu de l'admin). S'il traîne encore dans
    l'environnement, on le signale une fois — silencieusement l'ignorer
    recréerait exactement l'écart entre « ce qui est affiché » et « ce qui
    tourne » que ce chantier corrige.
    """
    global _env_chain_warned
    if not _env_chain_warned and os.getenv(_DEPRECATED_CHAIN_ENV):
        _env_chain_warned = True
        logger.warning(
            "tier_s: %s est DÉPRÉCIÉ et IGNORÉ — le niveau S se configure "
            "désormais dans Paramètres → Routage. Retire la ligne du .env "
            "pour éviter toute confusion.",
            _DEPRECATED_CHAIN_ENV,
        )

    from app.services.llm_provider import DEFAULT_TIER_CONFIG, get_tier_config

    default = DEFAULT_TIER_CONFIG[_SKILL_TIER]
    try:
        entry = get_tier_config().get(_SKILL_TIER)
    except Exception as exc:  # noqa: BLE001 — jamais casser la génération
        logger.warning("tier_s: lecture de la config de niveau échouée (%s)", exc)
        entry = None
    # Une config sauvegardée avant ce chantier n'a pas la clé `skill`.
    if not entry:
        entry = default
    return list(entry.get("providers") or []), bool(entry.get("fallback_enabled", True))


def _build_chain_item(provider_id: str) -> Any | None:
    """Construit un élément de chaîne — nom de provider OU UUID d'instance.

    Délègue à ``build_llm_for_provider``, le même point d'entrée que les
    autres niveaux : tier S hérite ainsi automatiquement des instances
    nommées, du déchiffrement des clés et de la gestion des providers.
    ``ComplexityTier.COMPLEX`` donne les hyperparamètres adaptés à de la
    génération de code (température basse, 8192 tokens de sortie).
    """
    try:
        from app.services.llm_provider import ComplexityTier, build_llm_for_provider

        return build_llm_for_provider(provider_id, ComplexityTier.COMPLEX)
    except Exception as exc:  # noqa: BLE001 — un provider cassé n'arrête pas la chaîne
        logger.warning("tier_s: construction de %r impossible (%s)", provider_id, exc)
        return None


async def get_tier_s_llm(*, force_fallback: bool = False) -> tuple[Any | None, TierSPick]:
    """Iterate the configured provider chain and return `(llm, pick)`.

    Returns the FIRST chain item whose builder succeeds AND whose
    selection respects the budget cap. The `pick` string is the
    canonical provider name (or `"none"` if nothing was buildable).

    `force_fallback=True` skips the FIRST item in the chain — useful
    when a caller wants to deliberately avoid the most-expensive
    provider (e.g. eval loop's deterministic re-runs).

    Budget rule (Phase 2 contract preserved): if the monthly spend is
    over the cap, the first chain item is skipped. Subsequent items
    are still attempted. This means a chain of `mistral,deepseek` with
    Mistral as the "primary" gets degraded to DeepSeek when budget
    runs out — not to nothing.
    """
    chain, fallback_enabled = _skill_tier_chain()
    if not chain:
        logger.warning("tier_s: empty provider chain — nothing to attempt")
        return None, "none"

    within_budget = await is_primary_within_budget()
    skip_first = force_fallback or not within_budget

    for i, name in enumerate(chain):
        if i == 0 and skip_first and len(chain) > 1:
            # Skip the first provider — caller asked for fallback OR
            # the budget is exhausted for the primary. Single-item
            # chain has no alternative, so we don't skip.
            continue
        llm = _build_chain_item(name)
        if llm is not None:
            return llm, name
        if not fallback_enabled:
            # L'admin a explicitement coupé le repli sur ce niveau : on ne
            # tente PAS l'élément suivant, même s'il est constructible.
            logger.info(
                "tier_s: %s unavailable and fallback disabled — stopping", name
            )
            return None, "none"
    logger.info("tier_s: every provider in chain %s is unavailable", chain)
    return None, "none"
