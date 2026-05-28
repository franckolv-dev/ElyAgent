# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_e2e.py
# @brief      Test E2E hermétique du Sprint 2.7 — Jalon 7a.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Test E2E hermétique du sandbox `orchestrate`.

Exerce **tout le chemin de production**, sans mock à l'intérieur du
runner :
    1. Le registry est bootstrappé (`register_all`) comme en prod.
    2. Le `_build_default_dispatcher` est utilisé tel quel (pas
       d'injection de dispatcher de test).
    3. Le runner crée un vrai tmpdir, un vrai socket UDS, un vrai
       subprocess Python avec env scrubbée, vraie isolation.
    4. Le script invoque plusieurs tools dans une boucle.
    5. Le RPC dispatch atterrit sur les vrais @tool du registry — mais
       leur ``coroutine`` interne a été monkey-patchée pour retourner
       un stub déterministe (pas de DB / pas de réseau / pas de
       Google credentials).

C'est la définition d'un E2E hermétique : tout est réel **sauf** les
appels aux services externes. Si ce test passe, le bench (Jalon 7b)
peut commencer sans crainte d'un bug d'archi déguisé en mauvais score.
"""
from __future__ import annotations

import pytest


# ──────────────────────────────────────────────────────────────────────
# Fixture — bootstrap real registry, patch tools we'll exercise
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def patched_registry_tools(monkeypatch):
    """Bootstrap the registry, then patch 4 allow-list V1 tools to
    return deterministic stubs (no DB, no Qdrant, no GitHub HTTP).

    Returns a dict ``{tool_name: stub_value}`` so the assertions can
    compare against the exact stub content.
    """
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    tools_by_name = {t.name: t for t in get_skill_registry().all_tools}

    stubs = {
        "search_past_conversations_tool": (
            "J'ai retrouvé une conversation passée sur Sprint 2.7 — "
            "5 jalons sur 7 livrés."
        ),
        "github_repo_stats": {
            "stars": 1, "issues": 1, "clones_14d": 503, "cloners_today": 38,
        },
        "knowledge_search": "Aucun document indexé pour cette requête.",
        "memory_search": "1 résultat: ELY tourne en EU par défaut.",
    }

    # Each stub MUST match the underlying tool's signature exactly,
    # because LangChain re-derives schema info from the coroutine at
    # invocation time. A mismatch (e.g. ``repo=None`` instead of
    # ``repo=""``) makes Pydantic reject the args before the stub runs.

    async def _stub_search_past(query: str, user_id: str = "", limit: int = 3):
        return stubs["search_past_conversations_tool"]

    async def _stub_github_stats(owner: str = "", repo: str = "", user_id: str = ""):
        return stubs["github_repo_stats"]

    async def _stub_knowledge_search(query: str, user_id: str = ""):
        return stubs["knowledge_search"]

    async def _stub_memory_search(query: str, user_id: str = "", limit: int = 5):
        return stubs["memory_search"]

    # Patch the .coroutine on each StructuredTool. Pydantic v2 allows
    # direct attribute assignment for declared fields (which coroutine
    # is — Optional[Callable]).
    monkeypatch.setattr(
        tools_by_name["search_past_conversations_tool"], "coroutine", _stub_search_past
    )
    monkeypatch.setattr(
        tools_by_name["github_repo_stats"], "coroutine", _stub_github_stats
    )
    monkeypatch.setattr(
        tools_by_name["knowledge_search"], "coroutine", _stub_knowledge_search
    )
    monkeypatch.setattr(
        tools_by_name["memory_search"], "coroutine", _stub_memory_search
    )

    return stubs


# ──────────────────────────────────────────────────────────────────────
# 1. The full pipeline boots and runs a multi-tool script end-to-end
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_tool_orchestration_end_to_end(patched_registry_tools) -> None:
    """Exécute un script qui appelle 4 tools de l'allow-list V1 via le
    default dispatcher (registry réel + RPC réel + subprocess réel)."""
    from app.services.orchestrate_runner import OrchestrateRunner

    code = (
        "from ely_tools import (\n"
        "    search_past_conversations_tool, github_repo_stats,\n"
        "    knowledge_search, memory_search,\n"
        ")\n"
        "past = search_past_conversations_tool(query='sprint 2.7')\n"
        "stats = github_repo_stats()\n"
        "kb = knowledge_search(query='hermes pattern')\n"
        "mem = memory_search(query='ELY EU')\n"
        "print(f'past={past!r}')\n"
        "print(f'stats={stats!r}')\n"
        "print(f'kb={kb!r}')\n"
        "print(f'mem={mem!r}')\n"
    )

    runner = OrchestrateRunner(user_id="test-user-e2e")
    result = await runner.run(code=code)

    # 1. Subprocess exited cleanly
    assert result.exit_code == 0, (
        f"sandbox exited {result.exit_code}, stderr={result.stderr!r}, "
        f"stdout={result.stdout!r}"
    )

    # 2. All 4 tools were dispatched in the correct order
    assert result.tools_dispatched == [
        "search_past_conversations_tool",
        "github_repo_stats",
        "knowledge_search",
        "memory_search",
    ]

    # 3. The script's prints came back to stdout (the head/tail buffer
    # preserved the final lines)
    assert "Sprint 2.7" in result.stdout
    assert "503" in result.stdout
    assert "Aucun document indexé" in result.stdout
    assert "tourne en EU" in result.stdout

    # 4. No truncation on this small workflow
    assert result.truncated is False

    # 5. Latency reasonable (< 3s for a 4-call hermetic test)
    assert result.duration_seconds < 3.0, (
        f"sandbox took {result.duration_seconds:.2f}s — too slow for an "
        "hermetic E2E test"
    )


# ──────────────────────────────────────────────────────────────────────
# 2. Tool-not-in-allow-list returns clear error to the script
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_script_calling_unauthorized_tool_gets_clear_error(
    patched_registry_tools,
) -> None:
    """Even though Gmail tools exist in the registry, the script must
    NOT be able to call them (they're not in SANDBOX_ALLOWED_TOOLS_V1's
    destructive-write set — well, actually gmail_list_emails IS in V1.
    So let's pick something we KNOW isn't whitelisted: ``gmail_send_email``)."""
    from app.services.orchestrate_runner import OrchestrateRunner

    code = (
        "from ely_tools import search_past_conversations_tool\n"
        "# Try to side-step the stub module and call a tool directly via\n"
        "# the RPC. The server should refuse with ToolNotAllowed.\n"
        "import json, socket, struct, os\n"
        "with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:\n"
        "    s.connect(os.environ['ELY_RPC_SOCKET'])\n"
        "    p = json.dumps({'tool': 'gmail_send_email', 'args': {}}).encode()\n"
        "    s.sendall(struct.pack('!I', len(p)) + p)\n"
        "    h = b''\n"
        "    while len(h) < 4:\n"
        "        h += s.recv(4 - len(h))\n"
        "    (n,) = struct.unpack('!I', h)\n"
        "    body = b''\n"
        "    while len(body) < n:\n"
        "        body += s.recv(n - len(body))\n"
        "    resp = json.loads(body.decode())\n"
        "print(resp.get('error_type'))\n"
    )

    runner = OrchestrateRunner(user_id="test-user-e2e-blocked")
    result = await runner.run(code=code)

    assert result.exit_code == 0
    assert "ToolNotAllowed" in result.stdout
    # The tool was never dispatched (refused before counter increments)
    assert "gmail_send_email" not in result.tools_dispatched


# ──────────────────────────────────────────────────────────────────────
# 3. Sandbox PII isolation regression — the script can't reach app.*
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_isolation_holds_under_full_pipeline(
    patched_registry_tools,
) -> None:
    """The Jalon 4 regression test verifies python -S blocks app.* imports
    in isolation. Here we re-verify it through the full pipeline (real
    runner, real dispatcher, real subprocess) to confirm the isolation
    survives integration with the registry."""
    from app.services.orchestrate_runner import OrchestrateRunner

    code = (
        "try:\n"
        "    import app.services.vault_service  # noqa\n"
        "    print('LEAK')\n"
        "except ImportError:\n"
        "    print('blocked')\n"
        "except Exception as e:\n"
        "    print(f'other:{type(e).__name__}')\n"
    )

    runner = OrchestrateRunner(user_id="test-user-isolation")
    result = await runner.run(code=code)

    assert "blocked" in result.stdout
    assert "LEAK" not in result.stdout
    assert result.tools_dispatched == []
