# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_node.py
# @brief      Sprint refactor nodes.py Phase 3 — LangGraph tool execution
#             node. Handles PII deanonymisation, vault refs, HITL gating
#             (allow / deny / ban / allow_always), credentials injection,
#             learning-signal recording, and result sanitisation.
# @license    Elastic License 2.0
# @version    1.7.1
# =============================================================================
"""Tool node — executes the tool_calls emitted by ``agent_node``.

Responsibilities (in execution order, per tool_call)
----------------------------------------------------
1. **PII deanonymisation** — restore ``[EMAIL_0]`` / ``[PHONE_0]`` …
   placeholders to their real values from the per-conversation
   ``SecurityFilter``.
2. **Hidden argument injection** — Google credentials (from the
   server-side store), user_id (for memory tools), etc.
3. **Vault resolution** — ``vault://label`` references are replaced by
   the decrypted secret. Locked vault → polite refusal.
4. **HITL gating** — request human approval for critical tools. Decisions
   handled :
     - ``allow``          → execute this once
     - ``allow_for_task`` → approve this tool (args-agnostic) for the rest
                            of THIS conversation only — ephemeral, not
                            persisted, bypasses LOCKED_HITL_TOOLS
     - ``allow_always``   → persist user preference + execute this once
     - ``deny``           → skip, record learning signal
     - ``ban``            → store permanent constraint + record signal
5. **Tool execution** — await ``tool.ainvoke(args)``, log timing.
6. **Result sanitisation** — strip oversized base64 payloads before
   storing in the LangGraph state (see helpers.tool_history).
7. **Error capture** — on exception, record a learning signal then
   surface the error as a tool result so the loop keeps moving.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.agent.helpers.message_sanitizer import _tool_result
from app.agent.helpers.tool_history import _sanitize_tool_result_for_history
from app.agent.state import AgentState
from app.agent.tool_sets import GOOGLE_TOOLS, USER_ID_TOOLS
from app.services.background_tasks import spawn
from app.services.hitl_manager import get_hitl_manager
from app.services.memory_manager import get_memory_manager
from app.services.security_filter import (
    ALWAYS_CRITICAL_TOOLS,
    INSTRUCTION_ARG_KEYS,
    SecurityFilter,
)

logger = logging.getLogger(__name__)


async def tool_node(state: AgentState) -> dict:
    from app.skills import get_skill_registry

    last_message = state["messages"][-1]
    user_id = state.get("user_id", "")
    results = []

    tool_map = {t.name: t for t in get_skill_registry().all_tools}
    # Sprint 4b V2 J7b.2 — make the user's promoted python_tool skills
    # dispatchable. They're bound in agent_node but aren't in the global
    # registry (per-user, by design), so without this the invoke would miss
    # them. Merged WITHOUT shadowing a builtin. No-op when the flag is off.
    from app.services.learning.learned_tools_runtime import merge_into_tool_map
    await merge_into_tool_map(tool_map, user_id)
    sf = SecurityFilter()
    hitl = get_hitl_manager()
    memory = get_memory_manager()

    # ── PII deanonymization for tool args (audit 2026-05-07) ──────────────
    # The user's PII (emails, phones, IBANs) is replaced with placeholders
    # like ``[EMAIL_0]`` BEFORE messages reach the LLM. When the LLM emits a
    # tool call, it uses those placeholders verbatim ("to": "[EMAIL_0]").
    # Without restoring real values here, downstream APIs (Gmail, etc.)
    # receive the placeholder string and reject it as invalid input.
    # We pull the per-conversation SecurityFilter from the shared registry
    # so we get the SAME vault used by chat.py for anonymization.
    _conv_id = state.get("conversation_id") or ""
    _vault_sf = None
    if _conv_id:
        try:
            from app.services.conversation_filters import get_filter as _get_conv_filter
            _vault_sf = _get_conv_filter(_conv_id)
        except Exception as _vault_exc:
            logger.debug("conversation filter lookup failed: %s", _vault_exc)

    def _deanonymize_value(v):
        """Recursively restore PII placeholders in a tool-arg value."""
        if _vault_sf is None:
            return v
        if isinstance(v, str):
            return _vault_sf.deanonymize(v)
        if isinstance(v, dict):
            return {k: _deanonymize_value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_deanonymize_value(x) for x in v]
        return v

    # Sprint 2.7 Jalon 6 — expose the conversation_id to the orchestrate
    # tool via a ContextVar so it can re-anonymize sandbox stdout/stderr
    # using the same SecurityFilter as the rest of the pipeline. The
    # ContextVar is set once for the whole turn and is automatically
    # scoped to this coroutine (no manual reset needed — asyncio
    # propagates ContextVars per task).
    try:
        from app.agent.tools.orchestrate_tool import ORCHESTRATE_CONVERSATION_ID
        ORCHESTRATE_CONVERSATION_ID.set(_conv_id)
    except Exception as _orch_ctx_exc:  # noqa: BLE001
        logger.debug("orchestrate ContextVar set skipped: %s", _orch_ctx_exc)

    # Sprint 4b V2 (composition) — expose the current user to call_tool so a
    # composition python_tool can re-inject Google creds / user_id when it
    # invokes another tool. Set once for the turn (ContextVars are per-task).
    try:
        from app.services.learning.learned_tool_dispatch import LEARNED_TOOL_USER_ID
        LEARNED_TOOL_USER_ID.set(user_id)
    except Exception as _lt_ctx_exc:  # noqa: BLE001
        logger.debug("learned-tool ContextVar set skipped: %s", _lt_ctx_exc)

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        # Deanonymize tool args BEFORE any other processing so HITL preview,
        # logs, and the actual API call all see the real values.
        args = _deanonymize_value(dict(tool_call["args"]))

        # Inject hidden arguments — credentials are fetched from the server-side
        # store (never stored in graph state) to prevent exposure in logs/events.
        if tool_name in GOOGLE_TOOLS:
            from app.services.credential_store import get_credential_store
            _uid = state.get("user_id") or ""
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
            args["user_id"] = state.get("user_id") or ""

        # Build display args — never expose tokens or injected IDs in UI/logs
        _hidden = {"user_google_credentials_json", "user_id"}
        display_args = {k: v for k, v in args.items() if k not in _hidden}
        action_desc = f"Outil: {tool_name} | Arguments: {json.dumps(display_args, ensure_ascii=False)}"
        tc_id = tool_call["id"]

        # ── Vault: resolve vault://label references in args ───────────────
        vault_refs_found = any(
            isinstance(v, str) and v.startswith("vault://")
            for v in args.values()
        )
        if vault_refs_found:
            from app.services.vault_service import get_vault_service
            vault = get_vault_service()
            if vault.is_locked(user_id):
                results.append(_tool_result(
                    "⛔ Vault verrouillé — déverrouillez votre coffre-fort dans Paramètres > Vault "
                    "pour utiliser ce secret.", tc_id
                ))
                continue
            try:
                args, _resolved = await vault.resolve_vault_refs(user_id, args)
                if _resolved:
                    logger.info("Resolved vault refs %s for tool %s", _resolved, tool_name)
            except KeyError as exc:
                results.append(_tool_result(f"⛔ Secret introuvable dans le Vault : {exc}", tc_id))
                continue

        # HITL check. The is_critical keyword scan EXCLUDES deferred-instruction
        # args (prompt/code) — a keyword in "what to run later" (e.g. a
        # scheduled task « supprimer … ») must not gate the harmless CURRENT
        # call. action_desc stays full for the HITL prompt + logs.
        _crit_args = {k: v for k, v in display_args.items() if k not in INSTRUCTION_ARG_KEYS}
        _crit_desc = f"Outil: {tool_name} | Arguments: {json.dumps(_crit_args, ensure_ascii=False)}"
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
                results.append(_tool_result(
                    "Action interdite définitivement et règle de sécurité enregistrée.", tc_id
                ))
                continue
            elif decision == "allow_always":
                # Save user preference so future calls to the same tool by
                # the same user skip the HITL prompt entirely. Then fall
                # through to execute the tool this time. The frontend
                # button "Toujours autoriser" sends this decision ; the
                # backward-compatible "Toujours interdire" sends "ban".
                try:
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
                results.append(_tool_result(
                    "Action non validée dans le délai imparti (ni autorisée, ni "
                    "refusée). L'utilisateur n'a pas répondu à temps."
                    if _is_timeout else
                    "Action refusée par l'utilisateur pour cette occurrence.",
                    tc_id,
                ))
                continue

        # B-12 (revue 2026-06-10) — outils à ressources d'INSTANCE (hôtes
        # SSH de l'admin, serveurs MCP avec secrets env_json admin) :
        # réservés au rôle admin tant qu'il n'y a pas d'ACL per-user.
        from app.services.tool_acl import check_tool_access
        _acl_refusal = await check_tool_access(user_id, tool_name)
        if _acl_refusal:
            results.append(_tool_result(_acl_refusal, tc_id))
            continue

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
                # passes [EMAIL_5] back as a tool arg it's deanonymized above
                # (line ~130). Capped at the filter's 50k ReDoS guard.
                if _vault_sf is not None:
                    # ner_detection=False : contenu MACHINE — regex + vault
                    # seulement, pas de détection NER fraîche (les résultats
                    # web/GitHub/emails sont publics ; les masquer casse
                    # l'agent — retour terrain 2026-06-11).
                    _safe_result = _vault_sf.anonymize(_safe_result, ner_detection=False)
                results.append(_tool_result(_safe_result, tc_id))
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
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
                results.append(_tool_result(_err, tc_id))
        else:
            from langchain_core.messages import ToolMessage
            results.append(ToolMessage(
                content=f"Outil '{tool_name}' non disponible.",
                tool_call_id=tc_id,
            ))

    return {"messages": results}
