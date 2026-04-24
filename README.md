# ELY — Exactly Like You

> **Your personal AI agent. Trained on your habits. Runs on your hardware. Never acts without your approval.**

ELY is a fully self-hosted AI agent that integrates with your entire digital life — Google Workspace, servers, smart home, files, web — while keeping your sensitive data out of the LLM and pausing before every irreversible action.

**Run it on your laptop, a Mac Mini, or a VPS. Access it from anywhere via Cloudflare Tunnel or Tailscale. No subscription. No data leaving your machine unless you choose it.**

---

## Why ELY, not another AI wrapper?

| Feature | ELY | Typical AI chat |
|---------|-----|----------------|
| Runs 100% on your hardware | ✅ | ❌ |
| Pauses before irreversible actions (HITL) | ✅ | ❌ |
| PII never reaches the LLM | ✅ | ❌ |
| Works via Telegram, iOS, Android, WhatsApp | ✅ | ❌ |
| Persistent memory across sessions | ✅ | ❌ |
| Executes commands on your servers via SSH | ✅ | ❌ |
| Controls your desktop (mouse, keyboard, screen) | ✅ | ❌ |
| Compares LLMs blind with ELO ranking | ✅ | ❌ |
| Local models (Ollama) with zero cloud cost | ✅ | ❌ |
| On-device smart file cleanup (dedupe by MD5 + dHash) | ✅ | ❌ |
| Fully open source, PolyForm licence | ✅ | ❌ |

---

## What ELY Can Do

### 🌐 Google Workspace — Full Integration (76 tools)

ELY has read/write access to your entire Google suite. Every destructive action pauses for your approval.

> **New in v1.1 — Advanced tier.** In addition to the high-level tools below, every service exposes a `batch_update` / `batch_operations` tool (bulk mutations in one call) and a `raw_api_call` escape hatch. The raw tool lets Éli call **any** method of the official Google Python client by name (e.g. `spreadsheets.values.append`, `messages.batchModify`, `events.quickAdd`) with free-form JSON params — so she is no longer limited to the wrappers we pre-wrote. Critical raw calls still go through HITL approval.

<details>
<summary><strong>Gmail (17 tools)</strong> — read, send, reply, draft, label, search, clean up, bulk modify, settings, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Read my last 5 unread emails" | Fetches and summarises latest Gmail messages |
| "Send an email to alice@company.com: Meeting Friday" | Drafts, pauses for approval, then sends |
| "Reply to Bob's email and say I'll be there" | Replies in-thread (approval required) |
| "Archive all newsletters from 2024" | `gmail_batch_modify` — up to 1000 messages / call (HITL) |
| "Turn on my vacation responder until next Monday" | `gmail_update_settings` — signature, vacation, filters, forwarding |
| "Clean up my promotions folder" | Smart cleanup by category |
| "Search for invoices from last month" | Full-text search with filters |

</details>

<details>
<summary><strong>Calendar (9 tools)</strong> — list, create, update, delete, check availability, quick add, Meet events, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "What are my appointments this week?" | Lists Google Calendar events |
| "Dentist Friday 10h30 for 45min" | `calendar_quick_add` — natural language parsing (HITL) |
| "Create a Meet with team@company.com every Monday at 9am" | `calendar_create_meet_event` — auto Meet link + RRULE recurrence |
| "Am I free Thursday between 2pm and 4pm?" | Checks freebusy |

</details>

<details>
<summary><strong>Drive (11 tools)</strong> — list, read, create, update, move, rename, delete, share, copy, export, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Share that spec doc with alice@company.com as commenter" | `drive_share_file` with role whitelist (HITL) |
| "Duplicate the Q2 budget into a Q3 budget" | `drive_copy_file` — no approval needed |
| "Export the invoice doc as PDF" | `drive_export_file` — PDF, DOCX, XLSX, CSV, ODT, EPUB, RTF… |

</details>

<details>
<summary><strong>Google Docs (7 tools)</strong> — create, read, append, find/replace, insert tables, batch update, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Add a bullet list with our 3 priorities at the top of doc X" | `docs_batch_update` — insertText + createParagraphBullets (HITL) |
| "Find every 'client' in this doc and replace by 'partner'" | `docs_batch_update` — replaceAllText |

</details>

<details>
<summary><strong>Google Sheets (9 tools)</strong> — create, read, append, update, manage tabs, batch update, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Sort column B descending and freeze the first row" | `sheets_batch_update` — sortRange + updateSheetProperties (HITL) |
| "Add a conditional formatting rule: red when late" | `sheets_batch_update` — addConditionalFormatRule |

</details>

<details>
<summary><strong>Tasks (8 tools)</strong> — list, create, complete, update, delete, manage lists, raw API</summary>

Plus full sub-tasks, reorder (`tasks.move`) and batch-clear of completed items via the raw tool.

</details>

<details>
<summary><strong>Contacts / People API (8 tools)</strong> — find, list, create, update, delete, batch operations, raw API</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Import these 30 contacts from the CSV" | `contacts_batch_operations` — create/update/delete up to 200 / call (HITL) |

</details>

---

### 🔒 Security — The Core Difference

#### PII Masking Pipeline

Your sensitive data never reaches the LLM:

```
Your input:     "Transfer €500 to alice@company.com from FR76 3000 ..."
LLM receives:   "Transfer €500 to [EMAIL_0] from [IBAN_0] ..."
ELY shows you:  "Transferring €500 to alice@company.com ..."  ← real values restored
```

Automatically detected and masked: email addresses, credit card numbers, IBANs, API tokens, phone numbers.

#### Human-in-the-Loop (HITL)

Every irreversible action is **paused** before execution:

```
ELY wants to execute:
  Tool: send_email → alice@example.com
  Subject: "Meeting Friday"

  [ ✅ Allow once ]   [ ❌ Deny once ]   [ 🛡️ Ban permanently ]
```

- **Ban permanently** → ELY never proposes this action again, even in future sessions
- HITL works on web UI, Telegram inline keyboard, and the Android app (FCM push)

---

### 🧠 Memory — ELY Knows You

| Layer | Storage | Purpose |
|-------|---------|---------|
| Semantic | Qdrant (vector DB) | Facts, preferences — retrieved by similarity |
| Keyword | SQLite FTS5 | Fast recall of names, dates, IDs |
| Temporal decay | Score weighting | Recent memories prioritised |
| Permanent constraints | Qdrant | HITL "Ban" decisions — never forgotten |

ELY automatically extracts and remembers: your preferences, important facts, recurring patterns, security rules — across all sessions.

---

### 🤖 Multi-Provider LLM Engine

Route each request to the optimal model based on detected complexity. **Configure everything in Settings — no code, no restart.**

| Tier | Recommended default | Use case |
|------|---------------------|---------|
| **A — Simple** | Qwen 3.6 Flash (API) *or* Qwen 2.5-VL local (LM Studio) | Quick questions, cheapest/fastest |
| **B — Standard** | Qwen 3.6 Plus (API) or Claude Haiku | Everyday tasks, tool chaining |
| **C — Complex** | Qwen 3.6 Plus (API) or Claude Sonnet | Code, deep analysis, multi-step |
| **IMG — Vision** | Qwen 3-VL Plus (API) or Gemini Flash | Images, PDFs, screenshots |
| **SYS — Maintenance** | Qwen 3.6 Flash or Ollama (local) | Background tasks, memory |

**Supported providers:**
- **Cloud API** — Qwen API (Alibaba DashScope) · OpenRouter (200+ models) · Anthropic Claude · Google Gemini · DeepSeek · Mistral AI · Zhipu GLM
- **Local** — Ollama · LM Studio (MLX on Apple Silicon, OpenAI-compatible endpoint)

**Local mode optimisations** (2026-04) :
- **Compact prompt mode** : ELY auto-detects OpenAI-compatible servers on `localhost`/`127.0.0.1`/`host.docker.internal`/RFC-1918 hosts and switches to a ~300-token system prompt (vs 2,700 normally) — makes small models (Qwen 2.5-VL 7B, Gemma, Phi) actually respect `tool_choice="required"`. Frontier cloud models keep the full prompt.
- **Per-turn memory cache** : constraints / memories / user profile are fetched once per user turn and reused across tool-call iterations — keeps LM Studio prefix-cache valid.
- **Provider-aware `tool_choice` mapping** : `any` → `required` when the LLM is OpenAI-compatible, to avoid silent HTTP 400 from strict servers.
- **Qwen thinking off** : `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` injected for Qwen-on-LM-Studio and Qwen-via-API to prevent 100 %-of-tokens spent in `<think>` blocks.

**Qwen API setup** : Create an instance in *Settings → Modèles IA*, provider `qwen_api`, paste your DashScope key + region-scoped base URL (e.g. `https://ws-<id>.eu-central-1.maas.aliyuncs.com/compatible-mode/v1`), pick a model (`qwen3.6-plus`, `qwen3.6-flash`, `qwen3-vl-plus`, etc.), assign to tiers.

Automatic fallback if a provider is unavailable (can be disabled per-tier for pure local / pure cloud testing). Context caching enabled where supported (up to 90 % cost reduction on Anthropic prompt caching).

---

### ⚔️ Arena — Blind LLM Comparison

Compare any two AI models side-by-side without knowing which is which. Vote for the best answer. ELO leaderboard (K=32) tracks performance over time.

- Pick any two providers from your configured keys
- Responses labelled "Model A" and "Model B" — revealed only after you vote
- `both_bad` vote penalises both models symmetrically
- Leaderboard and history accessible from the sidebar

---

### 🌍 Web, News & Weather

```
"Search for flights Paris–New York July"     → Browses the web, summarises results
"Go to lemonde.fr and read the front page"   → Navigates + extracts content
"What's the weather in Lyon?"                → Current weather + 3-day forecast
"Latest news in France"                      → Google News RSS headlines
"Translate this paragraph to Spanish"        → MyMemory translation API
"Take a screenshot of this site"             → Screenshot of current page
```

---

### 🖥️ ELY Desktop — Local Automation

A native Go daemon that runs on your personal computer and connects to the ELY server. Exposes capabilities impossible from a cloud server:

| Capability | What it does |
|-----------|-------------|
| Screen capture | Screenshots of your desktop |
| Keyboard / mouse control | Types text, presses keys, clicks anywhere |
| App launcher | Opens applications by name |
| Clipboard access | Reads and writes your clipboard |
| Local file operations | Reads, writes, moves, deletes files (approval required) |
| System info | CPU, memory, disk, running processes |

The daemon connects **outbound** via WebSocket — your desktop never needs to be publicly reachable.

```bash
cd desktop
./build.sh          # produces binaries for Linux, macOS (ARM + Intel), Windows
./ely-desktop       # run the daemon
```

---

### 🎓 ELY Trainer — Visual Guidance Mode

ELY takes control of your screen to demonstrate any task, step by step — like a colleague guiding your hands.

1. You ask: *"Show me how to create a pivot table in Excel"*
2. ELY takes a screenshot → vision LLM decides the next action
3. ELY narrates: *"I'm going to click on the Insert tab…"*
4. ELY executes on your screen → new screenshot → next step
5. Repeats until the task is complete (up to 20 steps)

Requires ELY Desktop to be running and connected.

---

### 📡 Communication Channels

Same agent. Same memory. Same security. **10 ways to reach Éli.**

> Every channel goes through the same LangGraph agent, the same HITL approval layer, and the same persistent memory — a conversation started on your phone continues seamlessly on your desktop or Telegram.

#### 🖥️ Web Interface

| Channel | Setup | Notes |
|---------|-------|-------|
| **Web UI** | Zero — open `https://your-server` | Real-time streaming chat, 3D cyberpunk avatar, Markdown rendering, file attachments, Stop button mid-generation |
| **Voice Mode** | Zero — microphone permission | Full-screen voice conversation, wake word **"Éli"**, continuous STT→TTS loop (edge-tts), live transcript, visual breathing animation |
| **PWA** | Zero — browser install prompt after 30s | Installable on iOS / Android / macOS / Windows as a native-looking app — works offline (shell + cached assets), push-ready |

#### 📱 Native Mobile Apps

| Channel | Setup | Notes |
|---------|-------|-------|
| **iOS App** (SwiftUI) | Build from `ios/` — Xcode 15, iOS 17+ | Native chat + voice mode, Keychain authentication, biometric unlock, landscape support |
| **Android App** (Kotlin) | Build APK from `android/` or follow [docs/ANDROID_INSTALL.md](./docs/ANDROID_INSTALL.md) | Jetpack Compose UI, voice input, FCM push notifications for HITL approvals, built-in **Smart File Manager**, minSdk 28 |

#### 🗂️ Smart File Manager (Android)

An on-device cleanup assistant — nothing ever leaves your phone. Accessed from the folder icon in the chat toolbar.

- **Pick any folder** via Android's Storage Access Framework (Downloads, WhatsApp, DCIM, SD card…) — no runtime permissions needed, the OS only grants the tree you chose.
- **Declarative filters**: size (`> 5 Mo`), age (older than N days), category (images, videos, APK, archives, documents), extension, filename substring — combinable with AND logic.
- **Exact-duplicate detection** via streaming MD5 (first pruned by file size → no hashing of unique sizes). Groups are auto-sorted by recoverable space.
- **Visual duplicate detection** via perceptual dHash (8×8 → 64 bits, Hamming distance ≤ 6) — catches resized / re-encoded / slightly edited copies of the same photo.
- **Ask Ély**: natural-language parser for one-shot cleanup requests — *"supprime les apk"*, *"fichiers de plus de 5 Mo"*, *"photos plus anciennes que 6 mois"*. Runs locally, no LLM round-trip.
- **Safe deletion**: one-copy-kept heuristic for dedupe (largest kept as master), explicit confirmation dialog with recoverable size preview, per-file failure list surfaced back to the UI.
- **Privacy by design**: all hashing, filtering and grouping happens inside the app process. Files never transit the backend, only user decisions do.

#### 💬 Messaging Platforms

| Channel | Setup | Notes |
|---------|-------|-------|
| **Telegram** | `TELEGRAM_BOT_TOKEN` in `.env` → `@BotFather` | Full agent access from any device; inline keyboard buttons for HITL approvals (Allow / Deny / Ban); works in groups and DMs |
| **WhatsApp** | Meta Cloud API webhook — see below | Full agent access; HITL approvals via reply messages; requires a Meta Business account and a dedicated phone number |
| **Slack** | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` in `.env` | Socket Mode — **no public URL needed**; Block Kit interactive buttons for HITL; works in channels and DMs with `@Éli` |
| **Discord** | `DISCORD_BOT_TOKEN` in `.env` | DM or `@Éli` mention in any channel; emoji-based HITL reactions (✅ allow · ❌ deny · 🛡️ ban) |

#### 🔔 Push Notifications

| Channel | Setup | Notes |
|---------|-------|-------|
| **Android (FCM)** | Install the Android app — the FCM token is registered automatically on login | Delivers HITL approval requests as rich push notifications with **Allow / Deny / Ban** action buttons, even when the app is closed |
| **iOS (APNs)** | Install the iOS app — the push token is registered automatically on login | Same UX as Android, via Apple Push Notification service |

---

#### WhatsApp — Setup Guide

WhatsApp requires a **Meta Business account** and a number dedicated to the bot (cannot be your personal number).

1. Create a **Meta for Developers** app at [developers.facebook.com](https://developers.facebook.com)
2. Add the **WhatsApp** product → get a test number (free) or connect your own number
3. Copy the **phone number ID** and **access token** into `.env`:
   ```
   WHATSAPP_PHONE_NUMBER_ID=12345678901234
   WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxx
   WHATSAPP_VERIFY_TOKEN=your-random-secret
   ```
4. Set your webhook URL to `https://your-server/api/channels/whatsapp/webhook`
5. Subscribe to the `messages` field
6. Restart ELY (`make restart s=backend`) — Éli is now reachable on WhatsApp

> Messages sent to the bot number are processed by the full agent (tools, HITL, memory). HITL approvals arrive as WhatsApp replies in the same thread.

---

#### Telegram — Quick Start

```bash
# 1. Create bot with @BotFather → /newbot
# 2. Add to .env:
TELEGRAM_BOT_TOKEN=123456789:AAxxxxxx

# 3. Restart backend
make restart s=backend
```

Send `/start` to your bot — done.

---

#### Channel Comparison

| | Web | Voice | iOS | Android | PWA | Telegram | WhatsApp | Slack | Discord |
|--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Full agent (all tools) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| HITL approvals | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Persistent memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Voice / STT | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | — | — |
| Push notifications | — | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Needs public URL | — | — | ✅ | ✅ | ✅ | — | ✅ | — | ✅ |
| Works fully offline | — | — | — | — | Partial | — | — | — | — |

---

### 🗄️ Infrastructure & Automation

```
"Remind me every Monday at 9am to check my calendar"   → Recurring scheduled task
"Run df -h on my prod server"                           → SSH execution (approval required)
"Run docker ps on my-server"                            → Remote Docker management
"Generate a QR code for https://example.com"            → Downloadable QR image
"Summarise the PDF invoice.pdf"                         → Extracts + summarises PDF
"Transcribe this audio file"                            → Local Whisper STT
"Read the YouTube video at this URL"                    → Fetches transcript
```

---

### 📚 RAG Knowledge Base

Upload your documents — ELY searches them semantically before answering.

- Supported formats: PDF, TXT, Markdown, CSV, JSON, DOCX
- Automatic chunking + embedding (fastembed, all-MiniLM-L6-v2)
- Semantic retrieval with source citations
- **Agentic RAG**: ELY proactively decides if the knowledge base is worth searching, reranks results before answering

---

### 🔐 Vault — Encrypted Secrets

Store API keys and passwords encrypted at rest (AES-256-GCM), injected into tool calls at runtime — never sent to the LLM.

---

### 📊 Analytics Dashboard

| Widget | Shows |
|--------|-------|
| Summary cards | Requests, tokens, estimated cost |
| Daily chart | Token consumption and cost per day |
| Top skills | Most used tools |
| HITL breakdown | Allow / Deny / Ban counts |
| Provider breakdown | Usage per LLM provider |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                          Channels                             │
│  Web · Voice · Telegram · Slack · Discord · WhatsApp          │
│  iOS · Android · PWA                                          │
└────────────────────┬──────────────────────────────────────────┘
                     │
┌────────────────────▼──────────────────────────────────────────┐
│                    nginx (port 80)                            │
│    /ws/* → backend:8000    everything else → frontend:3000    │
└────────────────────┬──────────────────────────────────────────┘
                     │
┌────────────────────▼──────────────────────────────────────────┐
│                     FastAPI Backend                           │
│                                                               │
│  SecurityFilter → Complexity Router → LangGraph Agent        │
│  (PII masking)     (A/B/C/IMG/SYS)    (tool calling loop)   │
│                                              │               │
│  ┌───────────────────────────────────────────▼────────────┐  │
│  │                      Tools                             │  │
│  │  Gmail · Calendar · Drive · Docs · Sheets · Tasks      │  │
│  │  Web · Weather · News · SSH · Scheduler · PDF          │  │
│  │  Desktop daemon · Trainer · RAG · Vault · QR · STT    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  HITL Manager → Web / Telegram / FCM (Android) / APNs (iOS)  │
│  Arena Service → ELO ranking (K=32)                          │
│  Analytics Logger → usage_logs                               │
└───────────────────────────────┬───────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────┐
│                          Storage                              │
│  Qdrant (vector)     SQLite (conversations, usage, settings)  │
│  Vault (AES-256-GCM) Scheduled tasks · User profiles         │
└───────────────────────────────────────────────────────────────┘
```

---

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12 · FastAPI · LangGraph · uv |
| Frontend | Next.js 15 · TypeScript · Tailwind CSS · Three.js |
| Proxy | nginx (WebSocket + API routing) |
| Auth | JWT · Argon2 · HttpOnly cookies |
| LLM | OpenRouter · Anthropic · Gemini · DeepSeek · Mistral · Zhipu · Ollama |
| Memory | Qdrant (vector) · SQLite FTS5 |
| Browser automation | Playwright (Chromium, headless) |
| Desktop daemon | Go (multi-platform, WebSocket) |
| Mobile | iOS SwiftUI (iOS 17+) · Android Kotlin/Compose |
| RAG | fastembed · Qdrant |
| STT | faster-whisper (local) |
| TTS | edge-tts (Microsoft Edge voices) |
| Notifications | FCM (Android) · APNs (iOS) · Telegram · WebSocket |
| Vault | AES-256-GCM |
| Infra | Docker Compose · nginx · Cloudflare Tunnel |

---

## Quick Start

**Prerequisites:** Docker, Git, Ollama *(optional but recommended)*

```bash
# 1. Clone
git clone https://github.com/franckolv-dev/PhysicalAgent.git
cd PhysicalAgent

# 2. Configure
cp .env.example .env
# Edit .env — minimum: set JWT_SECRET_KEY
# python -c "import secrets; print(secrets.token_hex(32))"

# 3. Start everything
make up

# 4. Create your admin account
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password

async def create():
    async with async_session() as db:
        u = User(email='admin', username='admin',
                 hashed_password=await hash_password('your-password'),
                 role='admin', is_active=True)
        db.add(u); await db.commit(); print('Done!')

asyncio.run(create())
"
```

Open **http://localhost:3000** and log in.

### Configure your AI models

**Settings → Modèles IA → + Ajouter**

- **Ollama (free, local):** install [Ollama](https://ollama.com), pull a model (`ollama pull gemma4:26b`), select it in Settings — the list is auto-detected.
- **Cloud providers:** enter your API key in Settings — no restart needed.

Then **Settings → Routage** to assign models to complexity tiers.

### Access from anywhere

For mobile access, external webhooks (WhatsApp, Telegram), or sharing with family — see the deployment guide:

📖 **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)** — step-by-step for Cloudflare Tunnel, Tailscale, and fixed IP + Caddy.

---

## 💡 Tips for talking to ELY

ELY has 148 tools across Google Workspace, web, system automation and
local memory. She picks the right one automatically from your sentence
— but a **few words can save a roundtrip** when a request is ambiguous:

- Say **"brouillon de mail"** instead of just "brouillon"
  → ensures Gmail, not some other system
- Say **"rappel chaque soir"** or **"événement ponctuel dans mon agenda"**
  → picks a recurring cron task vs a one-off Google Calendar event
- Say **"dans mes notes"** vs **"dans un Google Doc"** for a text snippet
  → chooses local notes vs Google Docs
- Provide a **real email address** (`alice@example.com`) when asking her
  to mail someone you haven't saved in contacts, so she doesn't have to
  search-or-ask

When the choice is truly ambiguous (e.g. *"envoie ça à Alice"* — mail,
WhatsApp, Telegram?) ELY asks a short clarification question before
acting. She never guesses on irreversible actions.

### Experimental features

These are in the codebase but not recommended for daily use yet —
expect rough edges:

- **ELY Trainer** — screen-control tutoring via vision LLM (needs the
  desktop daemon). Works, but costly in API credits.
- **MCP generator** — on-the-fly creation of MCP connector servers.
  Useful for power-users who know what MCP is.
- **Wake-word voice mode** — the browser voice overlay listens for
  "Éli" but wake-word detection is browser-side; on Android the mic
  button must be pressed explicitly.

---

## Useful Commands

```bash
make up                    # Start all services
make down                  # Stop all services
make restart s=backend     # Restart one service
make logs s=backend        # Stream logs
make build                 # Full rebuild (after code changes)
make ps                    # Check container status

# Ollama models
make slm-pull m=qwen2.5:7b # Pull a model into the Docker Ollama
make slm-enable            # Enable local model for simple tasks
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Installation](./docs/installation.md) | Full setup — macOS, Linux, Windows (Docker) |
| [Deployment](./docs/DEPLOYMENT.md) | External access — Cloudflare Tunnel, Tailscale, fixed IP |
| [User Guide](./docs/user-guide.md) | Interface walkthrough and features |
| [Architecture](./docs/architecture.md) | Technical deep-dive |
| [Security](./docs/security.md) | Security model and threat analysis |
| [Testing](./TESTING.md) | Test suite, smoke tests, debugging |

---

## ⚖️ License

**PolyForm Strict License 1.0.0** — see [LICENSE](./LICENSE).

✅ **Allowed:** personal use, learning, non-commercial research.

❌ **Not allowed without written agreement:**
- Commercial use or integration into a paid service
- Redistribution of modified versions
- Training other AI models on this codebase

For commercial licensing: [franck.olv@gmail.com](mailto:franck.olv@gmail.com)
