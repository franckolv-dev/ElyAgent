# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/orchestrate_tool.py
# @brief      Tool ``orchestrate`` — Programmatic Tool Calling (Sprint 2.7).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    0.1.0-skeleton
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Tool ``orchestrate`` — script Python sandboxé qui chaîne N tools.

Pattern d'inspiration : Hermes Agent ``tools/code_execution_tool.py``.
Voir ``docs/external-references/hermes-zero-context-cost-turns.md``
pour la design note complète. Implémentation maison adaptée à ELY.

Tier policy
===========
Ce tool est **réservé au tier C** (gros modèles capables d'écrire du
Python correct — Mistral Large 3, DeepSeek v4-pro, Anthropic). Le
filtrage tier_c_only sera ajouté dans ``toolset_profiles.py`` au
Jalon 5. Sur tier A (Ministral 3B), le tool est masqué — le LLM ne le
voit même pas, donc pas de risque de script buggé.

Status : SKELETON
=================
Le tool est enregistré via ``@register`` (pour que l'auto-discovery
du Sprint 2 le capte), mais l'exécution lève ``NotImplementedError``
en attendant les Jalons 2-4.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


@register(
    domain=Domain.UNIVERSAL,
    skill_name="orchestrate",
    skill_display_name="Orchestration Python sandboxée",
    skill_description=(
        "Exécute un script Python dans un sandbox isolé qui peut chaîner "
        "plusieurs tools en lecture seule (Gmail, Drive, Calendar, web, "
        "knowledge, mémoire, GitHub) en un seul tour. Économies massives "
        "de tokens pour les workflows multi-tools analytiques."
    ),
    skill_icon="🛠️",
    enabled_by_default=True,
    skill_version="0.1.0",
)
@tool
async def orchestrate(
    code: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Run a Python script inside a sandboxed environment that can call N read-only tools.

    USE THIS TOOL WHEN you need to chain multiple read-only tool calls
    (Gmail list, Drive read, web search, knowledge search, GitHub stats,
    past conversations lookup, etc.) and synthesize a single answer.
    Instead of issuing 10 separate tool_calls (each polluting your
    context with the full tool_result), you write ONE Python script
    that orchestrates everything locally and prints the final summary.

    Available functions inside the sandbox (read-only):
        - gmail_list_emails, gmail_read_email, gmail_search_for_cleanup
        - calendar_list_events
        - drive_list_files, drive_read_file_content
        - web_search, web_get_text
        - knowledge_search, knowledge_list
        - memory_search, memory_recent, search_past_conversations_tool
        - github_repo_stats, github_traffic_stats

    Plus three helpers:
        - json_parse(text)       — tolerant JSON parser
        - shell_quote(s)         — shlex.quote alias
        - retry(fn, attempts, delay) — exponential backoff retry

    Example call (the LLM writes this as the `code` argument):

        emails = gmail_list_emails(query="from:shein.com", max_results=50)
        attachments = []
        for e in emails:
            content = gmail_read_email(message_id=e["id"])
            if "facture" in content.lower():
                attachments.append(e["subject"])
        print(f"Trouvé {len(attachments)} factures SHEIN:")
        for s in attachments:
            print(f"  - {s}")

    DO NOT USE THIS TOOL WHEN:
        - The task requires only 1-2 tool calls (overhead not worth it).
        - The task involves destructive actions (gmail_trash_*,
          drive_delete_*, gmail_send_*, notes_*). Those tools are NOT
          exposed in the sandbox — call them directly outside orchestrate
          so the HITL flow kicks in.
        - You are running on a small model (Ministral 3B) — this tool
          is masked at tier A/B and only available at tier C.

    Args:
        code: A complete, self-contained Python script. The last line
            (or the last `print(...)` calls) become the result returned
            to you. Stdout is captured up to 50 KB (head+tail).

    Returns:
        The script's stdout (truncated if needed), prefixed by a short
        meta line indicating which tools were actually dispatched. If
        the script raised or timed out, the error message + partial
        stdout are returned.
    """
    if not user_id:
        return "Erreur interne : user_id manquant."
    if not code or not code.strip():
        return "Erreur : le script est vide. Fournis du code Python à exécuter."

    from app.services.orchestrate_runner import OrchestrateRunner

    runner = OrchestrateRunner(user_id=user_id)
    try:
        result = await runner.run(code=code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("orchestrate: runner failed for user=%s", user_id)
        return (
            f"Erreur d'exécution du sandbox : {type(exc).__name__}: {exc}. "
            "Si le problème persiste, retombe sur des tool_calls directs."
        )

    # The agent node passes `result.tools_dispatched` to the
    # completion_guard via the `tools_called_via_sandbox` channel (§4.4).
    # Here we render a string for the LLM that combines stdout + a
    # short metadata header. Keeping the meta short so it doesn't dilute
    # the script's own conclusion (typically the last print).
    meta_parts: list[str] = []
    if result.tools_dispatched:
        meta_parts.append(
            f"tools={','.join(result.tools_dispatched)} "
            f"(count={len(result.tools_dispatched)})"
        )
    if result.exit_code != 0:
        meta_parts.append(f"exit={result.exit_code}")
    if result.truncated:
        meta_parts.append(f"⚠️ {result.truncation_reason}")
    if result.stderr.strip():
        stderr_preview = result.stderr.strip().splitlines()[-1][:200]
        meta_parts.append(f"stderr_last={stderr_preview!r}")

    meta_line = " | ".join(meta_parts) if meta_parts else "no tools called"
    return f"[orchestrate {meta_line}]\n{result.stdout}"
