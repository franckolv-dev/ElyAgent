#!/usr/bin/env python3
"""Cleanup runner — delete the test artefacts we created during the full run.

Exercises the *_delete_* HITL tests along the way (#35 drive_delete_file,
#60 tasks_delete, #69 contacts_delete, #105 notes_delete).
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner import Runner, TestCase, write_report  # reuse the engine

TOKEN = os.environ.get("ELY_TOKEN", "")
WS_URL = os.environ.get("ELY_WS_URL", "wss://ely.catalogmaker.fr/ws/chat")

CLEANUP = [
    TestCase(35, "Supprime le fichier Test-Runner-Doc de mon Drive",
             "drive_delete_file", section="Cleanup", category="hitl"),
    TestCase(35, "Supprime le fichier Test-Runner-Sheet de mon Drive",
             "drive_delete_file", section="Cleanup", category="hitl"),
    TestCase(60, "Supprime la tâche Tester ELY test-runner",
             "tasks_delete", section="Cleanup", category="hitl"),
    TestCase(69, "Supprime le contact dont l'email est franck@test.com",
             "contacts_delete", section="Cleanup", category="hitl"),
    TestCase(105, "Supprime ma note Idées-Test-Runner",
             "notes_delete", section="Cleanup", category="hitl"),
]


async def main():
    if not TOKEN:
        print("ERROR: set ELY_TOKEN", file=sys.stderr)
        sys.exit(2)
    print(f"▶ Cleanup: {len(CLEANUP)} destructive tests — approve each HITL on phone\n")
    async with Runner(WS_URL, TOKEN) as r:
        results = await r.run_all(CLEANUP)
    write_report(results, Path(__file__).parent / "cleanup-report.md")


if __name__ == "__main__":
    asyncio.run(main())
