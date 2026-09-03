# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/config_reality.py
# @brief      Confronte la configuration DÉCLARÉE aux valeurs RÉELLEMENT
#             présentes, et signale tout ce qui tombe dans un repli.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
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
    from app.services.context_manager import instance_price

    # Le tarif porté par l'instance compte autant que celui de la table : dès
    # que l'utilisateur a fait le geste, le contrôle doit se taire. Un
    # diagnostic qui réclame ce qui est déjà réglé cesse d'être lu.
    if instance_price(model) is not None or model in _PRICING:
        return None
    return Finding(
        kind="model_pricing",
        subject=model,
        detail=(
            "aucun tarif déclaré — le coût affiché à l'utilisateur est calculé "
            "sur un tarif générique inventé, donc faux pour ce modèle. "
            "Renseigne-le sur l'instance, dans Paramètres → Modèles IA"
        ),
    )


def _check_model_output_cap(model: str) -> Finding | None:
    """Un plafond de sortie non déclaré, c'est une réponse coupée à 4 096
    tokens sans avertissement — le modèle en autorise souvent seize fois plus."""
    from app.services.context_manager import instance_max_output

    if instance_max_output(model) is not None:
        return None
    return Finding(
        kind="model_output_cap",
        subject=model,
        detail=(
            "aucun plafond de sortie déclaré — les réponses seront coupées à "
            "4 096 tokens en silence, quand ce modèle en autorise souvent bien "
            "davantage. Renseigne-le sur l'instance, dans Paramètres → Modèles IA"
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


async def _primary_models() -> dict[str, str]:
    """Le modèle du fournisseur de RANG 1 de chaque tier, sans rien instancier.

    Lu depuis ``_instance_cache``, pas construit : construire exigerait la clé,
    et c'est justement son absence qu'on cherche à révéler.
    """
    out: dict[str, str] = {}
    try:
        from app.services.llm_provider import (
            _instance_cache, get_tier_config, load_llm_settings_from_db,
        )

        await load_llm_settings_from_db()
        for tier, cfg in (get_tier_config() or {}).items():
            providers = list((cfg or {}).get("providers") or [])
            if not providers:
                continue
            inst = _instance_cache.get(providers[0])
            model = (inst or {}).get("model") or ""
            if model:
                out[str(tier)] = str(model)
    except Exception as exc:  # noqa: BLE001 — un diagnostic ne casse rien
        logger.debug("rangs 1 illisibles (%s)", exc)
    return out


def _check_tier_uses_primary(
    tier: str, resolved: str, primary: str,
) -> Finding | None:
    """Le tier sert-il le fournisseur choisi, ou un repli de sa chaîne ?

    **Le trou que ce contrôle bouche.** ``_check_resolved_model`` vérifie que
    le modèle servi est *connu des tables* et *déclaré par une instance*. Un
    rang 2 de la même chaîne satisfait les deux : il est parfaitement déclaré.
    Le tier pouvait donc servir son repli en permanence sans qu'aucun constat
    ne soit émis.

    **L'incident, 28/07 → 05/08.** Le tier ``complex`` a servi DeepSeek v4 Pro
    (rang 2) pendant neuf jours : 994 requêtes, 42 M tokens, ~14 $. Les tokens
    par requête — ~42 500, le poids d'un tour agentique complet — disaient que
    ce modèle ne donnait pas un second avis : il FAISAIT le travail. La table
    ``provider_switches`` ne portait qu'UNE bascule sur ``complex`` pour la
    période, parce que la cascade de CONSTRUCTION (``get_llm_for_tier``) ne
    passe pas par ``fallback_manager`` : pas de ligne, pas de toast, rien.

    C'est l'invariant « un repli doit se voir » pris en défaut sur le chemin le
    plus cher du système.
    """
    if not resolved or not primary or resolved == primary:
        return None
    return Finding(
        kind="tier_serves_fallback",
        subject=tier,
        detail=(
            f"le tier « {tier} » sert « {resolved} » alors que son rang 1 est "
            f"« {primary} » — le rang 1 n'a pas pu être construit (clé absente, "
            f"instance hors cache) et la cascade l'a écarté SANS enregistrer de "
            f"bascule : ce repli est facturé et invisible"
        ),
    )


def check_unguarded_engaging_tools(
    unguarded: list[str] | None = None,
) -> list[Finding]:
    """Les actes engageants qu'aucune autorisation ne protège.

    Depuis le lot 3 (28/07/2026) la liste est **vide**, et c'est le résultat
    voulu : les 18 actes engageants qui n'étaient soumis à rien sont soit sous
    autorisation, soit explicitement dispensés avec leur raison. Ce contrôle
    n'existe plus que pour attraper la prochaine régression — un outil ajouté
    demain sans être classé, ou une garde retirée par inadvertance.

    ⚠️ Plusieurs de ces outils portaient « ALWAYS ask user confirmation » dans
    leur propre docstring. Une docstring est une consigne AU MODÈLE, pas un
    garde-fou : rien ne l'applique s'il passe outre.

    Args:
        unguarded: pour les tests — la liste à transformer en constats. Sans
            elle, on interroge la table réelle.

    Ne lève jamais : un instrument de diagnostic ne fait pas tomber le démarrage.
    """
    if unguarded is None:
        try:
            from app.agent.tool_nature import unguarded_engaging_tools

            unguarded = unguarded_engaging_tools()
        except Exception as exc:  # noqa: BLE001 — le diagnostic reste optionnel
            logger.debug("nature des outils illisible (%s)", exc)
            return []

    return [
        Finding(
            kind="unguarded_engaging_tool",
            subject=name,
            detail=(
                "acte irréversible ou visible par des tiers, exécutable sans "
                "que l'utilisateur soit consulté"
            ),
        )
        for name in unguarded
    ]


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
        for check in (_check_model_window, _check_model_pricing,
                      _check_model_output_cap):
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
    # Résolu UNE fois : `_resolved_models` instancie un client par tier.
    used: dict[str, str] = {}
    try:
        used = await _resolved_models() if resolved_models is None else resolved_models
        declared = {m for m in (names or []) if m}
        for tier, model in (used or {}).items():
            findings.extend(_check_resolved_model(tier, model or "", declared))
    except Exception as exc:  # noqa: BLE001
        logger.debug("contrôle du résolveur échoué (%s)", exc)

    # Servir le rang 2 de sa propre chaîne passe les contrôles ci-dessus — le
    # modèle est connu ET déclaré. C'est pourtant un repli, et sur ce chemin
    # il n'en existe aucune trace ailleurs (cf. `_check_tier_uses_primary`).
    try:
        primaries = await _primary_models()
        for tier, model in (used or {}).items():
            found = _check_tier_uses_primary(tier, model or "", primaries.get(tier, ""))
            if found is not None:
                findings.append(found)
    except Exception as exc:  # noqa: BLE001
        logger.debug("contrôle rang 1 vs rang servi échoué (%s)", exc)

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
    else:
        logger.warning(
            "Contrôle de réalité : %d valeur(s) de configuration tombent dans un "
            "repli — voir le détail ci-dessous", len(findings),
        )
        for f in findings:
            logger.warning("  %s", f)

    # Journalisé À PART, et volontairement pas fusionné dans `findings` : ce
    # n'est pas une valeur de configuration tombée dans un repli, c'est un
    # périmètre d'action jamais soumis à l'utilisateur. Les mélanger noierait
    # les constats de configuration sous 26 lignes permanentes et casserait le
    # contrat « liste vide = rien à signaler » sur lequel s'appuient les pins.
    nus = check_unguarded_engaging_tools()
    if nus:
        logger.warning(
            "Actes engageants sans autorisation : %d outil(s) peuvent agir de "
            "façon irréversible ou visible par des tiers sans que l'utilisateur "
            "soit consulté — %s",
            len(nus), ", ".join(f.subject for f in nus[:8]) + (" …" if len(nus) > 8 else ""),
        )
    return len(findings) + len(nus)
