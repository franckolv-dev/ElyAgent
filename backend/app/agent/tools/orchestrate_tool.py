# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/orchestrate_tool.py
# @brief      Tool ``orchestrate`` — Programmatic Tool Calling (Sprint 2.7).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    0.1.0-skeleton
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
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
from contextvars import ContextVar
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from app.services.llm_deadline import ainvoke_with_deadline
from app.skills.base import Domain
from app.skills.decorator import register

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Conversation-id passthrough (Sprint 2.7 — Jalon 6)
# ──────────────────────────────────────────────────────────────────────
#
# The orchestrate sandbox needs the per-conversation SecurityFilter to
# re-anonymize the sandbox's stdout/stderr before returning it to the
# main LLM — otherwise PII pulled from Gmail/Drive inside the script
# leaks back into the LLM context in cleartext.
#
# We can't add ``conversation_id`` as a LangChain InjectedToolArg
# without modifying every tool's injection logic across the codebase,
# so we use a ContextVar set by ``tool_node`` (in app/agent/nodes.py)
# right before invoking any tool. The tool reads the value here and
# looks up the SecurityFilter through the registry.
#
# When the context var is unset (e.g. called outside the agent graph
# in a test), the tool falls back to running WITHOUT anonymization —
# safe because in that case there's no LLM downstream consuming the
# result either.

ORCHESTRATE_CONVERSATION_ID: ContextVar[str] = ContextVar(
    "orchestrate_conversation_id", default=""
)


@register(
    domain=Domain.UNIVERSAL,
    skill_name="orchestrate",
    skill_display_name="Orchestration Python sandboxée",
    skill_description=(
        "Exécute un script Python dans un sandbox isolé qui peut chaîner "
        "plusieurs tools en lecture seule (Gmail, Drive, Calendar, web, "
        "knowledge, mémoire, GitHub) en un seul tour. Économies massives "
        "de tokens pour les workflows multi-tools analytiques. "
        "Mode `intent` : décris ce que tu veux, un modèle frontier écrit le "
        "script à ta place. Mode `code` : fournis ton script Python directement."
    ),
    skill_icon="🛠️",
    enabled_by_default=True,
    skill_version="0.2.0",
)
@tool
async def orchestrate(
    intent: str = "",
    code: str = "",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Run an orchestration in a sandboxed Python environment.

    Two modes — provide EITHER ``intent`` OR ``code`` (not both).

    Mode A — INTENT (recommended for non-frontier models)
    ------------------------------------------------------
    Describe in natural language what you want the orchestration to do.
    A tier C model (Mistral Large 3 / DeepSeek v4-pro / Anthropic) writes
    the Python script behind the scenes, the sandbox executes it, and
    you receive the stdout + meta. You don't need to know Python.

    Example::

        orchestrate(intent="Pour les 3 derniers projets en mémoire, "
                    "récupère leurs stats GitHub et fais un résumé hebdo")

    Mode B — CODE (frontier models or known patterns)
    -------------------------------------------------
    Provide the full Python script yourself. Use this when you already
    know the exact sequence of stub calls you want.

    USE THIS TOOL WHEN you need to chain multiple read-only tool calls
    (Gmail list, Drive read, web search, knowledge search, GitHub stats,
    past conversations lookup, etc.) and synthesize a single answer.
    Instead of issuing 10 separate tool_calls (each polluting your
    context with the full tool_result), you write ONE Python script
    that orchestrates everything locally and prints the final summary.

    Available functions inside the sandbox — USE THESE NAMES EXACTLY,
    any other name will crash the sandbox (the stub module is dynamically
    generated from this exact list at every run):

        Gmail (read):
            gmail_list_emails, gmail_read_email, gmail_search_for_cleanup
        Calendar (read):
            calendar_list_events
        Drive (read):
            drive_list_files, drive_read_file
        Web (read):
            web_search
        Knowledge / mémoire (read):
            knowledge_search, knowledge_list, memory_search, memory_recent,
            search_past_conversations_tool
        GitHub (read):
            github_repo_stats, github_traffic_stats
        System (read):
            system_list_scheduled_tasks

    None of the stubs takes ``user_id`` — it's injected server-side.
    If you don't remember the exact name of a stub, use ``intent=`` and
    let a tier C model write the script for you.

    Google accounts: the sandbox only reaches the user's DEFAULT Google
    account. To search a specific or secondary linked account, do NOT use
    orchestrate — call ``drive_list_files`` / ``gmail_list_emails`` /
    ``calendar_list_events`` directly with ``account="<alias>"`` (those
    direct tools support multi-account; the sandbox stubs don't).

    Plus three helpers (also in ``ely_tools``):
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
        - The task targets a SPECIFIC or NON-DEFAULT Google account (e.g.
          searching a second linked account, or "both drives"). The sandbox
          only reaches the default account — call the Google tools directly
          with ``account="<alias>"`` instead.
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
    # Diagnostic log — surface what the LLM actually decided to pass.
    # Helps catch frontier models that ignore the intent= mode and write
    # their own script in code=, vs smaller models that delegate via
    # intent. INFO level so it shows up in normal prod logs.
    logger.info(
        "orchestrate: invoked user=%s intent=%.120r code_len=%d code_head=%.80r",
        user_id, intent or "", len(code or ""), (code or "")[:80],
    )

    if not user_id:
        return "Erreur interne : user_id manquant."
    if not (intent and intent.strip()) and not (code and code.strip()):
        return (
            "Erreur : fournis soit `intent` (description haut-niveau de "
            "ce que tu veux faire, le script sera écrit par un modèle "
            "frontier) soit `code` (script Python complet à exécuter)."
        )

    from app.services.orchestrate_runner import OrchestrateRunner

    # Option C — if no code provided, delegate script generation to tier C.
    # Frontier models can still call orchestrate(code=...) directly; smaller
    # models call orchestrate(intent=...) and let the tier C model write
    # the script for them.
    if not (code and code.strip()):
        try:
            code = await _generate_script_from_intent(intent.strip())
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "orchestrate: tier C script generation failed for user=%s", user_id,
            )
            return (
                f"Erreur de génération du script via le tier C : "
                f"{type(exc).__name__}: {exc}. "
                "Tu peux retomber sur des tool_calls directs."
            )
        if not code.strip():
            return (
                "Erreur : le tier C a renvoyé un script vide. "
                "Reformule ton intent ou fournis directement `code=...`."
            )
        logger.info(
            "orchestrate: tier C generated %d-byte script for user=%s "
            "(intent=%.80r)",
            len(code), user_id, intent[:80],
        )

    runner = OrchestrateRunner(user_id=user_id)
    try:
        result = await runner.run(code=code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("orchestrate: runner failed for user=%s", user_id)
        return (
            f"Erreur d'exécution du sandbox : {type(exc).__name__}: {exc}. "
            "Si le problème persiste, retombe sur des tool_calls directs."
        )

    # Diagnostic — surface what the sandbox actually returned so we can
    # debug why scripts fail at 0.21s. Logged at INFO since this is
    # useful in prod for early bench data.
    logger.info(
        "orchestrate: run finished user=%s exit_code=%d duration=%.2fs "
        "tools_dispatched=%s truncated=%s",
        user_id, result.exit_code, result.duration_seconds,
        result.tools_dispatched, result.truncated,
    )
    logger.info(
        "orchestrate: stdout_head=%.500r stderr_head=%.300r",
        result.stdout, result.stderr,
    )

    # Sprint 2.7 Jalon 6 — re-anonymize stdout/stderr before they reach
    # the main LLM. The sandbox receives DEANONYMIZED args (tool_node
    # already restored real values for the script to work against the
    # real Gmail/Drive APIs), and tool results pulled inside the sandbox
    # contain real PII. Without this step, that PII would round-trip
    # back into the LLM's tool_message context — defeating the whole
    # anonymization pipeline. Re-running the same SecurityFilter
    # preserves placeholder stability: an email mapped to <EMAIL_3>
    # earlier in the conversation stays <EMAIL_3> in this turn too.
    conv_id = ORCHESTRATE_CONVERSATION_ID.get()
    if conv_id:
        try:
            from app.services.conversation_filters import get_filter
            sf = get_filter(conv_id)
            # ner_detection=False : sorties machine (cf. tool_node).
            if result.stdout:
                result.stdout = sf.anonymize(result.stdout, ner_detection=False)
            if result.stderr:
                result.stderr = sf.anonymize(result.stderr, ner_detection=False)
        except Exception as anon_exc:  # noqa: BLE001
            logger.warning(
                "orchestrate: stdout/stderr re-anonymization skipped (%s) — "
                "raw PII may leak to the main LLM. Investigate.",
                anon_exc,
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


# ──────────────────────────────────────────────────────────────────────
# Tier C delegation — Option C of Sprint 2.7
# ──────────────────────────────────────────────────────────────────────


_SCRIPT_GENERATION_SYSTEM_PROMPT = """\
Tu es un assistant qui écrit des scripts Python pour le sandbox `orchestrate` d'ELY.

Tu reçois un intent utilisateur en langage naturel. Tu produis UN SCRIPT \
Python complet qui utilise UNIQUEMENT les fonctions stubs ci-dessous, \
importables via `from ely_tools import ...` :

{stubs}

Helpers QoL également disponibles dans `ely_tools` :
- `json_parse(text)` : `json.loads` tolérant aux \\t \\n dans les strings
- `shell_quote(s)` : alias de `shlex.quote`
- `retry(fn, max_attempts=3, delay=2)` : retry avec backoff exponentiel

Règles strictes :
1. Réponds UNIQUEMENT par du code Python. PAS de markdown, PAS de blocs ``` , PAS d'explications.
2. Imports AUTORISÉS uniquement : `from ely_tools import <noms>`. Pas d'imports stdlib (le sandbox tourne en `python -S` et le PYTHONPATH est minimal).
3. Le script doit terminer par UN OU PLUSIEURS `print(...)` synthétiques — c'est tout ce que le modèle appelant recevra.
4. Pas de boucle infinie. Pas d'I/O réseau direct (les RPC parlent déjà aux services).
5. Sois concis : 20-40 lignes maximum. Une boucle `for` propre vaut mieux que 10 appels séquentiels.
6. Les stubs ne prennent JAMAIS `user_id` — il est injecté côté serveur.

Conventions importantes (à respecter pour éviter des bugs runtime) :
7. LES DEFAULTS SONT VALIDES. La plupart des stubs marchent SANS arguments — les valeurs par défaut sont configurées côté serveur (GITHUB_DEFAULT_REPO, compte Gmail principal, etc.). N'INVENTE PAS de valeurs (« Franck/main-project », « user@example.com »…). Si tu n'es pas sûr d'une valeur, appelle SANS arg. Les stubs Google (drive/gmail/calendar) interrogent UNIQUEMENT le compte par défaut — ils ne prennent pas d'argument `account`.
8. LES STUBS RETOURNENT DES STRINGS DESCRIPTIVES. Tu peux les `print(...)` DIRECTEMENT. Ils ne retournent PAS de dict — n'utilise PAS `result.get('key')`, `result['key']`, ni de json.loads sur leur sortie. Si tu as besoin de structure, parse la string toi-même (les stubs documentent leur format).
9. ENCAPSULE les appels dangereux dans try/except si tu fais une boucle, mais sinon laisse remonter l'erreur — c'est plus debuggable côté caller.

Exemple de script working :

    from ely_tools import github_repo_stats, github_traffic_stats, memory_recent, search_past_conversations_tool

    repo = github_repo_stats()              # pas d'args : utilise GITHUB_DEFAULT_REPO
    traffic = github_traffic_stats()        # pareil
    projects = memory_recent(category="project", limit=5)
    past = search_past_conversations_tool(query="sprint en cours")

    print("=== Résumé hebdo dev ===\\n")
    print("## GitHub repo\\n" + repo + "\\n")
    print("## Trafic 14j\\n" + traffic + "\\n")
    print("## Projets récents\\n" + projects + "\\n")
    print("## Conversations passées\\n" + past)
"""


async def _generate_script_from_intent(intent: str) -> str:
    """Ask the tier C LLM to write a Python script that satisfies ``intent``.

    Used when the orchestrate tool is invoked with ``intent="..."`` (Option C).
    Lets non-frontier callers (tier A/B) benefit from the sandbox without
    needing to write Python themselves — a tier C model does that for them.

    Args:
        intent: free-text description of what the script should accomplish.

    Returns:
        A bare Python script (markdown fences stripped if present).

    Raises:
        RuntimeError: if the tier C LLM is unavailable.
        Exception: if the LLM call itself fails (propagated, caught by the
            tool wrapper).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.llm_provider import ComplexityTier, get_llm_for_tier
    from app.services.orchestrate_runner import SANDBOX_ALLOWED_TOOLS_V1
    from app.services.orchestrate_stubs import describe_allowed_tools_for_prompt

    llm = get_llm_for_tier(ComplexityTier.COMPLEX)
    if llm is None:
        raise RuntimeError(
            "tier C LLM unavailable — set a model in Settings → Routage tier C"
        )

    stubs_desc = describe_allowed_tools_for_prompt(SANDBOX_ALLOWED_TOOLS_V1)
    system_msg = SystemMessage(
        content=_SCRIPT_GENERATION_SYSTEM_PROMPT.format(stubs=stubs_desc)
    )
    user_msg = HumanMessage(
        content=f"Intent utilisateur :\n\n{intent}\n\nProduis le script Python."
    )

    response = await ainvoke_with_deadline(
        llm, [system_msg, user_msg], tier="complex", surface="orchestrate")
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        # Some providers return content as a list of content blocks.
        raw = "".join(
            (b.get("text", "") if isinstance(b, dict) else str(b))
            for b in raw
        )
    return _strip_markdown_fences(str(raw).strip())


def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing ``` or ```python markdown fences if present.

    Tier C LLMs sometimes wrap their output in fences despite the prompt
    asking for raw Python. Strip defensively rather than failing the run.
    """
    code = text.strip()
    # Leading fence with optional language tag
    if code.startswith("```"):
        # Drop the first line entirely (handles ```python, ```py, plain ```)
        first_newline = code.find("\n")
        code = code[first_newline + 1:] if first_newline != -1 else ""
    # Trailing fence
    if code.endswith("```"):
        code = code[: -3].rstrip()
    return code
