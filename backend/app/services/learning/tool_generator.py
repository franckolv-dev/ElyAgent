# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/tool_generator.py
# @brief      Sprint 4b V2 J6 — tier-S generator of @tool Python source.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Generate Python ``@tool`` source via the tier-S LLM (design note J0 §3).

The companion of ``tool_orchestrator``: this asks the tier-S model to
WRITE a tool; the orchestrator VALIDATES it. The system prompt encodes
exactly the constraints the validation gates enforce (composition of
existing tools + pure-compute stdlib, typed signature, docstring,
allow-listed imports) so the generated code passes the chain on the
first or second try.

Model selection is **fully driven by the environment**, not hardcoded.
The generator calls ``get_tier_s_llm()`` which reads ``LLM_TIER_S_CHAIN``:

    LLM_TIER_S_CHAIN=deepseek            # cheap (~30x cheaper than Opus)
    LLM_TIER_S_CHAIN=mistral             # EU sovereignty
    LLM_TIER_S_CHAIN=anthropic,deepseek  # Opus primary, DeepSeek fallback (default)

plus per-provider model overrides (LLM_TIER_S_DEEPSEEK_MODEL=deepseek-chat,
LLM_TIER_S_MAX_TOKENS, LLM_TIER_S_MONTHLY_BUDGET_USD). Usage is recorded
under purpose ``tool_generator`` so V2 generation cost is tracked
separately from V1 playbook creation.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.learning.tier_s import (
    estimate_cost_usd,
    get_tier_s_llm,
    record_tier_s_usage,
)

logger = logging.getLogger(__name__)


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are ELY's autonomous TOOL writer. ELY is a sovereign AI agent
(FastAPI + LangGraph). When ELY repeatedly needs a capability it can only
get by chaining several existing tools + some pure data work, you write a
new reusable Python `@tool` that packages that workflow into one call.

V2 SCOPE — read carefully, the validator WILL reject violations
================================================================
The tool you write is COMPOSITION + PURE COMPUTATION only:
  - It MAY call other already-registered ELY tools — ONLY those in the
    AVAILABLE TOOLS list — via the provided `call_tool` helper (see
    "Composing other tools" below), and combine/transform their results.
  - It MAY use pure-compute stdlib: math, json, re, datetime, statistics,
    itertools, collections, decimal, functools, string, typing.
  - It MUST NOT do any I/O of its own: NO os, sys, subprocess, socket,
    shutil, pathlib, urllib, requests, http, open(), eval/exec/compile,
    __import__, getattr/setattr, or dunder attribute access. (New external
    integrations are a future capability behind a sandbox — not now.)

Composing other tools
---------------------
⚠️ READ THIS FIRST — the #1 cause of broken generated tools:

    **`call_tool` RETURNS A HUMAN-READABLE `str`. NOT a dict. NOT a list.**

Every ELY tool is written for an LLM to read, so it returns prose:

    "3 fichier(s):\\n\\n• rapport.pdf (application/pdf)\\n  ID: 1AbC…"
    "Aucun fichier trouvé."
    "Erreur Drive: quota exceeded"

So this code is WRONG and crashes at runtime with
``'str' object has no attribute 'get'`` — the validator will NOT catch it,
only the user will, in production:

    files = await call_tool("drive_list_files", {"query": q})
    if len(files) == 0: ...        # ✗ len() of a string — always > 0
    file_id = files[0].get("id")   # ✗ files[0] is a CHARACTER

Treat every result as text you must READ:

    from app.services.learning.learned_tool_dispatch import call_tool

    @tool
    async def my_tool(query: str) -> str:
        \"\"\"…\"\"\"
        listing = await call_tool("drive_list_files", {"query": query})
        if "Aucun fichier" in listing or listing.startswith("Erreur"):
            return f"Rien trouvé pour {query!r}."
        match = re.search(r"ID\\s*:\\s*(\\S+)", listing)   # parse the text
        if not match:
            return f"Impossible d'extraire un ID de : {listing[:200]}"
        return await call_tool("drive_copy_file", {"file_id": match.group(1)})

Rules:
  - `call_tool(name, args)` is the ONLY way to reach another tool. NEVER
    import a tool function directly, and never invent a tool name.
  - The return value is a `str`. ALWAYS. Parse it with `re` / `in` /
    `splitlines()`. NEVER call `.get()`, `.keys()`, `[0]["x"]` or
    `json.loads()` on it, and never trust `len()` as an item count.
  - A tool result is also how ERRORS come back — they are strings too, not
    exceptions. Check for "Erreur", "Aucun", "non connecté" before using a
    result, and return a clear message instead of crashing.
  - Prefer NOT composing at all when a single tool already does the job.
    A chain of 3 text-parsing calls is 3 chances to break.
  - Compose ONLY tools from the AVAILABLE TOOLS list — it already excludes
    destructive / sensitive tools (delete, send, share, ssh…), which CANNOT
    be composed and will raise at runtime.
  - A tool that uses `call_tool` MUST be `async def` and `await` every call.
  - A PURE computation tool (no `call_tool`) stays a normal sync `def`.
  - You don't know each tool's exact argument names — pass the obvious ones;
    if a call is wrong, the validation feedback tells you what to fix.

Output contract
---------------
Reply with EXACTLY one fenced ```python code block and NOTHING else
(no prose before or after). The module MUST be:

```python
from __future__ import annotations

# allowed imports only (see scope above) + the scaffolding:
from langchain_core.tools import tool
# from app.services.learning.learned_tool_dispatch import call_tool  # only if you compose tools
# from typing import Annotated         # if you need injected args
# from langchain_core.tools import InjectedToolArg

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,                 # pick the most fitting Domain
    skill_name="snake_case_slug",
    skill_display_name="Human Readable Name",
    skill_description="One sentence on what it does.",
    skill_icon="🧩",
    enabled_by_default=False,
)
@tool
def snake_case_slug(arg: str) -> str:
    \"\"\"Precise docstring: tell the LLM WHEN to call this tool.

    A tool with a vague docstring gets called never or constantly.
    \"\"\"
    ...
    return result
```

Hard requirements (the validator checks every one)
---------------------------------------------------
- `@register` ABOVE `@tool` (decorator order matters).
- EVERY parameter is type-annotated. The return type is annotated.
- A non-empty docstring describing WHEN to call the tool.
- Serialisable return value (str / int / list / dict of primitives).
- Use ONLY tool names from the AVAILABLE TOOLS list — never invent one.
- To call another tool: `async def` + `await call_tool("name", {...})` —
  never call a tool function by its name directly.
- Keep it small and single-purpose.
"""


# ── Prompt io (Sprint 4b V3 J7 — v1.16.0) ───────────────────────────────────
# Même writer, contrat différent : l'outil tourne DANS LA SANDBOX (subprocess
# python -S, réseau via proxy egress filtrant, secrets injectés par le
# wrapper). Le validateur correspondant est validate_tool_source(profile="io")
# (7 étages, J5) + le gate async check_secrets_exist côté créateur.

_SYSTEM_PROMPT_IO = """\
You are ELY's autonomous TOOL writer. ELY is a sovereign AI agent
(FastAPI + LangGraph). When ELY needs a genuinely NEW external integration
(a public HTTP API, a web page to parse), you write a reusable Python
`@tool` that runs inside ELY's SANDBOX with real — but strictly declared —
network access.

V3 IO SCOPE — read carefully, the validator WILL reject violations
===================================================================
Your tool runs in an isolated sandbox subprocess. It:
  - MAY do real HTTP(S) calls with `httpx` — ONLY to the domains you
    declare in `network_allow` (every domain must come from the ALLOWED
    EGRESS DOMAINS list in the task message; anything else is refused by
    the egress proxy at runtime).
  - MAY parse responses with `beautifulsoup4` (`from bs4 import
    BeautifulSoup`) and `lxml` — declare what you import in `requires`.
  - MAY use pure-compute stdlib: math, json, re, datetime, statistics,
    itertools, collections, decimal, functools, string, typing.
  - reads API keys with `get_secret("vault_label")` — this helper is
    INJECTED by the sandbox at runtime: do NOT import it, do NOT define
    it. Declare every label you read in `requires_secrets`. NEVER hardcode
    a credential, NEVER return or log a secret value.
  - MUST NOT: import os/sys/subprocess/socket/shutil/pathlib/urllib/
    requests, call open()/eval()/exec()/compile()/__import__, touch dunder
    attributes, or call other ELY tools (`call_tool` does NOT exist in the
    sandbox — an io tool is self-contained).

Declarations contract (the three V3 kwargs on @register)
---------------------------------------------------------
    network_allow   = ["api.example.com"]   # exact domains you call
    requires        = ["httpx"]              # pip distributions you import
    requires_secrets = ["my_api_key"]        # Vault labels you get_secret()

Declare EXACTLY what you use — no more (gates reject undeclared usage and
unused declarations are confusing for the human reviewer), no less.

Output contract
---------------
Reply with EXACTLY one fenced ```python code block and NOTHING else.
The module MUST follow this shape:

```python
from __future__ import annotations

import httpx
from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.RESEARCH,                  # pick the most fitting Domain
    skill_name="snake_case_slug",
    skill_display_name="Human Readable Name",
    skill_description="One sentence on what it does.",
    skill_icon="🌐",
    enabled_by_default=False,
    network_allow=["api.example.com"],
    requires=["httpx"],
    requires_secrets=["example_api_key"],    # omit if no secret needed
)
@tool
def snake_case_slug(query: str) -> dict:
    \"\"\"Precise docstring: tell the LLM WHEN to call this tool.\"\"\"
    api_key = get_secret("example_api_key")  # injected — do not import
    r = httpx.get(
        "https://api.example.com/v1/search",
        params={"q": query, "key": api_key},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()
```

Hard requirements (the validator checks every one)
---------------------------------------------------
- `@register` ABOVE `@tool`; the three V3 kwargs present and consistent
  with the code (declared domains/libs/labels = used ones).
- The function is a plain SYNC `def` (the sandbox runs it directly).
- EVERY parameter and the return type are annotated; non-empty docstring
  saying WHEN to call it.
- `httpx` calls always set an explicit `timeout` and handle non-200
  responses (`raise_for_status()` or a clear error return).
- Serialisable, reasonably sized return value (str / int / list / dict of
  primitives) — never raw bytes, never a full HTML page (extract what's
  useful).
- Keep it small and single-purpose.
"""


def _format_tool_list(tools: list[str]) -> str:
    if not tools:
        return "(no tools available — write a pure-computation tool only)"
    groups: dict[str, list[str]] = {}
    for name in tools:
        prefix = name.split("_", 1)[0] if "_" in name else "misc"
        groups.setdefault(prefix, []).append(name)
    return "\n".join(
        f"  {prefix}: {', '.join(sorted(names))}" for prefix, names in sorted(groups.items())
    )


def compose_user_prompt(
    task_description: str,
    *,
    available_tools: list[str],
    prior_errors: str | None = None,
    profile: str = "pure",
    allowed_egress: list[str] | None = None,
    available_secret_labels: list[str] | None = None,
) -> str:
    """Build the user message. ``prior_errors`` (a validation report
    summary) is included on retries so the model fixes the exact failure.

    ``profile="io"`` (J7) : remplace la liste d'outils composables par le
    contexte sandbox — domaines egress autorisés (la source de vérité
    Squid) et labels Vault disponibles pour ce user.
    """
    parts = [
        "Write a tool for this recurring need:\n",
        task_description.strip(),
    ]
    if profile == "io":
        if allowed_egress:
            parts.append(
                "\n\nALLOWED EGRESS DOMAINS (declare network_allow as a "
                "subset of EXACTLY these — any other domain is refused by "
                "the proxy at runtime; if the API you need is missing, say "
                "so in a comment instead of inventing a domain):\n  "
                + " ".join(allowed_egress)
            )
        else:
            parts.append(
                "\n\nALLOWED EGRESS DOMAINS: (list unavailable — declare the "
                "exact domains your code calls; the admin will review them)"
            )
        if available_secret_labels:
            parts.append(
                "\n\nAVAILABLE VAULT SECRET LABELS for this user (use "
                "get_secret() ONLY with labels from this list):\n  "
                + ", ".join(sorted(available_secret_labels))
            )
        else:
            parts.append(
                "\n\nAVAILABLE VAULT SECRET LABELS: (none provisioned — "
                "prefer a keyless API; if a key is unavoidable, declare the "
                "label you need in requires_secrets and the admin will "
                "provision it before promotion)"
            )
    else:
        parts.append(
            "\n\nAVAILABLE TOOLS (compose ONLY these; inventing a tool name "
            "is forbidden):\n" + _format_tool_list(available_tools)
        )
    if prior_errors:
        parts.append(
            "\n\nYOUR PREVIOUS ATTEMPT FAILED VALIDATION. Fix exactly this and "
            "resend the full corrected module:\n"
            + prior_errors.strip()
        )
    parts.append(
        "\n\nReply with ONLY the fenced ```python block — the complete module, "
        "no commentary."
    )
    return "".join(parts)


# ── Response parser ────────────────────────────────────────────────────────────


def parse_tool_response(raw: str) -> str | None:
    """Extract the Python source from the tier-S reply.

    Tolerant: handles a ```python fenced block, a bare ``` block, or — as a
    last resort — raw source with no fences. Returns None if there's
    nothing that looks like source.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    if "```" in text:
        start = text.find("```")
        after = text[start + 3:]
        # drop an optional language tag on the same line (```python)
        nl = after.find("\n")
        if nl != -1:
            first_line = after[:nl].strip().lower()
            if first_line in ("python", "py", ""):
                after = after[nl + 1:]
        end = after.find("```")
        block = after[:end] if end != -1 else after
        block = block.strip()
        return block or None

    # No fences — accept it if it at least looks like a module
    if "def " in text or "import " in text:
        return text
    return None


# ── Available tools (ground truth) ─────────────────────────────────────────────


def get_available_tool_names() -> list[str]:
    """Names of tools both registered and in the default profile, RESTRICTED
    to the composable (safe) subset — the composition surface offered to the
    generator. Destructive / HITL-gated tools are excluded (call_tool refuses
    them at runtime, so never invite them). Best-effort: returns [] on any
    registry hiccup (the prompt copes)."""
    try:
        from app.services.learning.learned_tool_dispatch import composable_tool_names
        from app.services.learning.skill_creator import _get_available_tool_names

        composable = composable_tool_names()
        return [n for n in _get_available_tool_names() if n in composable]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tool_generator: tool names lookup failed (%s)", exc)
        return []


# ── Public API ─────────────────────────────────────────────────────────────────


async def generate_tool_source(
    *,
    task_description: str,
    user_id: str = "",
    available_tools: list[str] | None = None,
    prior_errors: str | None = None,
    profile: str = "pure",
    allowed_egress: list[str] | None = None,
    available_secret_labels: list[str] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Ask the tier-S LLM (model per ``LLM_TIER_S_CHAIN``) to write a tool.

    Returns ``(source, info)``. ``source`` is the parsed Python module or
    None on failure. ``info`` carries the picked provider, token/cost
    accounting, and a status string. Never raises.

    ``profile="io"`` (Sprint 4b V3 J7) : enseigne le contrat sandbox
    (egress déclaré, secrets via ``get_secret``, libs bornées) au lieu du
    contrat composition V2.
    """
    info: dict[str, Any] = {"status": "pending", "profile": profile}
    tools = available_tools if available_tools is not None else get_available_tool_names()
    info["available_tool_count"] = len(tools)

    llm, pick = await get_tier_s_llm()
    if llm is None or pick == "none":
        info["status"] = "no_provider"
        info["error"] = "No tier-S provider configured (set LLM_TIER_S_CHAIN + API key)."
        return None, info
    info["provider_pick"] = pick

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(
                content=_SYSTEM_PROMPT_IO if profile == "io" else _SYSTEM_PROMPT
            ),
            HumanMessage(
                content=compose_user_prompt(
                    task_description,
                    available_tools=tools,
                    prior_errors=prior_errors,
                    profile=profile,
                    allowed_egress=allowed_egress,
                    available_secret_labels=available_secret_labels,
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        raw = getattr(response, "content", "") or ""
    except Exception as exc:
        info["status"] = "llm_call_failed"
        info["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("tool_generator: tier-S call failed: %s", exc)
        return None, info

    # Usage accounting (best-effort) — purpose distinguishes V2 codegen cost.
    try:
        usage_meta = getattr(response, "usage_metadata", None) or {}
        in_tok = int(usage_meta.get("input_tokens") or 0)
        out_tok = int(usage_meta.get("output_tokens") or 0)
        model_name = (
            getattr(response, "response_metadata", {}).get("model_name")
            or getattr(llm, "model", None)
            or getattr(llm, "model_name", None)
            or "tier-s"
        )
        if in_tok or out_tok:
            await record_tier_s_usage(
                user_id=user_id,
                model=model_name,
                provider=pick,
                input_tokens=in_tok,
                output_tokens=out_tok,
                purpose="tool_generator",
            )
            info["tokens_in"] = in_tok
            info["tokens_out"] = out_tok
            info["estimated_cost_usd"] = estimate_cost_usd(model_name, in_tok, out_tok)
    except Exception:  # pragma: no cover - accounting must never break gen
        pass

    source = parse_tool_response(raw)
    if source is None:
        info["status"] = "parse_failed"
        info["raw_excerpt"] = raw[:300]
        return None, info

    info["status"] = "generated"
    return source, info
