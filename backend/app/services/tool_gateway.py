# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/tool_gateway.py
# @brief      Tool Gateway (C3a) — LE pipeline unique d'exécution d'un appel
#             d'outil, extrait de agent/tool_node.py (audit 16/07 §8.3).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Passerelle d'outils — un appel, toutes les gates, dans l'ordre.

Extraction STRANGLER (C3a) : le nœud de graphe ``agent/tool_node.py`` reste
l'itérateur du tour (setup des ContextVars, boucle sur les tool_calls) ; la
passerelle porte le pipeline PAR APPEL, à comportement strictement identique :

  1. désanonymisation PII des arguments (placeholders → vraies valeurs) ;
  2. injection d'arguments cachés (credentials Google serveur, user_id) ;
  3. résolution Vault (``vault://label``) ;
  4. gates HITL — manifeste de capacité (substrat), canary io, ACL MCP,
     approbation task-scoped, préférences utilisateur, décisions
     allow / allow_for_task / allow_always / deny / ban ;
  5. ACL outils d'instance (admin) ;
  6. empreinte d'action fail-closed (l'action exécutée = celle approuvée) ;
  7. idempotence (« jamais deux fois par accident ») ;
  8. snapshot puis journal d'actions réversibles ;
  9. exécution + sanitisation du résultat (base64) ;
 10. ré-anonymisation PII du résultat AVANT retour au LLM (souveraineté) ;
 11. événements typés + signaux d'apprentissage (refus HITL, erreurs).

C3b migre les sous-agents et le dispatcher de missions sur cette même
passerelle — aucun appelant ne doit exécuter un outil autrement.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from app.agent.helpers.message_sanitizer import _tool_result
from app.agent.helpers.tool_history import _sanitize_tool_result_for_history
from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS
from app.services.background_tasks import spawn
from app.services.security_filter import (
    ALWAYS_CRITICAL_TOOLS,
    INSTRUCTION_ARG_KEYS,
    SecurityFilter,
)

logger = logging.getLogger(__name__)

# Outils model-facing du client MCP : ils appliquent eux-mêmes ACL + politique
# de données sortantes + HITL ciblé → on n'ajoute pas un HITL générique ici.
_MCP_SELF_GATING_TOOLS: frozenset[str] = frozenset({
    "mcp_list_servers", "mcp_discover_tools", "mcp_call_tool",
    "mcp_connect", "mcp_propose_server", "mcp_search_registry",
    # J6 — resources / prompts (lecture seule, auto-gérés en interne)
    "mcp_list_resources", "mcp_read_resource", "mcp_list_prompts", "mcp_get_prompt",
})


def deanonymize_args(pii_filter: SecurityFilter | None, value: Any) -> Any:
    """Restaure récursivement les placeholders PII ([EMAIL_0]…) d'une valeur
    d'argument d'outil — sans filtre, no-op."""
    if pii_filter is None:
        return value
    if isinstance(value, str):
        return pii_filter.deanonymize(value)
    if isinstance(value, dict):
        return {k: deanonymize_args(pii_filter, v) for k, v in value.items()}
    if isinstance(value, list):
        return [deanonymize_args(pii_filter, v) for v in value]
    return value


@dataclass
class GatewayContext:
    """Contexte de sécurité d'exécution d'un tour (audit §6.1 —
    ExecutionSecurityContext) : construit à l'entrée, transmis à la
    passerelle. ``pii_filter`` est l'instance PARTAGÉE de la conversation
    (registre conversation_filters) ; ``criticality_filter`` ne sert qu'au
    scan de criticité HITL. ``user_request`` (dernier message humain) nourrit
    la description HITL humanisée (fix Temu #21) ; ``label`` préfixe les logs
    de timing (nom du sous-agent, vide pour le chat)."""

    user_id: str
    conversation_id: str
    pii_filter: SecurityFilter | None
    criticality_filter: SecurityFilter
    hitl: Any
    memory: Any
    user_request: str = ""
    label: str = ""
    # C3b-2 — composition avec les appelants à politique PROPRE (missions) :
    # needs_hitl_final : None = la passerelle décide (pipeline complet) ;
    #   bool = l'appelant a déjà arbitré (gate mandat, autorité supérieure) —
    #   la passerelle garde le PROMPT et le traitement des décisions.
    # anonymize_results : False = l'appelant anonymise à SA frontière LLM
    #   (missions : anonymize_messages autour de chaque ainvoke) — les
    #   résultats restent bruts pour les steps/carnet visibles utilisateur.
    # pre_execute : hook async (tool_name, args) -> str|None — un refus
    #   n'exécute PAS l'outil (disjoncteurs J3 des missions).
    # post_execute : hook (tool_name, ok, elapsed_s, result_ou_exc) -> None
    #   (journal de bord J4).
    needs_hitl_final: bool | None = None
    anonymize_results: bool = True
    pre_execute: Any = None
    post_execute: Any = None
    # Surface INTERACTIVE (un humain attend devant son écran) : un outil qui
    # dépasse le budget bascule en tâche de fond au lieu de monopoliser le
    # tour (incident 24/07). Les missions et le scheduler laissent False —
    # ils ont le droit d'attendre et portent leurs propres budgets.
    interactive: bool = False
    # C4-4 — replay shadow STRICT : quand non-None, la passerelle ne fait
    # QU'UNE chose : re-servir les ToolMessages enregistrés du tour
    # d'origine (duck-typed : .serve(tool_name) -> str|None, .misses).
    # Court-circuit TOTAL en tête d'execute_tool_call — aucun outil réel,
    # aucun HITL, aucune injection de credentials, aucun journal n'est
    # atteignable en shadow, par construction (fail-closed).
    shadow_results: Any = None


# Envois de mail « à soi-même » : risque quasi nul (on ne fuit pas ses
# propres données vers soi) mais le HITL les bloquait — impossible à
# satisfaire hors-ligne (digest quotidien de 6 h). Historiquement réservé
# aux spécialistes, généralisé en C3b.
_SELF_MAIL_TOOLS: frozenset[str] = frozenset({
    "gmail_send_email", "gmail_reply_email", "gmail_send_with_attachment",
})


class GoogleAccountUnknown(Exception):
    """L'alias de compte Google demandé ne résout vers aucun compte lié.

    ⚠️ CE QUE ÇA CORRIGE (audit du 02/09/2026). Un alias introuvable — ou
    une recherche en erreur — posait un avertissement dans les logs et
    continuait avec les identifiants du compte PAR DÉFAUT : « envoie ce
    mail depuis mon compte travail » partait du compte personnel, et rien
    ne le disait à l'utilisateur. Un alias qui ne résout pas est un refus,
    porté jusqu'au modèle avec les comptes qui existent.
    """

    def __init__(self, alias: str, connus: list[str]) -> None:
        self.alias = alias
        self.connus = connus
        liste = ", ".join(f"« {a} »" for a in connus) if connus else "aucun compte lié"
        super().__init__(
            f"⛔ Compte Google « {alias} » inconnu pour cet utilisateur — "
            f"l'appel n'a PAS été exécuté (il serait parti du compte par "
            f"défaut). Comptes disponibles : {liste} ; omets « account » "
            f"pour le compte par défaut."
        )


async def _google_account_aliases(user_id: str) -> list[str]:
    """Les alias de comptes Google liés à l'utilisateur (best-effort)."""
    try:
        from sqlalchemy import select as _select

        from app.database import async_session as _async_session
        from app.models.google_account import GoogleAccount as _GA
        async with _async_session() as _db:
            rows = await _db.execute(
                _select(_GA.alias).where(_GA.user_id == user_id)
            )
            return sorted({a for a in rows.scalars().all() if a})
    except Exception:  # noqa: BLE001 — une aide, pas une garde
        return []


async def _inject_google_credentials(user_id: str, args: dict) -> None:
    """Injecte les credentials Google depuis le stockage SERVEUR (jamais
    l'état du graphe — SEC-1). Multi-comptes (C3b, historiquement réservé
    aux spécialistes) : l'alias ``account`` passé par le LLM cible un
    GoogleAccount lié ; alias vide/« default » → store mémoire →
    GoogleAccount par défaut → User.google_credentials legacy, avec
    repeuplement du store pour les appels suivants. Un alias explicite
    qui ne résout pas lève ``GoogleAccountUnknown`` : jamais de repli sur
    un autre compte que celui demandé."""
    _uid = user_id or ""
    _requested_alias = (args.pop("account", "") or "").strip()
    _resolved_creds: str | None = None
    if _uid and _requested_alias and _requested_alias.lower() != "default":
        try:
            from sqlalchemy import select as _select

            from app.database import async_session as _async_session
            from app.models.google_account import GoogleAccount as _GA
            async with _async_session() as _db:
                _row = await _db.execute(
                    _select(_GA.credentials_json).where(
                        _GA.user_id == _uid,
                        _GA.alias == _requested_alias,
                    )
                )
                _resolved_creds = _row.scalar_one_or_none()
        except Exception as _ga_exc:
            logger.warning(
                "GoogleAccount lookup failed for uid=%s alias=%s: %s — appel refusé",
                _uid, _requested_alias, _ga_exc,
            )
            _resolved_creds = None
        if _resolved_creds is None:
            logger.warning(
                "Google account alias '%s' not found for user %s — appel refusé, "
                "pas de repli sur le compte par défaut", _requested_alias, _uid,
            )
            raise GoogleAccountUnknown(
                _requested_alias, await _google_account_aliases(_uid),
            )
    if _resolved_creds:
        args["user_google_credentials_json"] = _resolved_creds
        return

    from app.services.credential_store import get_credential_store
    _creds = get_credential_store().get(_uid) or ""
    # Fallback DB si le store est vide — heartbeats de mission, tâches
    # planifiées, cron (qui ne passent pas par chat.py), et chaque restart
    # backend qui vide le store en mémoire. Sans lui, tous les outils
    # Google mentent « Google non connecté » (mission #19/15, avril 2026).
    if not _creds and _uid:
        try:
            from sqlalchemy import select as _select

            from app.database import async_session as _async_session
            from app.models.google_account import GoogleAccount as _GA
            from app.models.user import User as _U
            async with _async_session() as _db:
                # 1. Le GoogleAccount marqué par défaut
                _row = await _db.execute(
                    _select(_GA.credentials_json).where(
                        _GA.user_id == _uid,
                        _GA.is_default == True,  # noqa: E712
                    )
                )
                _creds = _row.scalar_one_or_none() or ""
                # 2. Legacy : User.google_credentials
                if not _creds:
                    _u = await _db.get(_U, _uid)
                    if _u and _u.google_credentials:
                        _creds = _u.google_credentials
            if _creds:
                get_credential_store().set(_uid, _creds)
                logger.info(
                    "Credential store re-populated from DB for user %s",
                    _uid[:8] + "…",
                )
        except Exception as _creds_exc:
            logger.warning("[creds] DB fallback failed for %s: %s",
                           _uid[:8] + "…", _creds_exc)
    args["user_google_credentials_json"] = _creds


def _truthy_env(name: str) -> bool:
    """Lecture d'un flag d'environnement sans dépendre du module qui vient
    justement de tomber (utilisée par le fail-closed du canary io)."""
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


async def _decide_hitl(ctx: GatewayContext, tool_name: str, args: dict,
                       display_args: dict) -> bool:
    """Pipeline de DÉCISION HITL de la passerelle (extrait en C3b-2) :
    base (manifeste/criticité) → canary io → gating MCP → approbation
    task-scoped → préférence utilisateur → self-mail. Les appelants à
    politique propre (gate mandat des missions) court-circuitent CE
    pipeline entier via ``ctx.needs_hitl_final`` — indispensable car le
    canary io est STATEFUL (le court-circuit doit empêcher son exécution,
    pas seulement ignorer son résultat)."""
    user_id = ctx.user_id
    _conv_id = ctx.conversation_id
    sf = ctx.criticality_filter
    from app.config import get_settings as _get_settings
    # HITL check. The is_critical keyword scan EXCLUDES deferred-instruction
    # args (prompt/code) — a keyword in "what to run later" (e.g. a
    # scheduled task « supprimer … ») must not gate the harmless CURRENT
    # call. action_desc stays full for the HITL prompt + logs.
    _crit_args = {k: v for k, v in display_args.items() if k not in INSTRUCTION_ARG_KEYS}
    _crit_desc = f"Outil: {tool_name} | Arguments: {json.dumps(_crit_args, ensure_ascii=False)}"
    # Substrat de confiance (P1/J1) — derrière le flag, la décision HITL de
    # base est pilotée par le CapabilityManifest (approval: always|risk_based|
    # never), qui REPRODUIT à l'identique la règle actuelle pour tout outil
    # connu. Flag OFF → comportement historique strictement préservé.
    if _get_settings().trust_substrate_enabled:
        from app.services.capability_manifest import manifest_requires_hitl
        needs_hitl = manifest_requires_hitl(tool_name, _crit_desc, sf.is_critical)
    else:
        needs_hitl = (tool_name in ALWAYS_CRITICAL_TOOLS) or sf.is_critical(_crit_desc)
    # Sprint 4b V3 — période canary des outils io (design §5.6, v1.15.0) :
    # les N premières invocations d'un outil io auto-généré (egress réel,
    # nouveau chemin de code) passent par HITL avant que l'outil ne soit
    # pleinement de confiance. No-op quand le flag io est off. Les
    # bypasses ci-dessous (task-scoped allow, « toujours autoriser »)
    # restent honorés — c'est un consentement explicite de l'utilisateur.
    if not needs_hitl:
        try:
            from app.services.learning.learned_tools_runtime_io import (
                io_canary_requires_hitl,
            )
            needs_hitl = await io_canary_requires_hitl(user_id, tool_name)
        except Exception as _canary_exc:
            # V0-3 — FAIL-CLOSED (audit Opus 5 §4.6). Avant, l'exception
            # partait en `debug` et `needs_hitl` restait False : un outil
            # auto-généré à egress réel s'exécutait sans validation, et la
            # garde disparaissait sans que rien ne le signale.
            #
            # Le refermement reste SCOPÉ : quand le profil io est éteint,
            # le canary ne garde rien (io_canary_requires_hitl rend False
            # d'emblée) — exiger un HITL sur chaque outil parce que ce
            # module ne s'importe plus serait une régression bien pire que
            # le trou qu'on bouche. Le flag est relu ici sans passer par le
            # module en panne.
            _io_on = _truthy_env("LEARNED_PYTHON_TOOLS_IO_ENABLED") and not _truthy_env(
                "LEARNED_PYTHON_TOOLS_DISABLED"
            )
            if _io_on:
                needs_hitl = True
                logger.warning(
                    "io canary indisponible pour %s (%s) — HITL exigé (fail-closed)",
                    tool_name, _canary_exc,
                )
            else:
                logger.debug("io canary check skipped: %s", _canary_exc)
    # Client MCP universel (J4) — gating spécifique :
    #  - un outil MCP d'instance (mcp__slug__tool, dans le registre) confirme
    #    selon son risque/permission (ACL fine) ;
    #  - les outils model-facing (mcp_connect/call/…) s'auto-gèrent en
    #    interne (ACL + données sortantes + HITL ciblé) → pas de double prompt.
    if tool_name.startswith("mcp__"):
        try:
            from app.services.mcp_acl import needs_hitl as _mcp_needs_hitl
            if await _mcp_needs_hitl(user_id, tool_name):
                needs_hitl = True
        except Exception as _mcp_exc:
            # V0-3 — FAIL-CLOSED (audit Opus 5 §4.6). Une ACL illisible
            # laissait passer l'outil d'un serveur MCP tiers sans
            # confirmation. Le refermement est naturellement scopé : on est
            # déjà dans la branche `tool_name.startswith("mcp__")`.
            needs_hitl = True
            logger.warning(
                "ACL MCP indisponible pour %s (%s) — HITL exigé (fail-closed)",
                tool_name, _mcp_exc,
            )
    elif tool_name in _MCP_SELF_GATING_TOOLS:
        needs_hitl = False
    # Task-scoped approval (2026-06-03) — checked FIRST so it bypasses
    # even LOCKED_HITL_TOOLS: it's the user's explicit, ephemeral,
    # per-conversation "allow for this task" consent. Keyed by tool_name
    # only (args ignored) so one click covers every later call of this
    # tool in the conversation — fixes the "11 deletes, 11 clicks because
    # each file_id re-prompted" friction. NOT persisted across tasks.
    #
    # ⚠️ SAUF les outils NON DISPENSABLES (audit 02/09/2026, second tour).
    # Fermer la préférence permanente sans fermer celle-ci ne fermait rien :
    # ce test-ci vient AVANT, donc « Autoriser pour cette tâche » sur un
    # ``*_raw_api_call`` éteignait la confirmation pour tout le reste de la
    # conversation — un passe-plat refait ce que font tous les autres outils
    # Google sans passer par eux. Le critère n'est pas recopié ici : il vit
    # dans ``hitl_preferences.is_hitl_waivable``, consulté aussi à
    # l'ENREGISTREMENT de la décision (cf. branche ``allow_for_task``) et par
    # le chemin missions. Refuser à la LECTURE est le garde-fou porteur : il
    # neutralise aussi les approbations déjà en mémoire d'un run en cours.
    if needs_hitl and _conv_id:
        try:
            from app.services.hitl_preferences import is_hitl_waivable
            from app.services.task_approvals import is_tool_approved_for_task
            if is_tool_approved_for_task(_conv_id, tool_name):
                if is_hitl_waivable(tool_name):
                    logger.info(
                        "HITL skipped (task-scoped allow) tool=%s conv=%s",
                        tool_name, _conv_id[:8],
                    )
                    needs_hitl = False
                else:
                    logger.info(
                        "HITL maintenu malgre une approbation de tache : %s "
                        "n'est pas dispensable (passe-plat)", tool_name,
                    )
        except Exception as _ta_exc:
            logger.debug("task-approval lookup failed: %s", _ta_exc)
    # Per-user override (2026-05-23) — honour "Toujours autoriser"
    # preference set by the user via the HITL panel ; mirrors what
    # sub_agents/factory.py already does. Depuis 2026-06-19, la préférence
    # vaut AUSSI pour les outils dangereux (LOCKED_HITL_TOOLS), désormais
    # désactivables à ses risques (résolu dans user_requires_hitl).
    if needs_hitl and user_id:
        try:
            from app.services.hitl_preferences import user_requires_hitl
            if not await user_requires_hitl(user_id, tool_name):
                logger.info(
                    "HITL skipped (user preference) tool=%s user=%s",
                    tool_name, user_id[:8],
                )
                needs_hitl = False
        except Exception as _pref_exc:
            logger.debug("HITL preference lookup failed: %s", _pref_exc)
    # ── Self-mail auto-approve (C3b, ex-spécialistes) ─────────────────
    # Envoyer un mail à SA PROPRE adresse (User.email ou tout GoogleAccount
    # lié) ne déclenche pas de HITL — sinon le digest planifié de 6 h reste
    # bloqué sur une confirmation que personne ne peut donner. Toute erreur
    # de résolution ⇒ HITL conservé (défaut sûr).
    if needs_hitl and tool_name in _SELF_MAIL_TOOLS:
        try:
            _to = (args.get("to") or "").strip().lower()
            from sqlalchemy import select as _sel

            from app.database import async_session as _async_session
            from app.models.google_account import GoogleAccount as _GA
            from app.models.user import User as _U
            async with _async_session() as _db:
                _u = await _db.get(_U, user_id) if user_id else None
                _self_emails: set[str] = set()
                if _u and _u.email:
                    _self_emails.add(_u.email.strip().lower())
                if user_id:
                    _rows = await _db.execute(
                        _sel(_GA.email).where(_GA.user_id == user_id)
                    )
                    for (_em,) in _rows.all():
                        if _em:
                            _self_emails.add(str(_em).strip().lower())
            # Match also handles "Name <email@x.com>" formatting
            if any(em and em in _to for em in _self_emails):
                logger.info(
                    "HITL skipped (self-mail) — to=%s matches user's own address",
                    _to[:80],
                )
                needs_hitl = False
        except Exception as _sm_exc:
            # Any error here → keep HITL enabled (safer default)
            logger.debug("self-mail check failed: %s", _sm_exc)
    return needs_hitl


async def execute_tool_call(
    ctx: GatewayContext,
    tool_call: dict,
    tool_map: dict[str, Any],
    meta: dict | None = None,
) -> Any:
    """Exécute UN appel d'outil à travers toutes les gates.

    Retourne le message-outil à ajouter à l'historique (dict ``role="tool"``,
    ou ``ToolMessage`` si l'outil est inconnu). Corps extrait VERBATIM de
    ``tool_node`` — les alias ci-dessous conservent les noms d'origine pour
    garder le diff d'extraction lisible et le comportement identique.
    """
    if meta is not None:
        meta.setdefault("success", False)  # seuls exécution OK / cache passent à True

    # ── C4-4 : mode REPLAY SHADOW — court-circuit total (fail-closed) ────
    # On re-sert le résultat ENREGISTRÉ du tour d'origine ; un outil sans
    # résultat enregistré reçoit une notice explicite et n'est JAMAIS
    # exécuté. Placé avant toute autre logique : ni PII, ni vault, ni
    # HITL, ni credentials, ni journal ne tournent en shadow.
    if ctx.shadow_results is not None:
        _sh_name = tool_call.get("name", "")
        _sh_id = tool_call.get("id", "")
        _served: str | None = None
        try:
            _served = ctx.shadow_results.serve(_sh_name)
        except Exception as _sh_exc:  # noqa: BLE001 — session shadow défaillante = miss
            logger.debug("shadow serve failed for %s: %s", _sh_name, _sh_exc)
        if _served is None:
            _served_content = (
                f"[replay : outil non enregistré — `{_sh_name}` n'a pas de "
                "résultat capturé dans le tour d'origine ; exécution réelle "
                "interdite en mode shadow. Réponds avec ce que tu as.]"
            )
        else:
            _served_content = _served
            if meta is not None:
                meta["success"] = True
        if meta is not None:
            meta["shadow"] = True
        return _tool_result(_served_content, _sh_id)

    user_id = ctx.user_id
    _conv_id = ctx.conversation_id
    _vault_sf = ctx.pii_filter
    sf = ctx.criticality_filter
    hitl = ctx.hitl
    memory = ctx.memory

    tool_name = tool_call["name"]
    # Deanonymize tool args BEFORE any other processing so HITL preview,
    # logs, and the actual API call all see the real values.
    args = deanonymize_args(_vault_sf, dict(tool_call["args"]))

    # Inject hidden arguments — credentials are fetched from the server-side
    # store (never stored in graph state) to prevent exposure in logs/events.
    # Multi-comptes inclus (alias ``account``) — voir _inject_google_credentials.
    if tool_name in GOOGLE_TOOLS:
        try:
            await _inject_google_credentials(user_id, args)
        except GoogleAccountUnknown as exc:
            # Refus AVANT le HITL : on ne demande pas à l'utilisateur
            # d'approuver un acte qu'on ne peut pas faire depuis le bon compte.
            return _tool_result(str(exc), tool_call["id"])
    if tool_name in USER_ID_TOOLS:
        args["user_id"] = user_id or ""

    # Build display args — never expose tokens or injected IDs in UI/logs
    _hidden = {"user_google_credentials_json", "user_id"}
    display_args = {k: v for k, v in args.items() if k not in _hidden}
    action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
    tc_id = tool_call["id"]

    # Substrat de confiance (P1/J2) — empreinte du plan d'action canonique.
    # Calculée sur display_args (AVANT résolution vault:// → pas de secret),
    # liée à l'approbation, et re-vérifiée juste avant l'exécution
    # (fail-closed). Devient pleinement protectrice quand approbation et
    # exécution sont séparées dans le temps (file durable / Intent Escrow).
    _action_fp = None
    from app.config import get_settings as _get_settings
    if _get_settings().trust_substrate_enabled:
        from app.services.action_plan import build_action_plan, fingerprint as _action_fingerprint
        _action_fp = _action_fingerprint(
            build_action_plan(tool_name, display_args, user_id, _conv_id)
        )

    # ── Vault: resolve vault://label references in args ───────────────
    vault_refs_found = any(
        isinstance(v, str) and v.startswith("vault://")
        for v in args.values()
    )
    if vault_refs_found:
        from app.services.vault_service import get_vault_service
        vault = get_vault_service()
        if vault.is_locked(user_id):
            return _tool_result(
                "⛔ Vault verrouillé — déverrouillez votre coffre-fort dans Paramètres > Vault "
                "pour utiliser ce secret.", tc_id
            )
        try:
            args, _resolved = await vault.resolve_vault_refs(user_id, args)
            if _resolved:
                logger.info("Resolved vault refs %s for tool %s", _resolved, tool_name)
        except KeyError as exc:
            return _tool_result(f"⛔ Secret introuvable dans le Vault : {exc}", tc_id)

    if ctx.needs_hitl_final is not None:
        # C3b-2 — décision de l'appelant (gate mandat mission).
        needs_hitl = ctx.needs_hitl_final
    else:
        needs_hitl = await _decide_hitl(ctx, tool_name, args, display_args)
    if needs_hitl:
        # Fix #21 (Temu, mai 2026) — description HITL humanisée : pré-compte,
        # demande d'origine de l'utilisateur, alertes d'écart args/intention.
        # Historiquement réservée aux spécialistes, généralisée en C3b.
        try:
            from app.services.hitl_descriptions import build_human_hitl_description
            _hitl_desc = await build_human_hitl_description(
                tool_name=tool_name,
                args=args,
                user_request=ctx.user_request,
                user_credentials_json=args.get("user_google_credentials_json", ""),
            )
        except Exception as _hum_exc:
            _hitl_desc = action_desc
            logger.debug("HITL humanizer failed: %s", _hum_exc)
        logger.info("HITL required for action: %s", action_desc)
        decision, reason = await hitl.request_validation(
            description=_hitl_desc,
            user_id=user_id,
        )
        # P1/J4 — événement d'approbation (décision seule, aucun contenu).
        if _action_fp is not None:
            from app.services.event_envelope import EventKind, emit
            emit(EventKind.APPROVAL, user_id=user_id, capability_id=tool_name,
                 fingerprint=_action_fp, outcome=str(decision))
        if decision == "ban":
            rule = f"INTERDICTION PERMANENTE: {action_desc}"
            if reason:
                rule += f" — Raison: {reason}"
            await memory.store_constraint(rule, user_id)
            # Sprint 3.7 Jalon 2 — persist HITL refusal as learning signal
            try:
                from app.services.learning import record_hitl_refusal
                spawn(record_hitl_refusal(
                    user_id=user_id,
                    conversation_id=_conv_id,
                    tool_name=tool_name,
                    args=args,
                    action_description=action_desc,
                    decision="ban",
                    reason=reason or "user-provided",
                ))
            except Exception as _sig_exc:
                logger.debug("HITL refusal signal skipped: %s", _sig_exc)
            return _tool_result(
                "Action interdite définitivement et règle de sécurité enregistrée.", tc_id
            )
        elif decision == "allow_always":
            # Save user preference so future calls to the same tool by
            # the same user skip the HITL prompt entirely. Then fall
            # through to execute the tool this time. The frontend
            # button "Toujours autoriser" sends this decision ; the
            # backward-compatible "Toujours interdire" sends "ban".
            try:
                if tool_name.startswith("mcp__"):
                    # Outil MCP : le gate lit mcp_tool_permissions, PAS
                    # hitl_preferences → on persiste là (sinon « Toujours
                    # autoriser » ne tenait jamais, ré-demande à chaque appel,
                    # même d'un run à l'autre — bug terrain Franck 2026-06-20).
                    from app.services.mcp_acl import set_permission
                    _dispense_ecrite = await set_permission(
                        user_id, tool_name, "allow",
                    )
                else:
                    from app.services.hitl_preferences import set_user_preference
                    _dispense_ecrite = await set_user_preference(
                        user_id, tool_name, requires_confirmation=False,
                    )
                # Le retour compte depuis le 02/09/2026 : la dispense est
                # REFUSÉE pour les outils non dispensables, donc rien n'est
                # écrit. Journaliser « now always-allowed » sans regarder,
                # c'était affirmer l'inverse de la vérité dans le seul
                # endroit où on irait la chercher après coup.
                if _dispense_ecrite:
                    logger.info(
                        "HITL: tool %s now always-allowed for user %s",
                        tool_name, user_id[:8],
                    )
                else:
                    logger.info(
                        "HITL: dispense permanente NON enregistree pour %s "
                        "(user %s) — la confirmation restera demandee",
                        tool_name, user_id[:8],
                    )
            except Exception as _save_exc:
                logger.debug("Could not save HITL preference: %s", _save_exc)
            # Fall through to execute (same as plain "allow")
        elif decision == "allow_for_task":
            # Approve this tool (action) for the REST OF THIS CONVERSATION
            # only — args-agnostic, ephemeral, NOT persisted. Works even
            # for LOCKED tools. Then fall through to execute this time.
            #
            # ⚠️ Sauf les outils non dispensables (audit 02/09/2026) : la
            # lecture les refuserait, on n'enregistre donc rien plutôt que de
            # garder une entrée morte. Cette occurrence-ci reste exécutée —
            # l'utilisateur vient de l'approuver, c'est la SUITE qui
            # redemandera.
            try:
                from app.services.hitl_preferences import is_hitl_waivable
                from app.services.task_approvals import approve_tool_for_task
                if not is_hitl_waivable(tool_name):
                    logger.info(
                        "HITL: approbation de tache NON enregistree pour %s "
                        "(passe-plat) — chaque appel restera confirme",
                        tool_name,
                    )
                else:
                    approve_tool_for_task(_conv_id, tool_name)
                    logger.info(
                        "HITL: tool %s allowed for the rest of conv %s (task-scoped)",
                        tool_name, (_conv_id or "")[:8],
                    )
            except Exception as _ta_exc:
                logger.debug("Could not register task-scoped approval: %s", _ta_exc)
            # Fall through to execute (same as plain "allow")
        elif decision != "allow":
            # Sprint 3.7 Jalon 2 — persist HITL refusal as learning signal.
            # Un timeout (ni validé ni refusé à temps) n'est PAS un refus
            # délibéré : record_hitl_refusal l'ignore, et on le dit au LLM.
            _is_timeout = reason == "timeout"
            try:
                from app.services.learning import record_hitl_refusal
                spawn(record_hitl_refusal(
                    user_id=user_id,
                    conversation_id=_conv_id,
                    tool_name=tool_name,
                    args=args,
                    action_description=action_desc,
                    decision="deny",
                    reason=reason or "user-provided",
                ))
            except Exception as _sig_exc:
                logger.debug("HITL refusal signal skipped: %s", _sig_exc)
            return _tool_result(
                "Action non validée dans le délai imparti (ni autorisée, ni "
                "refusée). L'utilisateur n'a pas répondu à temps."
                if _is_timeout else
                "Action refusée par l'utilisateur pour cette occurrence.",
                tc_id,
            )

    # B-12 (revue 2026-06-10) — outils à ressources d'INSTANCE (hôtes
    # SSH de l'admin, serveurs MCP avec secrets env_json admin) :
    # réservés au rôle admin tant qu'il n'y a pas d'ACL per-user.
    from app.services.tool_acl import check_tool_access
    _acl_refusal = await check_tool_access(user_id, tool_name)
    if _acl_refusal:
        return _tool_result(_acl_refusal, tc_id)

    # P1/J2 — re-vérification de l'empreinte juste avant exécution :
    # l'action exécutée doit être EXACTEMENT celle approuvée (fail-closed).
    if _action_fp is not None:
        from app.services.action_plan import build_action_plan, fingerprint as _action_fingerprint
        _now_fp = _action_fingerprint(
            build_action_plan(tool_name, display_args, user_id, _conv_id)
        )
        if _now_fp != _action_fp:
            logger.warning(
                "[trust] empreinte d'action divergente — exécution annulée (tool=%s)",
                tool_name,
            )
            return _tool_result(
                "⛔ L'action a changé depuis ton approbation — exécution annulée. "
                "Re-demande une validation.", tc_id,
            )

    # P1/J3 — idempotence : une action « supported » identique déjà réussie
    # dans la fenêtre TTL renvoie son résultat mémorisé, sans ré-exécuter
    # (« jamais deux fois par accident »). No-op pour les outils non
    # idempotents (le manifeste décide). Gates HITL/ACL déjà passées.
    if _action_fp is not None:
        from app.services.idempotency_store import check_idempotent
        _cached = await check_idempotent(tool_name, _action_fp)
        if _cached is not None:
            logger.info("[trust] idempotence — résultat mémorisé renvoyé (tool=%s)", tool_name)
            if meta is not None:
                meta["success"] = True
            from app.services.event_envelope import EventKind, emit
            emit(EventKind.TOOL, user_id=user_id, capability_id=tool_name,
                 fingerprint=_action_fp, outcome="idempotent_cache")
            return _tool_result(_cached, tc_id)

    # C3b-2 — hook pré-exécution de l'appelant (disjoncteurs J3 des
    # missions) : un refus ici N'EXÉCUTE PAS l'outil. Une exception du
    # hook ne bloque jamais (fail-open, le hook gère son propre fail-safe).
    if ctx.pre_execute is not None:
        try:
            _pre_refusal = await ctx.pre_execute(tool_name, args)
        except Exception as _pre_exc:  # noqa: BLE001
            logger.warning("pre_execute hook failed (%s): %s", tool_name, _pre_exc)
            _pre_refusal = None
        if _pre_refusal:
            return _tool_result(_pre_refusal, tc_id)

    # Reversible Journal (J3) — capture l'état AVANT exécution pour les
    # compensations par snapshot (rename/move : l'état d'avant est perdu
    # après l'action). No-op (None) pour tout le reste. Best-effort, ne
    # bloque jamais l'exécution de l'outil.
    _pre_snapshot = None
    if _action_fp is not None and _get_settings().reversible_journal_enabled:
        try:
            from app.services.journal_service import snapshot_before
            _pre_snapshot = await snapshot_before(tool_name, display_args, user_id)
        except Exception as _snap_exc:  # pragma: no cover — best-effort
            logger.debug("snapshot_before failed (%s): %s", tool_name, _snap_exc)

    tool = tool_map.get(tool_name)
    if tool:
        try:
            import time as _tt
            _ts = _tt.monotonic()
            # Garde-fou « outil long » : au-delà du budget d'une surface
            # interactive, l'exécution CONTINUE en tâche de fond et le modèle
            # reçoit un accusé au lieu du résultat (incident 24/07). Point
            # unique : tous les outils passent ici, natifs comme MCP.
            from app.services.long_running_tools import invoke_with_handoff
            result, _handoff_notice = await invoke_with_handoff(
                ctx, tool_name, tool, args,
            )
            if _handoff_notice is not None:
                if meta is not None:
                    meta["handoff"] = True
                return _tool_result(_handoff_notice, tc_id)
            _tlabel = f"{ctx.label}.tool" if ctx.label else "tool"
            logger.warning("⏱ TIMING[%s:%s] %.2fs", _tlabel, tool_name, _tt.monotonic() - _ts)
            # Résultat qui RESSEMBLE à une erreur → logue aussi les args
            # (credentials expurgés) pour comprendre ce que le LLM a passé
            # (comportement ex-spécialistes, généralisé en C3b).
            _raw_probe = str(result)
            if "Erreur" in _raw_probe or "Error" in _raw_probe or "HttpError" in _raw_probe:
                _safe_args_log = {
                    k: ("<redacted>" if k == "user_google_credentials_json" else v)
                    for k, v in args.items()
                }
                logger.warning(
                    "[tool_error_args] %s:%s ARGS=%s — ERROR=%.400s",
                    _tlabel, tool_name, _safe_args_log, _raw_probe,
                )
            # Strip oversized base64 / binary payloads from the tool result
            # BEFORE storing in LangGraph state. The frontend has already
            # consumed the full payload via the on_tool_end event ; only
            # the model's history view needs the trimmed version. Without
            # this, browser_screenshot leaks ~200 KB of base64 into every
            # subsequent turn's prompt.
            _raw_result = str(result)
            _safe_result = _sanitize_tool_result_for_history(_raw_result)
            if len(_safe_result) < len(_raw_result):
                logger.info(
                    "[tool_history_strip] %s: %d → %d chars",
                    tool_name, len(_raw_result), len(_safe_result),
                )
            # ── PII boundary (sovereignty) ────────────────────────────
            # Anonymize PII the TOOL fetched (email bodies, contacts,
            # calendar, drive content…) BEFORE it goes back to the LLM —
            # which on tier B/C is a CLOUD model. The SecurityFilter only
            # covered user-TYPED PII; without this, agent-fetched personal
            # data reached the model in clear. Same per-conversation filter
            # instance as chat.py, so: the model sees [EMAIL_5], the
            # response is deanonymized for display there, and if the model
            # passes [EMAIL_5] back as a tool arg it's deanonymized above.
            # Capped at the filter's 50k ReDoS guard.
            if _vault_sf is not None and ctx.anonymize_results:
                # ner_detection=False : contenu MACHINE — regex + vault
                # seulement, pas de détection NER fraîche (les résultats
                # web/GitHub/emails sont publics ; les masquer casse
                # l'agent — retour terrain 2026-06-11).
                _safe_result = _vault_sf.anonymize(_safe_result, ner_detection=False)
            if ctx.post_execute is not None:
                try:
                    ctx.post_execute(tool_name, True, _tt.monotonic() - _ts, result)
                except Exception as _pe_exc:  # noqa: BLE001
                    logger.debug("post_execute hook failed: %s", _pe_exc)
            if meta is not None:
                meta["success"] = True
            # C3d-3 — registre de tour : mémorise le résultat ANONYMISÉ pour
            # que le général de secours en hérite si le sous-agent meurt
            # APRÈS cet appel (fallback honnête — exhibits 18/07 : « accès
            # Gmail indisponible » confabulé alors que le résultat était là).
            from app.services.turn_ledger import record as _ledger_record
            _ledger_record(ctx.conversation_id, tool_name, _safe_result)
            _msg = _tool_result(_safe_result, tc_id)
            # P1/J3 — mémorise le résultat d'une action « supported » réussie
            # (no-op si le manifeste ne déclare pas l'idempotence).
            if _action_fp is not None:
                from app.services.idempotency_store import remember
                await remember(tool_name, _action_fp, user_id, _safe_result)
                # Reversible Action Journal — journalise l'action si elle est
                # annulable (manifeste avec `compensation`). No-op strict si
                # le flag est OFF. On passe display_args (sans secret) : la
                # capture n'en retient que l'identifiant utile (ex. file_id).
                if _get_settings().reversible_journal_enabled:
                    try:
                        from app.services.journal_service import record_reversible
                        await record_reversible(
                            tool_name, display_args, _safe_result, user_id, _action_fp,
                            pre_snapshot=_pre_snapshot,
                        )
                    except Exception as _rev_exc:  # pragma: no cover — best-effort
                        logger.debug("record_reversible failed (%s): %s", tool_name, _rev_exc)
                # P1/J4 — événement outil (succès, latence — aucun contenu).
                from app.services.event_envelope import EventKind, emit
                emit(EventKind.TOOL, user_id=user_id, capability_id=tool_name,
                     fingerprint=_action_fp, outcome="success",
                     latency_ms=round((_tt.monotonic() - _ts) * 1000, 1))
            return _msg
        except Exception as exc:
            logger.warning("Tool %s failed: %s", tool_name, exc)
            if ctx.post_execute is not None:
                try:
                    ctx.post_execute(tool_name, False, _tt.monotonic() - _ts, exc)
                except Exception as _pe_exc:  # noqa: BLE001
                    logger.debug("post_execute hook failed: %s", _pe_exc)
            # P1/J4 — événement outil (erreur, type seulement — pas de message).
            if _action_fp is not None:
                from app.services.event_envelope import EventKind, emit
                emit(EventKind.TOOL, user_id=user_id, capability_id=tool_name,
                     fingerprint=_action_fp, outcome="error",
                     attributes={"error_type": type(exc).__name__})
            # Sprint 3.7 Jalon 2 — persist tool exception as learning signal
            try:
                import traceback as _tb
                from app.services.learning import record_tool_error
                spawn(record_tool_error(
                    user_id=user_id,
                    tool_name=tool_name,
                    args=args,
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                    traceback=_tb.format_exc(),
                ))
            except Exception as _sig_exc:
                logger.debug("tool error signal skipped: %s", _sig_exc)
            # Error strings can echo PII-bearing args → anonymize too.
            _err = f"Erreur d'exécution: {exc}"
            if _vault_sf is not None and ctx.anonymize_results:
                _err = _vault_sf.anonymize(_err, ner_detection=False)
            return _tool_result(_err, tc_id)
    else:
        from langchain_core.messages import ToolMessage
        return ToolMessage(
            content=f"Outil '{tool_name}' non disponible.",
            tool_call_id=tc_id,
        )
