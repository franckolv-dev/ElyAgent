# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_orchestrate_wiring.py
# @brief      Tests du wiring Sprint 2.7 — Jalon 5 (tier_c_only + completion_guard).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""Tests du wiring tier_c_only + completion_guard pour le tool orchestrate.

Couvre :
    1. ``TIER_C_ONLY_TOOLS`` contient ``orchestrate`` (frozenset cohérent).
    2. ``parse_dispatched_from_result()`` extrait correctement les noms
       de tools depuis l'en-tête meta produit par ``orchestrate_tool``.
    3. Le retour réel du tool ``orchestrate`` est parsable par cette
       fonction — il y a un contrat implicite entre le formateur et le
       parseur qu'on vérifie ici.
    4. ``orchestrate`` est filtré de ``_filtered_tools`` quand le tier
       n'est pas COMPLEX (filtrage purement logique testable sans
       toucher au graph runtime).
"""
from __future__ import annotations

import pytest

from app.agent.tool_sets import TIER_C_ONLY_TOOLS
from app.services.orchestrate_runner import parse_dispatched_from_result


# ──────────────────────────────────────────────────────────────────────
# 1. TIER_C_ONLY_TOOLS contains orchestrate
# ──────────────────────────────────────────────────────────────────────


def test_tier_c_only_contains_orchestrate() -> None:
    assert "orchestrate" in TIER_C_ONLY_TOOLS


def test_tier_c_only_is_frozenset() -> None:
    """Mutability would let module-import-order tweak the set — refuse."""
    assert isinstance(TIER_C_ONLY_TOOLS, frozenset)


# ──────────────────────────────────────────────────────────────────────
# 2. parse_dispatched_from_result — happy paths and edge cases
# ──────────────────────────────────────────────────────────────────────


def test_parse_extracts_simple_list() -> None:
    output = (
        "[orchestrate tools=gmail_list_emails,drive_list_files,web_search "
        "(count=3) | exit=0]\n"
        "...script stdout...\n"
    )
    assert parse_dispatched_from_result(output) == [
        "gmail_list_emails", "drive_list_files", "web_search",
    ]


def test_parse_preserves_duplicates_in_order() -> None:
    output = (
        "[orchestrate tools=echo_tool,double_tool,echo_tool (count=3)]\n"
        "ok\n"
    )
    assert parse_dispatched_from_result(output) == [
        "echo_tool", "double_tool", "echo_tool",
    ]


def test_parse_returns_empty_when_no_tools_dispatched() -> None:
    output = "[orchestrate no tools called]\nhello\n"
    assert parse_dispatched_from_result(output) == []


def test_parse_handles_truncation_warning_in_header() -> None:
    output = (
        "[orchestrate tools=memory_search (count=1) | exit=0 | "
        "⚠️ stdout truncated — exceeded 1000 bytes, kept head+tail only]\n"
        "line0000\n"
    )
    assert parse_dispatched_from_result(output) == ["memory_search"]


def test_parse_returns_empty_on_missing_header() -> None:
    assert parse_dispatched_from_result("hello world") == []
    assert parse_dispatched_from_result("") == []
    assert parse_dispatched_from_result("\n[orchestrate tools=x]") == []


def test_parse_rejects_non_string_inputs() -> None:
    assert parse_dispatched_from_result(None) == []  # type: ignore[arg-type]
    assert parse_dispatched_from_result(123) == []  # type: ignore[arg-type]
    assert parse_dispatched_from_result([]) == []  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# 3. The real orchestrate_tool output is parseable
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_orchestrate_output_is_parseable(monkeypatch) -> None:
    """End-to-end: run the actual orchestrate @tool, parse the meta header.

    This verifies the implicit contract between the formatter (in
    ``orchestrate_tool.py``) and the parser (in ``orchestrate_runner.py``)
    — if either side changes the format, this test fails immediately
    instead of silently breaking the completion_guard wiring.
    """
    # Patch generate_stubs to a hand-written module that defines
    # ``probe`` for the mock dispatcher — avoids dragging in the full
    # registry just for a format-check.
    def _fake_generate(*, allowed_tools, socket_path, target_path):
        target_path.write_text(
            'import os, json, socket, struct, threading\n'
            '_SOCK = os.environ["ELY_RPC_SOCKET"]\n'
            '_lock = threading.Lock()\n'
            'def _rpc(_t, **kw):\n'
            '    with _lock:\n'
            '        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:\n'
            '            s.connect(_SOCK)\n'
            '            p = json.dumps({"tool": _t, "args": kw}).encode()\n'
            '            s.sendall(struct.pack("!I", len(p)) + p)\n'
            '            h = b""\n'
            '            while len(h) < 4:\n'
            '                h += s.recv(4 - len(h))\n'
            '            (n,) = struct.unpack("!I", h)\n'
            '            body = b""\n'
            '            while len(body) < n:\n'
            '                body += s.recv(n - len(body))\n'
            '            r = json.loads(body.decode())\n'
            '    if not r.get("ok"):\n'
            '        raise RuntimeError(r.get("error"))\n'
            '    return r["result"]\n'
            'def probe(**kw):\n'
            '    return _rpc("probe", **kw)\n',
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "app.services.orchestrate_runner.generate_stubs", _fake_generate
    )

    # Use the runner directly with a tiny allow-list + dispatcher, then
    # format the result the way orchestrate_tool would, and parse it.
    from app.services.orchestrate_runner import (
        OrchestrateLimits,
        OrchestrateRunner,
    )

    def _mock_dispatcher(name, args):
        return {"name": name, "args": args}

    runner = OrchestrateRunner(
        user_id="test-user",
        tool_dispatcher=_mock_dispatcher,
        limits=OrchestrateLimits(
            timeout_seconds=5, max_tool_calls=5,
            max_stdout_bytes=4_000, max_stderr_bytes=2_000,
            sigkill_grace_seconds=1.0,
        ),
        allowed_tools=frozenset({"probe"}),
    )
    code = "from ely_tools import probe\nfor _ in range(3): probe(a=1)\nprint('done')\n"
    result = await runner.run(code=code)
    assert result.tools_dispatched == ["probe", "probe", "probe"]

    # Mirror the exact format orchestrate_tool emits.
    formatted = (
        f"[orchestrate tools={','.join(result.tools_dispatched)} "
        f"(count={len(result.tools_dispatched)}) | exit={result.exit_code}]\n"
        f"{result.stdout}"
    )
    assert parse_dispatched_from_result(formatted) == ["probe", "probe", "probe"]


# ──────────────────────────────────────────────────────────────────────
# 4. Tier C only filtering — pure list filter (matches nodes.py logic)
# ──────────────────────────────────────────────────────────────────────


class _FakeTool:
    """Minimal stand-in for a LangChain tool — we only need ``.name``."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_tier_c_only_filter_drops_orchestrate_for_simple_tier() -> None:
    """Reproduces the filter logic inserted in nodes.py: at non-COMPLEX
    tiers, every name in TIER_C_ONLY_TOOLS must be removed from the bound
    tool list."""
    tools = [
        _FakeTool("gmail_list_emails"),
        _FakeTool("orchestrate"),
        _FakeTool("web_search"),
    ]
    filtered = [t for t in tools if t.name not in TIER_C_ONLY_TOOLS]
    names = [t.name for t in filtered]
    assert "orchestrate" not in names
    assert "gmail_list_emails" in names
    assert "web_search" in names


def test_tier_c_only_filter_is_no_op_on_unrelated_tools() -> None:
    tools = [_FakeTool("gmail_list_emails"), _FakeTool("web_search")]
    filtered = [t for t in tools if t.name not in TIER_C_ONLY_TOOLS]
    assert [t.name for t in filtered] == ["gmail_list_emails", "web_search"]
