# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/config_reality.py
# @brief      Confronte la configuration DÉCLARÉE aux valeurs RÉELLEMENT
#             présentes, et signale tout ce qui tombe dans un repli.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Contrôle de réalité de la configuration.

**Le défaut qu'il chasse.** Le 26/07/2026, ``get_context_window()`` renvoyait
8 192 tokens pour **tous** les modèles : la table ne connaissait que
``gemma4:26b``, ``gpt-4o``, ``claude-sonnet-4-6``, dont Ely ne fait tourner
aucun. Elle tronquait donc son contexte à 8 K en permanence — sans erreur,
sans test rouge, pendant des mois.

**La signature de la classe**, pour la reconnaître ailleurs : une
correspondance qui reçoit une clé produite ailleurs dans le système, possède
un repli pour les clés inconnues, et dont ce repli est *plausible* plutôt que
manifestement cassé. Personne ne vérifie jamais que les clés RÉELLES tombent
dans la table.

**Le principe de ce module.** Prendre ce qui est réellement configuré — les
instances LLM de la base, les outils bindés au profil — et le passer dans les
mêmes lectures que le code de production. Ce qui atterrit sur un repli est un
constat.

⚠️ **Chaque contrôle reproduit la sémantique EXACTE de la lecture qu'il
vérifie** : la fenêtre de contexte se résout par préfixe
(``model.startswith(key)``), la tarification par **égalité stricte**
(``_PRICING.get(model, …)``). Un contrôle plus permissif que le code réel
mentirait à son tour, et c'est précisément le piège qu'on essaie de sortir.

Ce module ne mesure aucune performance : un banc d'essai n'aurait trouvé aucun
de ces défauts — il aurait dit « c'est lent », jamais « la table renvoie
8 192 ». Les deux sont complémentaires, mais celui-ci vient d'abord, sinon le
banc grave la panne dans sa référence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Finding:
    """Un constat : ce qui est tombé dans un repli, et ce que ça coûte."""

    kind: str      # model_window | model_pricing | bound_tool_missing
    subject: str   # la valeur réelle qui n'a pas résolu
    detail: str    # la conséquence, en clair — pas juste « absent »

    def __str__(self) -> str:  # pragma: no cover — confort de journal
        return f"[{self.kind}] {self.subject} — {self.detail}"


async def _configured_models() -> list[str]:
    """Les modèles RÉELLEMENT déclarés en base.

    C'est là que se produit la dérive : Franck ajoute une instance depuis
    l'interface, et aucune table statique du code ne l'apprend jamais.
    """
    try:
        from sqlalchemy import text

        from app.database import async_session

        async with async_session() as db:
            rows = await db.execute(text("SELECT DISTINCT model FROM llm_instances"))
            return [r[0] for r in rows.all() if r[0]]
    except Exception as exc:  # noqa: BLE001 — un diagnostic ne bloque rien
        logger.debug("instances LLM illisibles (%s)", exc)
        return []


def _check_model_window(model: str) -> Finding | None:
    """Reproduit ``get_context_window`` : résolution par PRÉFIXE, repli
    ``_default``."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    default = _CONTEXT_WINDOWS["_default"]
    if get_context_window(model) != default:
        return None
    return Finding(
        kind="model_window",
        subject=model,
        detail=(
            f"aucune fenêtre déclarée — le contexte sera tronqué à {default} "
            f"tokens quelle que soit la fenêtre réelle du modèle, et les "
            f"messages les plus anciens seront jetés bien trop tôt"
        ),
    )


def _check_model_pricing(model: str) -> Finding | None:
    """Reproduit ``estimate_cost`` : ``_PRICING.get(model, …)``, donc égalité
    STRICTE — un préfixe ne suffit pas ici, contrairement à la fenêtre."""
    from app.services.analytics_service import _PRICING

    if model in _PRICING:
        return None
    return Finding(
        kind="model_pricing",
        subject=model,
        detail=(
            "aucun tarif déclaré — le coût affiché à l'utilisateur est calculé "
            "sur un tarif générique inventé, donc faux pour ce modèle"
        ),
    )


def _check_bound_tool(name: str, catalog: set[str]) -> Finding | None:
    """Leçon de #257 : un nom bindé au profil mais absent du catalogue ne lève
    rien. L'agent ne voit jamais l'outil et affirme honnêtement ne pas
    l'avoir."""
    if name in catalog:
        return None
    return Finding(
        kind="bound_tool_missing",
        subject=name,
        detail=(
            "bindé au profil mais absent du catalogue — l'agent ne le verra "
            "jamais et dira de bonne foi qu'il n'a pas cet outil"
        ),
    )


def _tool_catalog() -> set[str]:
    try:
        from app.skills import get_skill_registry
        from app.skills.builtin import register_all

        register_all()
        return {t.name for t in get_skill_registry().all_tools}
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalogue d'outils illisible (%s)", exc)
        return set()


async def _resolved_models() -> dict[str, str]:
    """Le modèle que CHAQUE TIER produit réellement, tier par tier.

    Différent de ``_configured_models`` : celui-ci lit ce qui est *déclaré*,
    celui-là ce qui est *utilisé*. Les deux ont divergé le 26/07 — les tiers
    medium/complex/image résolvaient vers ``gpt-5.5``, absent de
    ``llm_instances``, parce qu'une entrée référençait le fournisseur par son
    NOM et empruntait un chemin historique qui code le modèle en dur.

    Instancie des clients LLM (aucun appel réseau). Toute défaillance — clé
    absente, serveur local éteint — dégrade en silence : un diagnostic ne doit
    pas empêcher Ely de démarrer.
    """
    out: dict[str, str] = {}
    try:
        from app.services.llm_provider import (
            ComplexityTier, describe_llm, get_llm_for_tier,
            load_llm_settings_from_db,
        )

        await load_llm_settings_from_db()
        for tier in ComplexityTier:
            try:
                _provider, model = describe_llm(get_llm_for_tier(tier))
                if model:
                    out[tier.value] = model
            except Exception as exc:  # noqa: BLE001
                logger.debug("tier %s non résolu (%s)", tier, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("sonde du résolveur indisponible (%s)", exc)
    return out


def _check_resolved_model(
    tier: str, model: str, declared: set[str],
) -> list[Finding]:
    """Un modèle réellement utilisé doit être connu des tables ET déclaré.

    Le second point compte autant que le premier : ``gpt-5.5`` avait une
    fenêtre (par le préfixe « gpt-5 ») mais n'était déclaré par aucune
    instance. Un modèle que la configuration n'a jamais demandé signale qu'un
    chemin historique décide à la place de l'utilisateur.
    """
    found: list[Finding] = []
    if not model:
        return found

    window = _check_model_window(model)
    price = _check_model_pricing(model)
    for f in (window, price):
        if f is not None:
            found.append(Finding(
                kind="resolved_model_unknown",
                subject=model,
                detail=f"utilisé par le tier « {tier} » — {f.detail}",
            ))

    if declared and model not in declared:
        found.append(Finding(
            kind="resolved_model_unknown",
            subject=model,
            detail=(
                f"utilisé par le tier « {tier} » mais déclaré par AUCUNE "
                f"instance — un chemin historique impose ce modèle à la place "
                f"de ce qui est configuré"
            ),
        ))
    return found


async def check_config_reality(
    models: list[str] | None = None,
    bound_tools: list[str] | None = None,
    resolved_models: dict[str, str] | None = None,
) -> list[Finding]:
    """Retourne tout ce qui, dans la configuration réelle, tombe dans un repli.

    Sans argument, inspecte ce qui est effectivement configuré : les modèles
    de ``llm_instances`` et les outils du profil ``default``.

    Ne lève jamais — un instrument de diagnostic ne doit pas empêcher Ely de
    démarrer. Une liste vide signifie « rien à signaler », pas « pas vérifié » :
    les erreurs internes sont journalisées en debug.
    """
    findings: list[Finding] = []

    try:
        names = await _configured_models() if models is None else list(models)
    except Exception:  # noqa: BLE001
        names = []

    for model in [m for m in (names or []) if m]:
        for check in (_check_model_window, _check_model_pricing):
            try:
                found = check(model)
            except Exception as exc:  # noqa: BLE001
                logger.debug("contrôle %s échoué sur %s (%s)", check.__name__, model, exc)
                continue
            if found is not None:
                findings.append(found)

    try:
        if bound_tools is None:
            from app.agent.toolset_profiles import _DEFAULT_TOOLS

            bound_tools = sorted(_DEFAULT_TOOLS)
        catalog = _tool_catalog()
        # Un catalogue vide signifierait « rien n'existe » et produirait un
        # constat par outil : mieux vaut ne rien dire que crier faux.
        if catalog:
            for name in bound_tools:
                found = _check_bound_tool(name, catalog)
                if found is not None:
                    findings.append(found)
    except Exception as exc:  # noqa: BLE001
        logger.debug("contrôle des outils bindés échoué (%s)", exc)

    # Ce que le système UTILISE, et pas seulement ce qu'il déclare. C'est
    # l'angle mort qui a laissé gpt-5.5 facturé 4 USD/M sur la majorité du
    # trafic pendant que l'instance voulue, au forfait, coûtait 0.
    try:
        used = await _resolved_models() if resolved_models is None else resolved_models
        declared = {m for m in (names or []) if m}
        for tier, model in (used or {}).items():
            findings.extend(_check_resolved_model(tier, model or "", declared))
    except Exception as exc:  # noqa: BLE001
        logger.debug("contrôle du résolveur échoué (%s)", exc)

    return findings


async def log_config_reality() -> int:
    """Lance le contrôle et journalise chaque constat. Retourne leur nombre.

    Volontairement en ``warning`` : c'est exactement le niveau qu'avait
    l'avertissement « Unknown model » que personne n'a jamais lu. La différence
    tient à ce qui est écrit — un constat qui énonce sa conséquence se
    remarque, un nom de modèle seul se noie.
    """
    findings = await check_config_reality()
    if not findings:
        logger.info("Contrôle de réalité de la configuration : rien à signaler")
        return 0

    logger.warning(
        "Contrôle de réalité : %d valeur(s) de configuration tombent dans un "
        "repli — voir le détail ci-dessous", len(findings),
    )
    for f in findings:
        logger.warning("  %s", f)
    return len(findings)
