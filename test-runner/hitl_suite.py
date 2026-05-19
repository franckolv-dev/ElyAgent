#!/usr/bin/env python3
"""HITL test suite — remaining destructive/sensitive tests from the checklist.

Each test triggers a HITL notification on the phone via ntfy. The user
approves or refuses from the notification's action buttons.

Strategy to stay safe:
- Calendar: we create a dedicated test event first, then update & delete it
- Gmail: we send a mail to the user's own address, reply to it, then trash it
- Drive: we use `drive_share_file` on a file we control (the runner never
    targets files we can't reason about)
- Settings: vacation responder is activated THEN immediately deactivated
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner import Runner, TestCase, write_report

TOKEN = os.environ.get("ELY_TOKEN", "")
WS_URL = os.environ.get("ELY_WS_URL", "wss://ely.catalogmaker.fr/ws/chat")

HITL_TESTS = [
    # ── Gmail destructifs / envois ─────────────────────────────────────────
    TestCase(3, "Envoie un email à follivier@datasolution.fr avec pour sujet Test #3 runner et corps : Ceci est un test automatisé, ignore",
             "gmail_send_email", section="Gmail", category="hitl"),
    TestCase(15, "Active mon message d'absence avec pour texte : Test automatisé, je réponds bientôt — active-le pour les 5 prochaines minutes seulement",
             "gmail_update_settings", section="Gmail", category="hitl"),
    TestCase(15, "Désactive maintenant mon message d'absence",
             "gmail_update_settings", section="Gmail", category="hitl"),

    # ── Calendar chain : create → update → delete ──────────────────────────
    TestCase(19, "Crée un rendez-vous RDV-Test-Runner demain à 10h30 pendant 30 minutes",
             "calendar_create_event", section="Calendar", category="hitl"),
    TestCase(21, "Déplace le rendez-vous RDV-Test-Runner à 14h00 le même jour",
             "calendar_update_event", section="Calendar", category="hitl"),
    TestCase(25, "Réunion équipe lundi 9h",
             "calendar_quick_add", section="Calendar", category="hitl"),
    TestCase(22, "Supprime le rendez-vous RDV-Test-Runner",
             "calendar_delete_event", section="Calendar", category="hitl"),
    TestCase(22, "Supprime aussi la réunion équipe du lundi 9h",
             "calendar_delete_event", section="Calendar", category="hitl"),

    # ── Drive : partage puis dé-partage ────────────────────────────────────
    # On utilise un fichier qu'on vient de créer pour que ce soit isolé.
    TestCase(31, "Crée un fichier texte Test-Share-Runner.txt dans Drive avec le contenu : fichier de test partage",
             "drive_create_file", section="Drive", category="hitl"),
    TestCase(36, "Partage le fichier Test-Share-Runner.txt avec follivier@datasolution.fr en lecture seule",
             "drive_share_file", section="Drive", category="hitl"),
    TestCase(35, "Supprime le fichier Test-Share-Runner.txt de mon Drive",
             "drive_delete_file", section="Drive", category="hitl"),

    # ── Docs batch update ──────────────────────────────────────────────────
    # Nécessite un doc — on crée et on nettoie
    TestCase(40, "Crée un Google Doc intitulé Test-BatchUpdate",
             "docs_create_document", section="Docs", category="hitl"),
    TestCase(45, "Dans Test-BatchUpdate, ajoute le texte 'Titre principal' en gras et augmente sa taille via batch update",
             "docs_batch_update", section="Docs", category="hitl"),
    TestCase(35, "Supprime le Google Doc Test-BatchUpdate de mon Drive",
             "drive_delete_file", section="Docs", category="hitl"),

    # ── Sheets batch update ────────────────────────────────────────────────
    TestCase(47, "Crée un tableur Google Sheets intitulé Test-BatchSheet avec 5 lignes de données d'exemple",
             "sheets_create_spreadsheet", section="Sheets", category="hitl"),
    TestCase(54, "Dans Test-BatchSheet, trie la colonne B de manière décroissante via batch update",
             "sheets_batch_update", section="Sheets", category="hitl"),
    TestCase(35, "Supprime le tableur Test-BatchSheet de mon Drive",
             "drive_delete_file", section="Sheets", category="hitl"),

    # ── Tasks raw API call ─────────────────────────────────────────────────
    TestCase(63, "Via l'API Tasks brute, liste toutes les tasklists visibles avec leurs métadonnées complètes",
             "tasks_raw_api_call", section="Tasks", category="hitl"),
]


async def main():
    if not TOKEN:
        print("ERROR: set ELY_TOKEN", file=sys.stderr)
        sys.exit(2)
    print(f"▶ HITL suite : {len(HITL_TESTS)} tests — approve chaque notif sur ton téléphone\n")
    async with Runner(WS_URL, TOKEN) as r:
        results = await r.run_all(HITL_TESTS)
    write_report(results, Path(__file__).parent / "hitl-suite-report.md")


if __name__ == "__main__":
    asyncio.run(main())
