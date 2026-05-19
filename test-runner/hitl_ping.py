#!/usr/bin/env python3
"""One-off HITL ping: sends a gmail_send_email to yourself via WS and
waits for hitl_pending / hitl_resolved. Use this to validate that the
test-runner's HITL detection works end-to-end before a full run.

Usage:
    ELY_TOKEN=... python3 hitl_ping.py [destinataire_email]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
import websockets

WS_URL = os.environ.get("ELY_WS_URL", "wss://ely.catalogmaker.fr/ws/chat")
TOKEN = os.environ.get("ELY_TOKEN", "")
DEFAULT_TO = "contact@agent-ely.fr"


async def main():
    to = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TO
    prompt = (
        f"Envoie un email à {to} avec pour sujet "
        f"'Test HITL runner' et corps : Ceci est un test du "
        f"test-runner ELY, tu peux ignorer ce mail."
    )

    print(f"▶ Destinataire   : {to}")
    print(f"▶ Prompt         : {prompt}")
    print(f"▶ WebSocket      : {WS_URL}")
    print()

    if not TOKEN:
        print("ERROR: set ELY_TOKEN", file=sys.stderr)
        sys.exit(2)

    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"token": TOKEN}))
        conversation_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "type": "user",
            "content": prompt,
            "conversation_id": conversation_id,
        }))
        print("  … prompt envoyé, en attente du HITL\n")

        t0 = time.monotonic()
        tools = []
        hitl_seen = False

        while True:
            elapsed = time.monotonic() - t0
            if elapsed > 240:
                print("\n✗ Timeout 4 min — le test a échoué avant HITL")
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                if elapsed > 10 and not hitl_seen:
                    print(f"  … {elapsed:.0f}s écoulées sans HITL, toujours en attente")
                continue

            ev = json.loads(raw)
            t = ev.get("type")
            if t == "tool_start":
                tool_name = ev.get("tool", "")
                tools.append(tool_name)
                print(f"  🔧 tool_start : {tool_name}")
            elif t == "tool_end":
                print(f"  ✓  tool_end  : {ev.get('tool', '')}")
            elif t == "hitl_pending":
                hitl_seen = True
                print(f"\n  ⏸  ⏸  ⏸  HITL_PENDING REÇU ⏸  ⏸  ⏸")
                print(f"        action_id : {ev.get('action_id', '')}")
                print(f"        description : {ev.get('description', '')[:200]}")
                print(f"\n  >>> Regarde ton ONGLET ELY — le panel validation")
                print(f"      devrait apparaître avec 3 boutons (Autoriser / Refuser / Interdire).")
                print(f"      Clique Autoriser pour que le mail parte.\n")
            elif t == "hitl_resolved":
                print(f"  ▶  HITL_RESOLVED — decision={ev.get('decision', '?')}")
            elif t == "message" and ev.get("role") == "assistant":
                final = (ev.get("content") or "")[:300]
                print(f"\n✓ Fin de turn après {elapsed:.1f}s")
                print(f"  tools : {tools}")
                print(f"  hitl  : {'OUI' if hitl_seen else 'NON (bug!)'}")
                print(f"  réponse : {final!r}")
                break
            elif t == "error":
                print(f"✗ Erreur backend : {ev.get('content', '')[:200]}")
                break
            elif t == "stopped":
                print(f"✗ Flux interrompu")
                break


if __name__ == "__main__":
    asyncio.run(main())
