# ELY — Exactly Like You

> **Your personal AI agent. Trained on your habits. Bound by your rules. Never acts without your approval.**

ELY is a self-hosted AI agent that integrates with your entire digital life — Google Workspace, web browsing, servers, smart home, desktop automation — while keeping your sensitive data off the LLM and pausing before every irreversible action.

---

## Table of Contents

- [What ELY Can Do](#what-ely-can-do)
- [ELY Desktop — Local Automation](#ely-desktop--local-automation)
- [Multi-Provider LLM Engine](#multi-provider-llm-engine)
- [Security — The Core Difference](#security--the-core-difference)
- [Memory — ELY Knows You](#memory--ely-knows-you)
- [Vault — Encrypted Secret Storage](#vault--encrypted-secret-storage)
- [Analytics Dashboard](#analytics-dashboard)
- [Admin Panel](#admin-panel)
- [Architecture](#architecture)
- [Stack](#stack)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [⚖️ License & Terms of Use](#️-license--terms-of-use)

---

## What ELY Can Do

### Google Workspace

| Ask ELY | What happens |
|---|---|
| "Read my last 5 emails" | Fetches and summarises your latest Gmail messages |
| "Send an email to alice@company.com: subject Meeting Friday" | Drafts the email, pauses for your approval, then sends |
| "What are my appointments this week?" | Lists your Google Calendar events |
| "Create a dentist appointment Friday March 28 at 10:30am" | Creates the event (approval required) |
| "List my recent Drive files" | Shows your recent Google Drive files |
| "Read the document Q1 Report 2026" | Reads the document content |
| "Create a Word document titled Budget 2026" | Creates a new Google Doc |
| "Create a spreadsheet for my monthly budget" | Creates a new Google Sheets spreadsheet |
| "Show my to-do list" | Lists your Google Tasks |
| "Add Call the doctor to my tasks" | Creates a new task |

### Web, News & Weather

| Ask ELY | What happens |
|---|---|
| "Search for a flight Paris–New York for July" | Browses the web and summarises results |
| "Go to lemonde.fr and read the front page" | Navigates to the page and extracts main content |
| "Take a screenshot of this site" | Screenshots the current page |
| "What's the weather in Paris?" | Fetches current weather from wttr.in |
| "Lyon forecast for the next 3 days" | Shows a 3-day forecast |
| "Latest news in France" | Pulls recent headlines from Google News RSS |
| "Translate hello world to French" | Translates text via MyMemory API |

### Automation & Infrastructure

| Ask ELY | What happens |
|---|---|
| "Remind me every Monday at 9am to check my calendar" | Creates a recurring scheduled task |
| "Summarise my unread emails every Friday evening at 6pm" | Scheduled task with email tool |
| "Run df -h on my prod server" | Executes the command via SSH (approval required) |
| "Run docker ps on my-server" | Lists running containers on your server (approval required) |
| "Generate a QR code for https://example.com" | Creates a downloadable QR code image |
| "Read the PDF invoice.pdf and summarise it" | Extracts and summarises PDF content |
| "Transcribe this audio file" | Converts speech to text via Whisper |
| "Read the YouTube video at this URL" | Fetches transcript from YouTube |

### Communication Channels

ELY works across multiple channels simultaneously with **the same agent, same security, same memory**:

- **Web UI** — React chat interface with voice output (TTS), file/image attachments, conversation history
- **Telegram Bot** — full agent access from your mobile, inline HITL approval buttons
- **ntfy (Android)** — push notifications for HITL approvals with action buttons

---

## ELY Desktop — Local Automation

ELY Desktop is a native Go daemon that runs on your personal computer and connects to the ELY server. It exposes local capabilities that are impossible from a cloud server:

| Capability | What it does |
|---|---|
| **Screen capture** | Takes screenshots of your desktop |
| **Keyboard / mouse control** | Types text, presses keys, clicks anywhere on screen |
| **App launcher** | Opens applications by name |
| **Clipboard access** | Reads and writes your clipboard |
| **Local file operations** | Reads, writes, moves, deletes local files (approval required) |
| **System info** | CPU, memory, disk, running processes |

The daemon connects via WebSocket to your ELY server. Your desktop never needs to be publicly reachable — the connection is outbound from your machine.

**Building the daemon:**

```bash
cd desktop
go build -o ely-desktop ./cmd/daemon
./ely-desktop --server wss://your-ely-server --token YOUR_TOKEN
```

---

## Multi-Provider LLM Engine

ELY routes each request to the optimal model based on detected complexity, with automatic fallback if a provider is unavailable or over quota. **All tier assignments are fully configurable in Settings — no code change needed.**

### Complexity Tiers (default routing)

| Badge | Tier | Default Chain | Use Case |
|---|---|---|---|
| **A** | Simple | Ollama (local) | Quick questions, short answers |
| **B** | Standard | GLM-4.7 → Gemini → Claude | Everyday tasks, tool use, moderate reasoning |
| **C** | Complex | GLM-4.7 → Claude (cached) → Gemini | Code, deep analysis, multi-step workflows |
| **IMG** | Vision | Gemini → GLM-4.7 | Image analysis, screenshots |
| **SYS** | Maintenance | Ollama (local) | Background tasks: memory extraction, scheduled jobs |

Each tier has an **ordered provider list** and a **fallback toggle** — if disabled, only the first provider is tried. Reorder providers with up/down arrows in **Settings → Routing Levels**.

### Supported Providers

| Provider | Models | Notes |
|---|---|---|
| **OpenRouter** | 200+ models (Meta, Google, Mistral, Qwen, DeepSeek…) | Universal AI gateway — free models available; browsable in Settings |
| **Zhipu AI (GLM)** | glm-4.7, glm-4-plus, glm-4-air, glm-4-flash | Automatic prefix caching (~80% cost reduction); OpenAI-compatible API |
| **Anthropic Claude** | claude-sonnet-4-6, claude-opus-4-6, haiku | Prompt caching enabled (up to 90% cost reduction on system prompts) |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash | Implicit caching; best multimodal support |
| **DeepSeek** | deepseek-chat, deepseek-reasoner | Cost-efficient; strong at coding and reasoning |
| **Mistral AI** | mistral-small, mistral-medium, mistral-large | European servers, GDPR-compliant |
| **Ollama** | qwen2.5, llama3, mistral, phi3, … | 100% local — no data leaves your machine, zero cost |

Switch provider and model at any time in **Settings** — no restart required. If a provider returns a quota or rate-limit error (HTTP 429), ELY **automatically retries** with the next available provider.

### OpenRouter — Universal Gateway

OpenRouter gives access to 200+ models from a single API key. From the **Settings** screen you can:

- Browse the full catalogue live (fetched directly from OpenRouter)
- Toggle **Free models only** to filter to zero-cost options
- Search by model name or provider
- Select any model and save in one click

### Context Caching

ELY activates context caching on every provider that supports it:

- **GLM** — automatic prefix caching; cached tokens billed at ~1/5 price
- **Anthropic** — `anthropic-beta: prompt-caching-2024-07-31` header; system prompt always cached
- **Gemini** — implicit caching handled by Google's infrastructure
- **OpenRouter** — caching depends on the underlying model selected

---

## Security — The Core Difference

ELY was designed from day one so that **the AI model never sees your real sensitive data** and **never acts irreversibly without your explicit approval**.

### Data Masking Pipeline

Before any input reaches the LLM, ELY's SecurityFilter scans it and replaces sensitive values with opaque placeholders:

```
Your input:
  "Transfer €500 to alice@company.com from account FR76 3000 ..."

What the LLM receives:
  "Transfer €500 to [EMAIL_0] from account [IBAN_0] ..."

What you see in the response:
  "Transferring €500 to alice@company.com ..."  ← real values restored
```

Detected and masked automatically:
- Email addresses → `[EMAIL_0]`, `[EMAIL_1]`, …
- Credit card numbers → `[CARD_0]`
- IBAN numbers → `[IBAN_0]`
- API tokens and secrets → `[TOKEN_0]`
- Phone numbers → `[PHONE_0]`

### HITL — Human-in-the-Loop

Every irreversible action is **paused** before execution. ELY presents what it wants to do and waits for one of three responses:

```
ELY wants to execute:
  Tool   : send_email
  To     : alice@example.com
  Subject: "Meeting Friday"

  [ ✅ Allow once ]   [ ❌ Deny once ]   [ 🛡️ Ban permanently ]
```

- **Allow once** — the action runs this time. ELY will ask again next time.
- **Deny once** — the action is cancelled. ELY continues the conversation.
- **Ban permanently** — the action is cancelled AND a permanent rule is stored in memory. ELY will never propose this action again, even in future sessions.

HITL works on three channels simultaneously:
- Inline cards in the **web UI**
- Inline keyboard buttons in **Telegram**
- Push notification action buttons via **ntfy** (Android)

### No Credential Exposure

Your Google OAuth tokens and API keys are stored locally and injected at execution time via `InjectedToolArg`. The AI model only receives the result of a tool call (e.g., a list of email subjects), never the credentials used to call it.

### GDPR-Friendly Options

If you do not want your data processed outside Europe or your own infrastructure:

| Provider | Data location |
|---|---|
| **Ollama** | 100% local — no data ever leaves your machine |
| **Mistral AI** | European servers, GDPR-compliant |
| **Zhipu AI (GLM)** | China-based cloud, cost-efficient |
| **Anthropic Claude** | US servers |
| **Google Gemini** | US servers |
| **DeepSeek** | China-based cloud |

### CNIL-Compliant Password Policy

Passwords are enforced at both frontend (real-time strength indicator) and backend to meet French CNIL recommendations:

- Minimum 12 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

Users can change their own password at any time in **Settings**. Admins can reset any user's password from the **Admin Panel**.

---

## Memory — ELY Knows You

ELY maintains a persistent, multi-layer memory that survives across sessions and conversations.

### Memory Layers

| Layer | Storage | Purpose |
|---|---|---|
| **Semantic memory** | Qdrant (vector DB) | Facts, preferences, context — retrieved by similarity |
| **Keyword memory** | SQLite FTS5 | Fast exact-match recall of names, dates, IDs |
| **Temporal decay** | Score weighting | Recent memories are prioritised; old ones fade |
| **Permanent constraints** | Qdrant (constraint collection) | "Ban" HITL decisions — never forgotten, always enforced |

### What ELY Remembers

ELY automatically extracts and stores:
- Your preferences ("I prefer dark mode", "always use formal tone")
- Important facts ("my cat is named Luna", "my manager is Sarah")
- Recurring patterns ("I check emails every morning")
- Security rules ("never send files to external addresses")

### User Memory Profile

Each user has a queryable memory profile accessible from Settings. You can view, search, and delete any stored memory.

---

## Vault — Encrypted Secret Storage

The Vault is an encrypted key-value store for your secrets (API keys, passwords, tokens) that are injected into tool calls at runtime without ever being sent to the LLM.

- Secrets encrypted at rest with AES-256-GCM
- Master password protected (bcrypt)
- Referenced by name in tool configurations: `{{vault:my_api_key}}`
- Automatic injection before LLM call, automatic masking in output

---

## Analytics Dashboard

The dashboard gives you full visibility into how ELY is using LLM resources:

| Widget | What it shows |
|---|---|
| **Summary cards** | Total requests, tokens, and estimated cost for the selected period |
| **Daily usage chart** | Token consumption and cost per day (line chart) |
| **Top skills** | Which tools/skills are used most often |
| **HITL breakdown** | Allow / Deny / Ban decision counts |
| **Provider breakdown** | Token usage and cost per LLM provider and model |

Data is retained per-user. Filter by period (7, 14, 30 days).

---

## Admin Panel

The admin panel (accessible to the first registered account) lets you:

- **Create users** with email, username, password, and role
- **Enable/disable accounts** (toggle active status)
- **Reset passwords** for any user
- **View usage stats** per user
- **Manage MCP servers** (Model Context Protocol)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           Channels                               │
│   Web UI (Next.js)    Telegram Bot    ntfy (Android push)        │
└──────────┬────────────────┬──────────────────┬───────────────────┘
           │                │                  │
┌──────────▼────────────────▼──────────────────▼───────────────────┐
│                        FastAPI Backend                            │
│                                                                   │
│  SecurityFilter ──► Complexity Router ──► LangGraph Agent        │
│  (PII masking)        (SIMPLE / MEDIUM /   (tool calling loop)   │
│                        COMPLEX / IMAGE)           │               │
│                                                   ▼               │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                      Tool Router                          │   │
│   │  Gmail · Calendar · Drive · Docs · Sheets · Tasks         │   │
│   │  Web Browser (Playwright) · Weather · News · Translation  │   │
│   │  SSH · Scheduler · QR Code · PDF · Whisper · YouTube      │   │
│   │  Desktop (via ELY Desktop daemon)                         │   │
│   └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  HITL Manager ──► Web UI / Telegram / ntfy                       │
│  Analytics Logger ──► usage_logs table                           │
└───────────────────────────────────┬──────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────┐
│                           Storage                                 │
│   Qdrant (vector)       SQLite FTS5 (keyword)                    │
│   Memory · constraints  Conversations · usage logs · settings    │
│   Vault (AES-256-GCM)   User profiles · scheduled tasks          │
└───────────────────────────────────────────────────────────────────┘
```

**Key design points:**

- **Skill plugin system** — each capability is a `Skill` dataclass: one file, one import, fully decoupled. Enable/disable per user.
- **Complexity-based routing** — requests are classified before reaching the LLM so that simple questions use cheap local models and complex tasks get the most capable model.
- **Hybrid memory** — Qdrant semantic search + SQLite FTS5 keyword search + temporal decay. ELY remembers facts about you automatically across sessions.
- **Multi-channel** — same agent graph, same security, same memory — web, Telegram, or push notification.
- **Isolated browser contexts** — each user gets their own sandboxed Playwright Chromium instance.
- **MCP support** — connect any Model Context Protocol server and expose its tools to the agent automatically.

---

## Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · LangGraph · uv |
| Frontend | Next.js 14 · TypeScript · Tailwind CSS · Three.js |
| Auth | JWT (python-jose) · Argon2 |
| LLM | OpenRouter (200+ models) · Zhipu GLM · Anthropic Claude · Google Gemini · DeepSeek · Mistral · Ollama |
| Memory | Qdrant (vector) · SQLite FTS5 |
| Browser automation | Playwright (Chromium, headless) |
| Desktop daemon | Go (WebSocket, pyautogui bridge) |
| SSH | Paramiko + command whitelist |
| TTS | edge-tts |
| Notifications | ntfy · Telegram Bot API |
| Vault | AES-256-GCM (Python cryptography) |

---

## Quick Start

**Prerequisites**: Docker, Python 3.12+, Node.js 18+

```bash
# 1. Clone
git clone https://github.com/your-username/ely-agent.git
cd ely-agent

# 2. Start infrastructure (Qdrant + Ollama)
docker compose up -d qdrant ollama

# 3. Configure backend
cd backend && cp .env.example .env
# Edit .env: set at least JWT_SECRET_KEY
# Optionally add: ANTHROPIC_API_KEY, ZHIPU_API_KEY, GEMINI_API_KEY,
#                  OPENROUTER_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY, etc.

# 4. Install backend dependencies
pip install uv && uv sync
uv run playwright install chromium

# 5. Install frontend
cd ../frontend && npm install

# 6. Launch
cd .. && ./start.sh
```

Open **http://localhost:3000** — register (first account becomes admin) and start chatting.

### Docker Compose (recommended for VPS)

```bash
docker compose up -d
```

The full stack (backend, frontend, Qdrant, Ollama, ntfy) starts automatically.

### API Keys

All API keys are managed through the **Settings → LLM Providers** screen in the UI — no restart needed. Keys are stored encrypted in the database. You can also set them as environment variables in `.env` as fallback defaults.

---

## Documentation

| Document | Description |
|---|---|
| [Installation Guide](./docs/installation.md) | Full setup instructions for Linux, macOS, Windows |
| [User Guide](./docs/user-guide.md) | Interface walkthrough, features, security |
| [Architecture](./docs/architecture.md) | Technical architecture deep-dive |
| [Security](./docs/security.md) | Security model and threat analysis |
| [Memory](./docs/memory.md) | How hybrid memory works |
| [Desktop Daemon](./docs/desktop.md) | ELY Desktop setup and capabilities |
| [Roadmap](./docs/roadmap.md) | Completed phases and future plans |

---

## ⚖️ License & Terms of Use

This project is distributed under the **PolyForm Strict License 1.0.0** — see [LICENSE](./LICENSE).

**What you CAN do:**

- Use this AI agent for personal testing, learning, or non-commercial research projects.
- Read the source code to understand how it works.

**What you CANNOT do without prior written agreement:**

- **Commercial Use**: You may not sell this agent, integrate it into a paid service, or use it to generate revenue within a company.
- **Modification & Redistribution**: You are not permitted to modify the code and redistribute modified versions (even for free).
- **Model Training**: Using the data or structure of this agent to train other AI models is strictly prohibited.

> **Note:** If you wish to obtain a commercial licence or use this agent in a professional context, please contact me directly at: [franck.olv@gmail.com](mailto:franck.olv@gmail.com)

---

## ⚖️ Licence et Conditions d'Utilisation

Ce projet est distribué sous la **PolyForm Strict License 1.0.0** — voir [LICENSE](./LICENSE).

**Ce que vous POUVEZ faire :**

- Utiliser cet agent IA pour vos tests personnels, votre apprentissage ou vos projets de recherche non-commerciaux.
- Consulter le code source pour comprendre son fonctionnement.

**Ce que vous NE POUVEZ PAS faire sans accord écrit :**

- **Utilisation Commerciale** : Vous ne pouvez pas vendre cet agent, l'intégrer dans un service payant, ou l'utiliser pour générer des revenus au sein d'une entreprise.
- **Modification et Redistribution** : Vous n'êtes pas autorisé à modifier le code et à redistribuer ces versions modifiées (même gratuitement).
- **Entraînement de Modèles** : L'utilisation des données ou de la structure de cet agent pour entraîner d'autres modèles d'IA est strictement interdite.

> **Note :** Si vous souhaitez obtenir une licence commerciale ou utiliser cet agent dans un cadre professionnel, merci de me contacter directement à : [franck.olv@gmail.com](mailto:franck.olv@gmail.com)
