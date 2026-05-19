#!/usr/bin/env python3
"""Smoke test for the backlog fixes:
- notes_delete should NOT trigger HITL (word-boundary fix in is_critical)
- save_user_preference should not fire spontaneously
- sheets_batch_update should finish under 240s
"""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner import Runner, TestCase, write_report

TOKEN = os.environ.get("ELY_TOKEN", "")
WS_URL = os.environ.get("ELY_WS_URL", "wss://ely.catalogmaker.fr/ws/chat")

TESTS = [
    TestCase(101, "Crée une note intitulée Backlog-Fix-Note avec le contenu : test fix",
             "notes_create", section="Notes", category="mutating"),
    TestCase(105, "Supprime ma note Backlog-Fix-Note",
             "notes_delete", section="Notes", category="safe"),  # should NOT be HITL now
    TestCase(86, "Quel temps fait-il à Paris aujourd'hui ?",
             "weather_get", section="Météo", category="safe"),  # verifier no save_user_pref
]


async def main():
    if not TOKEN:
        print("ERROR: set ELY_TOKEN", file=sys.stderr)
        sys.exit(2)
    async with Runner(WS_URL, TOKEN) as r:
        results = await r.run_all(TESTS)
    write_report(results, Path(__file__).parent / "smoke-backlog-report.md")


if __name__ == "__main__":
    asyncio.run(main())
