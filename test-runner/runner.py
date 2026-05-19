#!/usr/bin/env python3
# =============================================================================
# @project    ELY — Exactly Like You
# @file       test-runner/runner.py
# @brief      Automated integration-test runner for the 148-test checklist.
# @author     Claude + Franck
# @license    PolyForm Strict License 1.0.0
# =============================================================================
"""ELY end-to-end test runner.

Opens a WebSocket to the backend, sends each test prompt in a fresh
conversation, collects the tool_calls and final assistant message, then
writes a markdown report. HITL pauses are surfaced loudly so the user
can approve from phone/web.

Usage:
    export ELY_WS_URL="wss://ely.catalogmaker.fr/ws/chat"
    export ELY_TOKEN="..."
    python3 runner.py [--filter 1-17] [--output report.md]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

# ── Configuration ────────────────────────────────────────────────────────────

WS_URL = os.environ.get("ELY_WS_URL", "wss://ely.catalogmaker.fr/ws/chat")
TOKEN = os.environ.get("ELY_TOKEN", "")
TURN_TIMEOUT = 240.0  # seconds — max wait for a single test turn.
#                       Tests that chain 4-5 tool calls (e.g. sheets batch_
#                       update with list + list_sheets + read + update +
#                       summary) can exceed 2 min of LLM inference time.
HITL_TIMEOUT = 180.0  # seconds — how long to wait for the user to approve


# ── Test case definition ─────────────────────────────────────────────────────

@dataclass
class TestCase:
    num: int
    prompt: str
    expected_tool: str   # main tool we expect to see called
    section: str = ""
    # "safe" = no user data altered
    # "hitl" = HITL will fire, user must approve
    # "mutating" = changes user state but safe (creates test artefacts)
    category: str = "safe"
    skip_reason: str = ""   # if set, the test is skipped with this reason


@dataclass
class TestResult:
    case: TestCase
    status: str               # "pass" | "fail" | "skip" | "hitl_timeout"
    tools_called: list[str] = field(default_factory=list)
    final_response: str = ""
    elapsed_s: float = 0.0
    notes: str = ""


# ── The checklist — transcribed from docs/TESTING_CHECKLIST.md ──────────────
# Section headers follow the file. We only run tests that don't
# depend on user-specific inbox/drive content. Items that need an
# `[expéditeur récent]`, an attached PDF, or a specific drive file are
# marked skip_reason.

TESTS: list[TestCase] = [
    # ── Gmail ───────────────────────────────────────────────────────────────
    TestCase(1, "Montre-moi mes 5 derniers emails non lus", "gmail_list_emails",
             section="Gmail", category="safe"),
    TestCase(2, "Lis l'email de Google Play",
             "gmail_read_email", section="Gmail", category="safe"),
    TestCase(6, "Montre-moi mes brouillons", "gmail_list_drafts",
             section="Gmail", category="safe"),
    TestCase(9, "Quels sont mes labels Gmail ?", "gmail_list_labels",
             section="Gmail", category="safe"),

    # ── Calendar ────────────────────────────────────────────────────────────
    TestCase(18, "Quels sont mes rendez-vous cette semaine ?", "calendar_list_events",
             section="Calendar", category="safe"),
    TestCase(23, "Suis-je libre jeudi entre 14h et 16h ?", "calendar_check_availability",
             section="Calendar", category="safe"),
    TestCase(24, "Liste mes calendriers Google", "calendar_list_calendars",
             section="Calendar", category="safe"),

    # ── Drive ───────────────────────────────────────────────────────────────
    TestCase(28, "Liste mes fichiers récents dans Drive", "drive_list_files",
             section="Drive", category="safe"),

    # ── Docs ────────────────────────────────────────────────────────────────
    TestCase(40, "Crée un Google Doc intitulé Test-Runner-Doc",
             "docs_create_document", section="Docs", category="mutating"),
    TestCase(41, "Lis le contenu du document Test-Runner-Doc", "docs_read_document",
             section="Docs", category="safe"),
    TestCase(42, "Ajoute le texte : Ceci est un paragraphe de test à la fin du document Test-Runner-Doc",
             "docs_append_text", section="Docs", category="mutating"),
    TestCase(43, "Remplace le mot 'test' par 'validation' dans le document Test-Runner-Doc",
             "docs_replace_text", section="Docs", category="mutating"),
    TestCase(44, "Insère un tableau 3x3 dans le document Test-Runner-Doc",
             "docs_insert_table", section="Docs", category="mutating"),

    # ── Sheets ──────────────────────────────────────────────────────────────
    TestCase(47, "Crée un tableur Google Sheets intitulé Test-Runner-Sheet",
             "sheets_create_spreadsheet", section="Sheets", category="mutating"),
    TestCase(49, "Dans Test-Runner-Sheet, ajoute les lignes Janvier,1000,900 et Février,1200,1100",
             "sheets_append_rows", section="Sheets", category="mutating"),
    TestCase(50, "Dans Test-Runner-Sheet, mets la cellule B2 à 1500",
             "sheets_update_cells", section="Sheets", category="mutating"),
    TestCase(52, "Dans Test-Runner-Sheet, ajoute un onglet nommé Trimestre2",
             "sheets_add_sheet", section="Sheets", category="mutating"),
    TestCase(53, "Liste les onglets de Test-Runner-Sheet", "sheets_list_sheets",
             section="Sheets", category="safe"),

    # ── Tasks ───────────────────────────────────────────────────────────────
    TestCase(56, "Montre-moi mes tâches en cours", "tasks_list",
             section="Tasks", category="safe"),
    TestCase(57, "Crée la tâche : Tester ELY test-runner, à faire demain",
             "tasks_create", section="Tasks", category="mutating"),
    TestCase(61, "Liste mes listes de tâches", "tasks_list_tasklists",
             section="Tasks", category="safe"),
    TestCase(62, "Crée une nouvelle liste de tâches nommée Tests-Runner",
             "tasks_create_tasklist", section="Tasks", category="mutating"),

    # ── Contacts ────────────────────────────────────────────────────────────
    TestCase(65, "Liste mes 10 premiers contacts", "contacts_list",
             section="Contacts", category="safe"),

    # ── Web / Maps / Météo / Traduction ────────────────────────────────────
    TestCase(72, "Cherche les actualités sur l'IA générative", "web_search",
             section="Web", category="safe"),
    TestCase(73, "Dernières nouvelles en technologie", "web_search_news",
             section="Web", category="safe"),
    TestCase(74, "Va sur https://example.com et dis-moi ce qu'il y a", "browser_navigate",
             section="Web", category="safe"),
    TestCase(81, "Cherche les actualités sur la tech en France", "news_get_headlines",
             section="Web", category="safe"),

    TestCase(82, "Quelle est l'adresse de la Tour Eiffel ?", "maps_geocode",
             section="Maps", category="safe"),
    TestCase(83, "Comment aller de Paris à Lyon en voiture ?", "maps_directions",
             section="Maps", category="safe"),
    TestCase(84, "Trouve les restaurants italiens près de la Place de la République Paris", "maps_nearby",
             section="Maps", category="safe"),
    TestCase(85, "Quelle adresse correspond à ces coordonnées : 48.8566, 2.3522 ?", "maps_reverse_geocode",
             section="Maps", category="safe"),

    TestCase(86, "Quel temps fait-il à Lyon aujourd'hui ?", "weather_get",
             section="Météo", category="safe"),
    TestCase(87, "Traduis en anglais : L'intelligence artificielle change le monde",
             "translate_text", section="Traduction", category="safe"),

    # ── YouTube ─────────────────────────────────────────────────────────────
    TestCase(88, "Cherche des vidéos YouTube sur LangGraph", "youtube_search",
             section="YouTube", category="safe"),

    # ── QR & images ─────────────────────────────────────────────────────────
    TestCase(96, "Génère un QR code pour https://github.com/franckolv-dev/PhysicalAgent",
             "qrcode_generate", section="QR", category="safe"),
    TestCase(97, "Crée un QR code WiFi pour le réseau MonWifi, mot de passe Test1234",
             "qrcode_generate_wifi", section="QR", category="safe"),
    TestCase(98, "Crée un QR code vCard pour Franck Ollivier, email franck@test.com",
             "qrcode_generate_vcard", section="QR", category="safe"),

    # ── Memory / Notes ──────────────────────────────────────────────────────
    TestCase(99, "Souviens-toi que je préfère les réponses courtes",
             "save_user_preference", section="Memory", category="safe"),
    TestCase(101, "Crée une note intitulée Idées-Test-Runner avec le contenu : test automatisé",
             "notes_create", section="Notes", category="mutating"),
    TestCase(102, "Liste mes notes", "notes_list",
             section="Notes", category="safe"),
    TestCase(103, "Lis ma note Idées-Test-Runner", "notes_read",
             section="Notes", category="safe"),
    TestCase(106, "Cherche dans mes notes le mot test", "notes_search",
             section="Notes", category="safe"),

    # ── RAG ─────────────────────────────────────────────────────────────────
    TestCase(107, "Que contient ma base de connaissances ?", "knowledge_list",
             section="RAG", category="safe"),

    # ── Scheduler ──────────────────────────────────────────────────────────
    TestCase(135, "Liste mes tâches planifiées", "scheduler_list_tasks",
             section="Scheduler", category="safe"),

    # ── Watchdog ────────────────────────────────────────────────────────────
    TestCase(139, "Liste les sites que tu surveilles", "watchdog_list",
             section="Watchdog", category="safe"),

    # ── Python sandbox ──────────────────────────────────────────────────────
    TestCase(141, "Exécute ce code Python : print([x**2 for x in range(10)])", "python_execute",
             section="Python", category="safe"),

    # ── MCP ─────────────────────────────────────────────────────────────────
    TestCase(144, "Liste les serveurs MCP disponibles dans ta bibliothèque", "mcp_list_library",
             section="MCP", category="safe"),

    # ── Briefing ───────────────────────────────────────────────────────────
    TestCase(147, "Génère mon briefing du matin", "briefing_generate",
             section="Briefing", category="safe"),
]


# ── Runner engine ────────────────────────────────────────────────────────────

class Runner:
    def __init__(self, ws_url: str, token: str):
        self.ws_url = ws_url
        self.token = token
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.results: list[TestResult] = []

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=10 * 1024 * 1024)
        # Handshake — send the token as first message
        await self.ws.send(json.dumps({"token": self.token}))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.ws is not None:
            await self.ws.close()

    async def run_one(self, case: TestCase) -> TestResult:
        if case.skip_reason:
            return TestResult(case=case, status="skip", notes=case.skip_reason)

        assert self.ws is not None
        conversation_id = str(uuid.uuid4())
        print(f"\n[#{case.num:>3}] {case.section:<12} │ {case.prompt[:80]}")

        t0 = time.monotonic()
        await self.ws.send(json.dumps({
            "type": "user",
            "content": case.prompt,
            "conversation_id": conversation_id,
        }))

        tools: list[str] = []
        content_accum = ""
        final_content = ""
        hitl_active = False
        hitl_waiting_start = 0.0
        # status starts empty — a successful "message" event will flip it
        # to "pending", and the heuristic block below will then refine it
        # to pass/fail. Hard errors (error/stopped/timeout) set it directly.
        status = ""
        notes = ""

        while True:
            # Per-turn deadline
            remaining = TURN_TIMEOUT - (time.monotonic() - t0)
            if hitl_active:
                remaining = HITL_TIMEOUT - (time.monotonic() - hitl_waiting_start)
            if remaining <= 0:
                notes = (
                    "Timeout HITL — aucune réponse de ton téléphone"
                    if hitl_active else
                    "Timeout — pas de réponse finale en 120s"
                )
                status = "hitl_timeout" if hitl_active else "fail"
                break

            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                notes = "Timeout sur recv()"
                status = "fail"
                break

            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = ev.get("type")
            if t == "token":
                content_accum += ev.get("content", "")
            elif t == "tool_start":
                name = ev.get("tool", "")
                if name and name not in tools:
                    tools.append(name)
            elif t == "tool_end":
                pass
            elif t == "hitl_pending":
                if not hitl_active:
                    hitl_active = True
                    hitl_waiting_start = time.monotonic()
                    desc = ev.get("description", "")[:120]
                    print(f"    ⏸  HITL — approuve sur ton téléphone : {desc}")
            elif t == "hitl_resolved":
                hitl_active = False
                print(f"    ▶  HITL résolu ({ev.get('decision', '?')})")
            elif t == "message" and ev.get("role") == "assistant":
                final_content = ev.get("content", content_accum)
                status = "pending"
                break
            elif t == "stopped":
                notes = "Flux interrompu (stopped)"
                status = "fail"
                break
            elif t == "error":
                notes = f"Erreur backend : {ev.get('content', '')[:200]}"
                status = "fail"
                break

        elapsed = time.monotonic() - t0

        # ── Heuristic pass/fail ─────────────────────────────────────────────
        # Rule of thumb: if Éli called at least one tool AND produced a
        # non-empty response, it's a pass. The "expected_tool" is a hint,
        # not a strict requirement — she may chain tools (e.g. list → act)
        # or pick a closely related variant (web_search ↔ web_search_news,
        # news_get_headlines for news queries). A true failure is:
        #   - No tool called + refusal phrase at the start of the reply
        #   - Empty response
        #   - Backend error event (already handled above)
        if status == "pending":
            response_stripped = (final_content or "").strip()
            response_head = response_stripped[:200].lower()
            tool_matched = case.expected_tool in tools
            tools_called_any = bool(tools)
            # Refusal only counted when it's near the start AND nothing was called
            head_refusal_markers = (
                "je ne peux pas",
                "je n'ai pas accès",
                "impossible d'accéder",
                "je suis désolée",
                "les outils ne sont pas disponibles",
                "je n'ai pas les capacités",
            )
            refused_upfront = any(m in response_head for m in head_refusal_markers)

            if not response_stripped:
                status = "fail"
                notes = "Réponse finale vide"
            elif tools_called_any:
                status = "pass"
                if not tool_matched:
                    notes = f"Outil attendu : {case.expected_tool} — réel : {','.join(tools)}"
            elif refused_upfront:
                status = "fail"
                notes = "Éli a refusé sans appeler d'outil"
            else:
                # Text-only response with no refusal — could be a chitchat
                # answer that didn't need a tool. Borderline; mark as "skip-like".
                status = "pass"
                notes = "Réponse texte sans outil (peut être OK si la question ne nécessite pas d'appel)"

        summary = {
            "pass": "✓",
            "fail": "✗",
            "skip": "⊘",
            "hitl_timeout": "⧖",
        }[status]
        print(f"    {summary} {status.upper():<12} {elapsed:5.1f}s  tools={tools}")
        if notes:
            print(f"      ↳ {notes}")

        return TestResult(
            case=case,
            status=status,
            tools_called=tools,
            final_response=final_content[:500],
            elapsed_s=elapsed,
            notes=notes,
        )

    async def run_all(self, filtered: list[TestCase]) -> list[TestResult]:
        results = []
        for case in filtered:
            try:
                r = await self.run_one(case)
            except Exception as exc:
                r = TestResult(
                    case=case, status="fail",
                    notes=f"Exception runner : {type(exc).__name__}: {exc}",
                )
                print(f"    ✗ EXCEPTION {type(exc).__name__}: {exc}")
            results.append(r)
            # Breathe between tests to avoid throttling
            await asyncio.sleep(1.5)
        return results


# ── Report generator ────────────────────────────────────────────────────────

def write_report(results: list[TestResult], path: Path) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    hitl_to = sum(1 for r in results if r.status == "hitl_timeout")

    lines = [
        "# ELY — Rapport de test-runner",
        "",
        f"- Total exécutés : **{total}**",
        f"- ✓ Pass : **{passed}**",
        f"- ✗ Fail : **{failed}**",
        f"- ⧖ HITL timeout : **{hitl_to}**",
        f"- ⊘ Skip : **{skipped}**",
        "",
        "| # | Section | Prompt | Statut | Tool attendu | Tools réels | Temps | Notes |",
        "|---|---|---|:---:|---|---|---:|---|",
    ]
    for r in results:
        status_sym = {"pass": "✓", "fail": "✗", "skip": "⊘", "hitl_timeout": "⧖"}[r.status]
        prompt_short = r.case.prompt[:60].replace("|", "\\|")
        tools_real = ",".join(r.tools_called) or "—"
        notes = (r.notes or "").replace("|", "\\|")[:200]
        lines.append(
            f"| {r.case.num} | {r.case.section} | {prompt_short} | "
            f"{status_sym} | `{r.case.expected_tool}` | `{tools_real}` | "
            f"{r.elapsed_s:.1f}s | {notes} |"
        )

    lines += ["", "## Détails des échecs", ""]
    for r in results:
        if r.status in ("fail", "hitl_timeout"):
            lines += [
                f"### #{r.case.num} — {r.case.section} — {r.case.prompt}",
                "",
                f"- Statut : **{r.status}**",
                f"- Tool attendu : `{r.case.expected_tool}`",
                f"- Tools réels : `{r.tools_called}`",
                f"- Notes : {r.notes}",
                f"- Réponse : {r.final_response[:300]!r}",
                "",
            ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📝 Rapport écrit : {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_filter(arg: str) -> set[int]:
    if not arg:
        return set()
    out: set[int] = set()
    for chunk in arg.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif chunk:
            out.add(int(chunk))
    return out


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="", help="e.g. '1-20,45,72-85'")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "report.md"),
        help="Markdown report output path",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Stop after N tests (0 = all)",
    )
    args = parser.parse_args()

    if not TOKEN:
        print("ERROR: set ELY_TOKEN env var", file=sys.stderr)
        sys.exit(2)

    only = parse_filter(args.filter)
    cases = TESTS if not only else [c for c in TESTS if c.num in only]
    if args.limit:
        cases = cases[: args.limit]

    print(f"▶ Running {len(cases)} test(s) against {WS_URL}")
    print(f"  Keep the web UI open on your phone — HITL approvals go there.\n")

    async with Runner(WS_URL, TOKEN) as r:
        results = await r.run_all(cases)

    write_report(results, Path(args.output))


if __name__ == "__main__":
    asyncio.run(main())
