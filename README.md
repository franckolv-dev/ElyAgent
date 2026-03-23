# ELY — Your Personal AI Agent, Built for Power and Privacy

> **All the capabilities of a modern AI assistant. None of the credential exposure. Every irreversible action requires your approval.**

ELY is a self-hosted personal AI agent that connects to your Google Workspace, browses the web, manages your schedule, runs commands on your servers, and remembers you across sessions — while keeping your sensitive data off the LLM and asking before it acts.

![ELY dark mode chat interface](./docs/screenshots/chat-dark.png)

---

## What ELY Can Do

### Google Workspace

| Ask ELY | What happens |
|---|---|
| "Lis mes 5 derniers emails" | Fetches and summarises your latest Gmail messages |
| "Envoie un email à alice@exemple.com avec comme sujet Réunion vendredi" | Drafts the email, pauses for your approval, then sends |
| "Quels sont mes rendez-vous cette semaine ?" | Lists your Google Calendar events |
| "Crée un rendez-vous Dentiste vendredi 28 mars à 10h30" | Creates the event (approval required) |
| "Liste mes fichiers Drive récents" | Shows your recent Google Drive files |
| "Lis le document Rapport Q1 2026" | Reads the document content |
| "Crée un document Word avec le titre Budget 2026" | Creates a new Google Doc |
| "Crée une feuille de calcul pour mon budget mensuel" | Creates a new Google Sheets spreadsheet |
| "Montre ma to-do list" | Lists your Google Tasks |
| "Ajoute Appeler le médecin à mes tâches" | Creates a new task |

### Web, News, Weather

| Ask ELY | What happens |
|---|---|
| "Cherche le prix d'un vol Paris–New York pour juillet" | Browses the web and summarises results |
| "Va sur lemonde.fr et lis la une" | Navigates to the page and extracts main content |
| "Prends une capture d'écran de ce site" | Screenshots the current page |
| "Quel temps fait-il à Paris ?" | Fetches current weather from wttr.in |
| "Météo Lyon pour les 3 prochains jours" | Shows a 3-day forecast |
| "Les dernières actualités en France" | Pulls recent headlines from Google News RSS |
| "Traduis hello world en français" | Translates text via MyMemory API |

### Automation and Infrastructure

| Ask ELY | What happens |
|---|---|
| "Rappelle-moi tous les lundis à 9h de consulter mon agenda" | Creates a recurring scheduled task |
| "Résume mes emails non lus chaque vendredi soir à 18h" | Scheduled task with email tool |
| "df -h sur mon serveur de prod" | Executes the command via SSH (approval required) |
| "docker ps sur my-server" | Lists running containers on your server (approval required) |

---

## Security — The Core Difference

ELY was designed from day one so that **the AI model never sees your real sensitive data** and **never acts irreversibly without your explicit approval**.

### Data Masking Pipeline

Before any input reaches the LLM, ELY's SecurityFilter scans it and replaces sensitive values with opaque placeholders:

```
Your input:
  "Envoie 500€ à alice@entreprise.com depuis le compte FR76 3000 ..."

What the LLM receives:
  "Envoie 500€ à [EMAIL_0] depuis le compte [IBAN_0] ..."

What you see in the response:
  "J'envoie 500€ à alice@entreprise.com ..."  ← real values restored
```

Detected and masked automatically:
- Email addresses → `[EMAIL_0]`, `[EMAIL_1]`, ...
- Credit card numbers → `[CARD_0]`
- IBAN numbers → `[IBAN_0]`
- API tokens and secrets → `[TOKEN_0]`
- Phone numbers → `[PHONE_0]`

### HITL — Human-in-the-Loop

Every irreversible action is **paused** before execution. ELY presents what it wants to do and waits for one of three responses:

```
ELY wants to execute:
  Tool   : send_email
  To     : alice@exemple.com
  Subject: "Réunion vendredi"

  [ ✅ Allow once ]   [ ❌ Deny once ]   [ 🛡️ Ban permanently ]
```

- **Allow once**: the action runs this time. ELY will ask again next time.
- **Deny once**: the action is cancelled. ELY continues the conversation.
- **Ban permanently**: the action is cancelled AND a permanent rule is stored in Qdrant. ELY will never propose this action again, even in future sessions.

HITL works on three channels simultaneously:
- Inline cards in the **web UI**
- Inline keyboard buttons in **Telegram**
- Push notifications via **ntfy** (Android)

### No Credential Exposure

Your Google OAuth tokens and API keys are stored locally and injected at execution time via `InjectedToolArg`. The AI model only receives the result of a tool call (e.g., a list of email subjects), never the credentials used to call it.

### RGPD-Friendly Options

If you do not want your data processed outside Europe or your own infrastructure:

| Provider | Data location |
|---|---|
| **Anthropic Claude** | US servers (default) |
| **Mistral AI** | European servers, RGPD-compliant |
| **Ollama** | 100% local — no data ever leaves your machine |
| **DeepSeek** | Cloud, cost-efficient alternative |

Switch providers at any time in Settings — no restart required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Channels                           │
│   Web UI (React)          Telegram Bot                  │
└───────────────┬───────────────────┬─────────────────────┘
                │                   │
┌───────────────▼───────────────────▼─────────────────────┐
│                   FastAPI Backend                        │
│                                                          │
│   SecurityFilter ──► LangGraph Agent ──► Tool Router     │
│   (data masking)       (Claude/Mistral/     │             │
│                         Ollama/DeepSeek)   │             │
│                                            ▼             │
│   Skills: Gmail · Calendar · Drive · Docs · Sheets ·    │
│           Tasks · Scheduler · Weather · News ·          │
│           Translation · Web Browser · SSH · TTS         │
└──────────────────────────────┬──────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────┐
│                     Storage                              │
│   Qdrant (vector)    SQLite FTS5 (keyword)               │
│   Memory + HITL rules + embeddings                       │
└─────────────────────────────────────────────────────────┘
```

**Key design points:**
- **Skill plugin system**: each capability is a `Skill` dataclass — one file, one import, fully decoupled. Enable/disable per user.
- **Hybrid memory**: Qdrant semantic search + SQLite FTS5 keyword search + temporal decay. ELY remembers facts about you automatically across sessions.
- **Multi-channel**: same agent graph, same security, same memory — web or Telegram.
- **Isolated browser contexts**: each user gets their own sandboxed Playwright Chromium instance.

---

## Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · LangGraph · uv |
| Frontend | React · Vite · Tailwind CSS · Three.js |
| Auth | JWT (python-jose) · Argon2 |
| LLM | Anthropic Claude · Mistral AI · Ollama · DeepSeek |
| Memory | Qdrant (vector) · SQLite FTS5 |
| Browser | Playwright (Chromium, headless) |
| SSH | Paramiko + command whitelist |
| TTS | edge-tts |
| Notifications | ntfy · Telegram Bot API |

---

## Quick Start

**Prerequisites**: Docker, Python 3.12+, Node.js 18+

```bash
# 1. Clone
git clone https://github.com/your-username/ely-agent.git
cd ely-agent

# 2. Start Qdrant
docker run -d --name qdrant -p 6333:6333 \
  -v qdrant_storage:/qdrant/storage qdrant/qdrant

# 3. Configure backend
cd backend && cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and JWT_SECRET_KEY

# 4. Install backend
pip install uv && uv sync
uv run playwright install chromium

# 5. Install frontend
cd ../frontend && npm install

# 6. Launch
cd .. && ./start.sh
```

Open **http://localhost:3000** — register (first account = admin) and start chatting.

For detailed instructions including macOS, Windows, and Google OAuth setup, see the **[Installation Guide](./docs/installation.md)**.

---

## Documentation

| Document | Description |
|---|---|
| [Installation Guide](./docs/installation.md) | Full setup instructions for Linux, macOS, Windows |
| [User Guide](./docs/user-guide.md) | Interface walkthrough, features, security |
| [Architecture](./docs/architecture.md) | Technical architecture deep-dive |
| [Security](./docs/security.md) | Security model and threat analysis |
| [Memory](./docs/memory.md) | How hybrid memory works |
| [Roadmap](./docs/roadmap.md) | Completed phases and future plans |

---

## Language Note

The ELY interface is in **French by default** (it was built as a personal assistant for a French-speaking user). The underlying system prompts, code, and API are fully in English. UI language configuration is on the roadmap.

---

## License

MIT License — see [LICENSE](./LICENSE).
