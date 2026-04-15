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
| Fully open source, PolyForm licence | ✅ | ❌ |

---

## What ELY Can Do

### 🌐 Google Workspace — Full Integration

ELY has read/write access to your entire Google suite. Every destructive action pauses for your approval.

<details>
<summary><strong>Gmail (14 tools)</strong> — read, send, reply, draft, label, search, clean up</summary>

| Ask ELY | What happens |
|---------|-------------|
| "Read my last 5 unread emails" | Fetches and summarises latest Gmail messages |
| "Send an email to alice@company.com: Meeting Friday" | Drafts, pauses for approval, then sends |
| "Reply to Bob's email and say I'll be there" | Replies in-thread (approval required) |
| "Clean up my promotions folder" | Smart cleanup by category |
| "Search for invoices from last month" | Full-text search with filters |

</details>

<details>
<summary><strong>Calendar (6 tools)</strong> — list, create, update, delete, check availability</summary>

| Ask ELY | What happens |
|---------|-------------|
| "What are my appointments this week?" | Lists Google Calendar events |
| "Create a dentist appointment Friday at 10:30am" | Creates with approval |
| "Am I free Thursday between 2pm and 4pm?" | Checks freebusy |

</details>

<details>
<summary><strong>Drive (8 tools)</strong> — list, read, create, update, move, rename, delete</summary>
</details>

<details>
<summary><strong>Google Docs (5 tools)</strong> — create, read, append, find/replace, insert tables</summary>
</details>

<details>
<summary><strong>Google Sheets (7 tools)</strong> — create, read ranges, append rows, update cells, manage tabs</summary>
</details>

<details>
<summary><strong>Tasks (7 tools)</strong> — list, create, complete, update, delete, manage lists</summary>
</details>

<details>
<summary><strong>Contacts / People API (6 tools)</strong> — find, list, create, update, delete</summary>
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
- HITL works on web UI, Telegram inline keyboard, and Android push notifications (ntfy)

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

| Tier | Default | Use case |
|------|---------|---------|
| **A — Simple** | Ollama (local) | Quick questions, zero cost |
| **B — Standard** | Gemini Flash → Claude | Everyday tasks, tool use |
| **C — Complex** | Gemini Pro → Claude | Code, deep analysis, multi-step |
| **IMG — Vision** | Gemini Flash | Images, PDFs, screenshots |
| **SYS — Maintenance** | Ollama | Background tasks, memory |

**Supported providers:** OpenRouter (200+ models) · Anthropic Claude · Google Gemini · DeepSeek · Mistral AI · Zhipu GLM · Ollama (local)

Automatic fallback if a provider is unavailable. Context caching enabled where supported (up to 90% cost reduction).

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

Same agent. Same security. Same memory. Everywhere.

| Channel | Notes |
|---------|-------|
| **Web UI** | Real-time chat, 3D cyberpunk avatar, voice output (TTS), Markdown, file attachments, Stop button |
| **Voice Mode** | Full-screen voice conversation, wake word "Éli", continuous STT→TTS loop, visual feedback |
| **iOS App** | Native SwiftUI, chat + voice mode, Keychain auth, iOS 17+ |
| **Android App** | Kotlin + Jetpack Compose, voice input, FCM push notifications |
| **PWA** | Installable from any browser (manifest + service worker), offline shell, install prompt |
| **Telegram Bot** | Full agent access, inline HITL approval buttons |
| **Slack Bot** | Socket Mode (no public URL needed), Block Kit HITL buttons |
| **Discord Bot** | DM + @mention, emoji-based HITL |
| **WhatsApp** | Meta Cloud API webhook, HITL supported |
| **ntfy (Android)** | Push notifications for HITL approvals with action buttons |

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
│  iOS · Android · PWA · ntfy                                   │
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
│  HITL Manager → Web / Telegram / ntfy                        │
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
| Notifications | ntfy · Telegram · FCM |
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
