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
    scan de criticité HITL."""

    user_id: str
    conversation_id: str
    pii_filter: SecurityFilter | None
    criticality_filter: SecurityFilter
    hitl: Any
    memory: Any


async def execute_tool_call(
    ctx: GatewayContext,
    tool_call: dict,
    tool_map: dict[str, Any],
) -> Any:
    """Exécute UN appel d'outil à travers toutes les gates.

    Retourne le message-outil à ajouter à l'historique (dict ``role="tool"``,
    ou ``ToolMessage`` si l'outil est inconnu). Corps extrait VERBATIM de
    ``tool_node`` — les alias ci-dessous conservent les noms d'origine pour
    garder le diff d'extraction lisible et le comportement identique.
    """
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
    if tool_name in GOOGLE_TOOLS:
        from app.services.credential_store import get_credential_store
        _uid = user_id or ""
        _store = get_credential_store()
        _creds = _store.get(_uid) or ""
        # Fallback (audit 2026-05-07): if the in-process cache is empty
        # — happens after a backend restart while the WebSocket is
        # still alive but the 5-min refresh hasn't ticked yet, or after
        # an OAuth re-consent that didn't propagate to the cache —
        # refresh straight from the DB. Better to pay one query per
        # tool call than to lie « Google non connecté » when the user
        # is in fact connected.
        if not _creds and _uid:
            try:
                from app.database import async_session as _async_session
                from app.models.user import User as _U
                async with _async_session() as _db:
                    _u = await _db.get(_U, _uid)
                    if _u and _u.google_credentials:
                        _creds = _u.google_credentials
                        _store.set(_uid, _creds)
                        logger.warning(
                            "[creds] cache miss for user=%s — refreshed from DB",
                            _uid,
                        )
            except Exception as _creds_exc:
                logger.warning("[creds] DB fallback failed: %s", _creds_exc)
        args["user_google_credentials_json"] = _creds
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
            logger.debug("MCP HITL check skipped: %s", _mcp_exc)
    elif tool_name in _MCP_SELF_GATING_TOOLS:
        needs_hitl = False
    # Task-scoped approval (2026-06-03) — checked FIRST so it bypasses
    # even LOCKED_HITL_TOOLS: it's the user's explicit, ephemeral,
    # per-conversation "allow for this task" consent. Keyed by tool_name
    # only (args ignored) so one click covers every later call of this
    # tool in the conversation — fixes the "11 deletes, 11 clicks because
    # each file_id re-prompted" friction. NOT persisted across tasks.
    if needs_hitl and _conv_id:
        try:
            from app.services.task_approvals import is_tool_approved_for_task
            if is_tool_approved_for_task(_conv_id, tool_name):
                logger.info(
                    "HITL skipped (task-scoped allow) tool=%s conv=%s",
                    tool_name, _conv_id[:8],
                )
                needs_hitl = False
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
    if needs_hitl:
        logger.info("HITL required for action: %s", action_desc)
        decision, reason = await hitl.request_validation(
            description=action_desc,
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
                    await set_permission(user_id, tool_name, "allow")
                else:
                    from app.services.hitl_preferences import set_user_preference
                    await set_user_preference(
                        user_id, tool_name, requires_confirmation=False,
                    )
                logger.info(
                    "HITL: tool %s now always-allowed for user %s",
                    tool_name, user_id[:8],
                )
            except Exception as _save_exc:
                logger.debug("Could not save HITL preference: %s", _save_exc)
            # Fall through to execute (same as plain "allow")
        elif decision == "allow_for_task":
            # Approve this tool (action) for the REST OF THIS CONVERSATION
            # only — args-agnostic, ephemeral, NOT persisted. Works even
            # for LOCKED tools. Then fall through to execute this time.
            try:
                from app.services.task_approvals import approve_tool_for_task
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
            from app.services.event_envelope import EventKind, emit
            emit(EventKind.TOOL, user_id=user_id, capability_id=tool_name,
                 fingerprint=_action_fp, outcome="idempotent_cache")
            return _tool_result(_cached, tc_id)

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
            result = await tool.ainvoke(args)
            logger.warning("⏱ TIMING[tool:%s] %.2fs", tool_name, _tt.monotonic() - _ts)
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
            if _vault_sf is not None:
                # ner_detection=False : contenu MACHINE — regex + vault
                # seulement, pas de détection NER fraîche (les résultats
                # web/GitHub/emails sont publics ; les masquer casse
                # l'agent — retour terrain 2026-06-11).
                _safe_result = _vault_sf.anonymize(_safe_result, ner_detection=False)
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
            if _vault_sf is not None:
                _err = _vault_sf.anonymize(_err, ner_detection=False)
            return _tool_result(_err, tc_id)
    else:
        from langchain_core.messages import ToolMessage
        return ToolMessage(
            content=f"Outil '{tool_name}' non disponible.",
            tool_call_id=tc_id,
        )
