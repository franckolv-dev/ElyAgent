<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — sovereign AI agent" width="200" />

# ELY

### The sovereign AI agent for people who refuse to leak their data to the cloud.

Self-hosted · GDPR-native · multi-LLM · **self-improving** · 10 channels · 190+ built-in tools. Runs on your hardware, masks sensitive data before any model call, asks before every irreversible action.

[**Website**](https://agent-ely.fr) ·
[**Documentation**](./docs/START_HERE.md) ·
[**Licence**](https://agent-ely.fr/pricing.html) ·
[**Roadmap**](https://agent-ely.fr/roadmap.html) ·
[**Discussions**](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Elastic License v2](https://img.shields.io/badge/license-Elastic%20License%20v2-13bbc2?style=flat-square)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/franckolv-dev/ElyAgent/ci.yml?style=flat-square&label=tests)](https://github.com/franckolv-dev/ElyAgent/actions)
[![Stars](https://img.shields.io/github/stars/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/stargazers)

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-orange?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

</div>

> **Note on licensing.** ELY is licensed under the **[Elastic License v2](LICENSE)** — free for any personal use AND any internal business use, regardless of organisation size. Full source published and auditable.

---

<p align="center">
  ELY masks personal data before any LLM call
  <br>
  <sub><i>PII masking in action — sensitive values are masked before cloud model calls (scope &amp; limits in <a href="docs/security.md">docs/security.md</a>).</i></sub>
</p>

---

## Why ELY exists

Cloud AI agents — ChatGPT, Claude, Gemini, the upcoming Google Remy, OpenAI Operator, Microsoft Copilot — are powerful, but they all share the same architecture: **your raw data goes to a third-party server in the United States.** Emails, IBANs, family details, medical records, contract drafts — all transit through models you don't control, in jurisdictions that aren't yours.

For most cloud services that's an accepted tradeoff. **If you handle anything you'd rather not hand to a US server — your inbox, your finances, your family's data — it isn't.**

ELY is a personal AI agent **that runs on your own hardware, masks sensitive data before any model call, asks before every irreversible action, and keeps data inside the EU by default.** It's a non-commercial personal project under the Elastic License v2 — and that licence also covers internal professional use, free of charge.

---

## The four pillars

<table>
<tr>
<td width="50%" valign="top">

### Sovereignty
**Your hardware. Your data. Your jurisdiction.**

- Self-hosted on your Mac, server, NAS, on-prem or sovereign cloud
- Local-first routing — simple/medium tiers run on your local model (Ollama, LM Studio MLX). Mistral preferred for cloud tier C, keeping data inside the EU.
- GDPR-native by construction · DPA available · DPIA template provided
- Zero telemetry · zero phone-home · zero forced cloud dependency
- Source code auditable (Elastic License v2)

</td>
<td width="50%" valign="top">

### Security
**Sensitive data is masked before cloud LLM calls. Irreversible actions never run unattended.**

- **Native PII anonymisation** — emails, IBANs, credit cards, API tokens, phone numbers, French SIRET masked by regex before the prompt is built on the agent path. Coverage, the optional NER layer and known limits are documented in [docs/security.md](docs/security.md).
- **Structural HITL** — every irreversible tool (mail send, file delete, SSH, sharing) pauses for explicit approval. Allow once · deny once · **ban permanently** (persisted across sessions).
- Server-side encrypted vault (AES-256-GCM, key derived from your master password) for credentials.
- Immutable audit trail — every approval logged, exportable for compliance.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Integration
**Plugged into the tools you already use.**

- **Full Google Workspace** — Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts (75 tools, full read/write with HITL on every destructive action)
- 10 channels — Web · Voice (wake-word "Éli") · PWA · iOS native · Android native · Telegram · WhatsApp · Slack · Discord · ntfy push
- Native push notifications for HITL approvals (FCM + APNs) — most competitors only proxy via messaging bots
- 190+ tools across web automation, system, RAG, vault, missions, self-improvement

</td>
<td width="50%" valign="top">

### Architecture
**Multi-user. Multi-LLM. Built to scale from one person to a household.**

- **Multi-user native — and hardened for it** *(June 2026 campaign: 11 releases)* — one deployment serves you or a household. Each user has their own memory, vault, approval queue, **daily LLM budget**, rate limits and storage quota. Secrets encrypted at rest, Alembic migrations, nightly backups, deep healthchecks.
- **Multi-LLM with complexity tiers** — assign different models to Tier A (fast) / B (standard) / C (deep) / IMG / SYS. Local for simple tasks, Mistral or Anthropic for complex ones — your choice, no restart.
- 11 LLM providers supported · auto-fallback on provider outage (per-conversation chain, auto-return after cooldown)
- Channel-to-user mapping prevents impersonation across messaging platforms

</td>
</tr>
</table>

---

## What makes ELY different: it improves itself

Most agents are static. **ELY watches its own failures and gets better — transparently, with you in control.**

- **Learns reusable playbooks from its own mistakes — autonomously.** When a task goes wrong (a refused action, a hallucination block, a low-graded mission), ELY mines the failure into a short Markdown **playbook** — *"when you see X, do Y, never Z"* — evaluates it with a separate judge model, and now **creates and activates the good ones on its own**, no admin click. The library ships with starter playbooks so it's useful from day one, and you can **import community playbooks** (`SKILL.md`) straight from a URL into the review queue.
- **Diagnoses its own "façade successes".** A background loop records, after each autonomous run, whether the agent *actually* did what it claimed — flagging *"reported success, no real effect"* — then **diagnoses the cause** and surfaces a **reviewable fix proposal** on an admin Incidents page. ELY measures its real success rate, not its declared one.
- **Structured missions that ask instead of guessing** *(v1.17)*. Describe a multi-step workflow in simple YAML — `steps`, `foreach` over a previous step's results, and **edge-case handlers**: `on_ambiguous: ask_user("…")`, `on_not_found: skip_with_note("…")`. When ELY hesitates, she **pings you** (web, push, Telegram), you answer, she resumes — while the other items keep running. A live list viewer shows every step and item (✓ ⏳ ⏸ ⊝) with inline answers.
- **Radical transparency.** Two dashboards — `/me/learning` and `/me/state` — show you exactly what ELY learned from you and the model it holds of you (mood, focus, open loops). Editable, killable, never hidden.
- **Cognitive typed memory.** Five memory types (episodic · semantic · procedural · error · constraint) instead of one opaque blob — recalled per-type, across conversations, all local.
- **MCP client.** Consume any Model Context Protocol server — ELY's toolset extends without a code change.
- **MCP server.** ELY is also exposed *as* an MCP server — connect Claude Desktop, Cursor or any MCP client (authenticated by a personal API key) to chat, schedule tasks and search memory.
- **50-scenario regression bench + nightly CI.** Self-improvement ships safely because every subsystem is pinned by a deterministic harness, on top of 1,900+ automated tests.

> *Experimental:* ELY can also generate executable Python **tools** from a description (AST-guarded, admin-reviewed, sandboxed) and a network "io" variant behind a filtering egress proxy. These are kept **behind a flag and off by default** — for a single-user assistant the playbook approach above carries the day, so that's where the loop now focuses.

---

## ELY vs. the Alternatives — An Honest Comparison

We respect what other projects do well. We are explicit about what sets us apart.

| | **ELY** | Other Self-Hosted Agents | Hosted AI Assistants |
|---|:---:|:---:|:---:|
| Self-Hosted on Your Hardware | ✅ | ✅ | ❌ |
| **Anonymized PII before LLM Call** | ✅ Native | ⚠️ Plugin or Absent | ❌ |
| **HITL Enabled by Default, Cannot Be Disabled** | ✅ Structural | ⚠️ Configurable | N/A |
| **Multi-User (one person or a household)** | ✅ | ❌ Often Single-User | ✅ (Cloud Publisher) |
| **Hybrid Local/Cloud Routing** | ✅ Explicit Third Parties | ⚠️ Manual / Partial | ❌ |
| Native Mobile Apps (iOS + Android) | ✅ | ❌ Rare | ✅ |
| Encrypted Vault (Zero-Knowledge) | ✅ AES-256-GCM | ❌ Rare | ❌ |
| Full French Interface | ✅ | ⚠️ Often EN Only | ⚠️ Partial |
| License | Elastic v2 (free internal use, no SaaS resale) | Variable | Proprietary |

> **Our Honest Read.** Other self-hosted agents have larger communities and more channel adapters. **If you handle data you'd rather not leak — yours, your family's — ELY's anonymization pipeline and structural HITL are the reasons to choose it over the alternatives.**

---

## Who ELY is for

**Privacy-conscious individuals & families** — you want a powerful AI assistant but you refuse to send your inbox, banking details and medical history to OpenAI, Google or Anthropic. Run ELY on your own hardware. Free under the Elastic License v2.

ELY is a **non-commercial personal project**. That said, the Elastic License v2 also covers **internal professional use**, free and without any extra agreement — so if it's useful inside your own structure, it's allowed.

---

## Quick start

**Prerequisites:** Docker · Docker Compose · 16 GB RAM (32 GB for local LLMs) · 20 GB disk · `make` (preinstalled on Mac and most Linux) · `openssl` (preinstalled everywhere).

```bash
# 1. Clone
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent

# 2. Configure — minimum: a JWT secret
cp .env.example .env
# Generate a 64-char hex secret and replace the placeholder in .env:
#   macOS / Linux: openssl is always available
sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env && rm .env.bak

# 3. Pick a LLM provider (REQUIRED — without this, ELY can't answer anything)
# Easiest free option: Google Gemini key (Anthropic / Mistral / OpenAI work too)
# 1. Grab a free key at https://aistudio.google.com/apikey
# 2. Paste it into .env on the line GEMINI_API_KEY=
# 3. Change ACTIVE_LLM_PROVIDER from "ollama" to "gemini" in .env
#
# Full provider list and setup links: docs/SETUP_AI_PROVIDERS.md

# 4. Boot the stack (first run downloads ~2 GB of images, takes 5-10 min)
make up

# 5. Watch logs until the backend is healthy
make logs s=backend     # ctrl-C once you see "Application startup complete"

# 6. Open http://localhost:3000 — first signup becomes admin
#    Password policy: min 12 chars, at least one uppercase + one special char (!@#$%^&*…)
```

> **Without an LLM key**: ELY boots fine but every chat message will fail
> with a connection error. The default `ACTIVE_LLM_PROVIDER=ollama`
> assumes a local Ollama is running on the host — install it from
> https://ollama.ai or switch to a cloud provider in `.env`.

→ **[Full setup guide for non-developers →](./docs/START_HERE.md)**
Four scenarios, from 30-min local install (Scenario A) to fully remote deployment with Cloudflare Tunnel and all messaging channels (Scenario D). No prior knowledge of Docker, Google Cloud or APIs assumed.

→ **[Browser Extension setup →](./extension/chrome/README.md)** for ELY to act on your real Chrome tabs (LinkedIn, Gmail, GitHub, Amazon…) with your existing sessions. Optional but it's the killer feature.

→ **[Troubleshooting →](./docs/TROUBLESHOOTING.md)** if `make up` fails, the first chat errors out, or ports clash with another project.

---

## Browser autonomy — ELY acts in your real Chrome

> **The killer feature no cloud agent can replicate.**

ELY ships with a Chrome extension that lets the agent **read and act on the tabs you already have open**, using YOUR authenticated sessions. No headless Playwright with empty cookies — it's your actual browser, with your actual logins.

What this enables, with zero credentials shared:

- *"How many impressions did my last LinkedIn post get?"* → ELY opens linkedin.com (your session, already logged in), reads the data, closes the tab. ~5 seconds.
- *"What's in my Gmail inbox?"* → reads via the Gmail web UI, no API token needed.
- *"Summarise this Amazon order page"* → captures + reads the rendered page, even when anti-bot blocks DOM extraction (falls back to Gemini Vision).

```
You → ELY → Chrome Extension → YOUR Chrome tab → site (with YOUR cookies)
                  ↑
             ELY backend never sees your cookies, never stores credentials
```

**Setup** (one-time, 2 min):
1. `chrome://extensions/` → enable Developer Mode → Load unpacked → select [`extension/chrome/`](./extension/chrome/)
2. Right-click the ⚡ ELY icon → Options → paste your ELY backend URL + access token
3. Done — pop-up turns green when connected

→ Full extension docs: [`extension/chrome/README.md`](./extension/chrome/README.md)

---

## What ELY can do

A real product UI on every surface — not a terminal dressed as a website. ELY treats the UI as a first-class citizen, including for non-technical users.

<details>
<summary><strong>Security pipeline</strong> — PII masking · HITL · vault · audit trail</summary>

- **PII masking pipeline.** Deterministic regex detection of emails, IBANs, credit cards, API tokens, phone numbers (all French formats), SIRET, employee IDs. Deterministic placeholders, reversed only when displayed back to you. This regex layer is the active privacy boundary. (A local NER layer for free-text names/orgs was built and benchmarked, but is **off by default** — it proved too disruptive for an agentic assistant; see [docs/security.md](docs/security.md).)
- **Human-in-the-loop.** Blocks 30+ tool categories by default. Three actions: allow once, deny once, **ban permanently** (persisted across sessions).
- **Encrypted vault.** AES-256-GCM, per-user key derived from password. Zero-knowledge.
- **Audit trail.** Immutable JSON Lines. Exportable for compliance.

[Full security model →](./docs/security.md)

</details>

<details>
<summary><strong>Multi-LLM engine</strong> — your keys, route by complexity tier</summary>

Configure providers in **Settings → AI Models**. Assign each tier (A/B/C/IMG/SYS) to a model. Switch any time, no code, no restart.

- **Cloud:** Mistral (preferred, EU) · Anthropic · OpenAI · Gemini · Qwen API · Moonshot Kimi K2.x · DeepSeek · Zhipu · OpenRouter
- **Local:** Ollama · LM Studio (MLX on Apple Silicon)
- Auto-detected compact prompts so 7B local models actually obey `tool_choice="required"`
- Auto-fallback if a provider goes down — disable per-tier for pure-local testing

</details>

<details>
<summary><strong>Google Workspace integration</strong> — 75 tools, full read/write with HITL</summary>

Gmail · Calendar · Drive · Docs · Sheets · Tasks · Contacts. High-level tools, batch operations, and a `raw_api_call` escape hatch for any method of the official Google Python client. Critical raw calls still trigger HITL. Multi-Google-account support — link several mailboxes to one ELY user.

</details>

<details>
<summary><strong>Missions</strong> — goal-driven loop that survives restarts, now with structured specs</summary>

Give ELY a goal — she breaks it into steps, picks tools, executes, evaluates, replans on failure, and notifies you on completion. Five guardrails: token budget · iteration budget · optional deadline · HITL on critical tools · anti-loop replan after 3 consecutive failures. Every terminal mission is graded by an external **LLM-as-judge** that flags "façade success".

**Structured missions** *(v1.17)* — replace the monolithic prompt with a YAML spec:

```yaml
version: 1
steps:
  - id: enrich
    foreach: "{{ read_companies.output }}"
    do: "Find the CEO of {{ item }} on LinkedIn."
    on_ambiguous: ask_user("Several results for {{ item }} — which one?")
    on_not_found: skip_with_note("Not found")
    on_error: resume_next
```

The LLM stays in the loop (the spec *frames* execution, it doesn't replace reasoning) ; declared edge cases are **signalled, not improvised** ; `ask_user` pauses the item, pings you on every channel, and resumes on your answer while the other items keep running. Live list viewer with inline replies. Deterministic completion — no LLM-judged "done". Legacy free-text missions unchanged.

</details>

<details>
<summary><strong>Learning loop & skills</strong> — ELY turns its mistakes into reusable playbooks</summary>

Failure signals (HITL refusals, hallucination blocks, mission critiques, "missing tool" gaps) feed a learning loop centred on **Markdown playbooks** — short, readable *"when X, do Y, never Z"* procedures the agent follows:

- **Autonomous capture.** A background pass mines recent failures into a playbook, an external judge scores it, and passing ones are **created and activated automatically** — no admin click. The library ships **seeded** so it's useful from day one.
- **Import.** Bring in community playbooks in the open `SKILL.md` format straight from a URL — they land in the admin **review queue** (external content is never auto-activated) before you promote them.
- **Self-diagnosis.** After each autonomous run, a loop checks whether the agent *really* did what it claimed (*"façade success"* detection), diagnoses the cause, and surfaces a **reviewable fix proposal** on an admin Incidents page.

Everything stays auditable and reversible — playbooks are prose you can read, edit, archive. A 50-scenario regression bench + nightly CI keeps the loop honest.

> *Experimental, off by default:* ELY can also generate executable **Python tools** from a description (AST-guarded → ruff → mypy → sandboxed smoke test → admin review → canary HITL), including a network "io" variant behind a filtering egress proxy with declared domains and Vault-injected secrets. For a single-user assistant this rarely pays off (a strong model just does the trivial task inline), so the loop now focuses on playbooks; the code-generation path is kept behind a flag.

</details>

<details>
<summary><strong>Radical transparency</strong> — see what ELY learned about you, and change it</summary>

`/me/learning` shows the failure signals + verdicts ELY recorded; `/me/state` shows the live model it holds of you (mood, focus, recent topics, open loops, energy). Both are user-readable, editable, and killable — no hidden profiling.

</details>

<details>
<summary><strong>Channels</strong> — 10 ways to reach ELY</summary>

Web UI · Voice (wake-word "Éli") · PWA · iOS native · Android native · Telegram · WhatsApp · Slack · Discord · ntfy push. Same agent, same memory, same security across all surfaces.

</details>

<details>
<summary><strong>API access & MCP server</strong> — drive ELY from external clients</summary>

Mint personal API keys in **Settings → Clés API** (`ely_api_…`, shown once, max 20 active, revocable). Use one as a bearer token against ELY's own **MCP server** at `/api/mcp` (FastMCP Streamable-HTTP) — v1 tools: chat one autonomous-safe turn, list/create scheduled tasks, semantic memory search. Intended clients: Claude Desktop, Cursor.

</details>

<details>
<summary><strong>Memory & RAG</strong> — local Qdrant + SQLite FTS5</summary>

PDF · TXT · Markdown · CSV · JSON · DOCX. Everything local — no remote embedding services. ELY decides when to search, reranks results, cites sources. Uploads up to **50 MB** per file (per-user storage quota applies). Note: `.zip` files upload but ELY has no unzip tool — send archives unzipped.

</details>

</details>

<details>
<summary><strong>LLM Arena, Desktop daemon, Smart File Manager</strong></summary>

Blind LLM head-to-head ELO ranking · Native Go desktop daemon for local automation · On-device duplicate detection on Android (files never transit the backend).

</details>

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  USER INPUT  ─→  PII Filter (mask)  ─→  Complexity Router            │
│                                                          │           │
│  RESPONSE  ←─  Restore real values  ←─  HITL gate  ←─  LangGraph     │
│                                                          │           │
│                                              ┌───────────┼─────────┐ │
│                                              ▼           ▼         ▼ │
│                                         Local LLM     Tools     Cloud│
│                                         (Ollama,     (190+)   (PII-│
│                                         LM Studio)             masked)│
└──────────────────────────────────────────────────────────────────────┘
```

→ [Full architecture deep-dive](./docs/architecture.md)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 · FastAPI · LangGraph · uv |
| Frontend | Next.js 16 · TypeScript · Tailwind · Three.js |
| Mobile | iOS SwiftUI · Android Kotlin/Compose |
| Desktop daemon | Go (Linux · macOS · Windows) |
| LLM providers | 11 (cloud + local) |
| Memory | Qdrant · SQLite FTS5 · fastembed |
| Auth | JWT HS256 · Argon2id · HttpOnly refresh cookie |
| Vault | AES-256-GCM, per-user key derivation |
| Push | FCM · APNs · Telegram · WebSocket |
| Infra | Docker Compose · nginx · Cloudflare Tunnel |

---

## Roadmap

**Shipped** *(May–June 2026)*
- **Self-improving skills loop** *(v2.2)* — ELY mines its real failures into Markdown playbooks and **creates + activates them autonomously**; seeded library; **import community `SKILL.md` from a URL** into the review queue
- **Self-diagnosis loop** *(v2.2)* — detects "façade success", diagnoses the cause, surfaces a reviewable fix proposal on an admin Incidents page
- **Smarter scheduled tasks** *(v2.2)* — `[SILENT]` (monitors stop spamming when nothing changed), true one-shot `@once` (runs once then deletes), edit/run a task without recreating it
- **Chat affordances** *(v2.2)* — LLM-generated conversation titles, regenerate a reply, edit-and-resend the last message
- **Structured missions** *(v1.17)* — YAML specs with `foreach` + edge-case handlers; `ask_user` pauses, pings you, resumes on your answer; live list viewer
- **Multi-user hardening campaign** *(11 releases, v1.14.x)* — cross-user isolation audit, per-user budgets/quotas/rate limits, secrets encrypted at rest, Alembic migrations, nightly backups, deep healthchecks
- **Cognitive typed memory** — 5 memory types, cross-conversation recall
- **Radical transparency** — `/me/learning` + `/me/state` dashboards
- **MCP client** — consume any Model Context Protocol server
- **MCP server** *(v2.2)* — ELY exposed AS a Model Context Protocol server (authenticated `/api/mcp` endpoint, personal API keys) so you can drive it from Claude Desktop / Cursor (ely_chat, scheduled tasks, typed-memory search)
- **50-scenario regression bench** + nightly CI · 1,900+ automated tests

**Maybe next** *(optional — this is a personal project, no roadmap pressure)*
- **Anthropic prompt-cache markers** — shave multi-turn input cost on the Anthropic tier.

→ [Full public roadmap →](https://agent-ely.fr/roadmap.html)

---

## Licence

**Source code** — [Elastic License v2](LICENSE)

In plain language (informative — the [LICENSE](LICENSE) file is the legal text):

**You are free to** — use ELY for any personal use (household, family) · use it for any internal business use, any organisation size · modify the source and run your version · distribute it (modified or not) keeping the LICENSE + copyright notices.

**You may not** — offer ELY as a hosted or managed service to third parties (no SaaS resale) · remove or hide the copyright/licence notices · disable or circumvent any licence-key mechanism.

→ [Plain-language summary on the official site →](https://agent-ely.fr/pricing.html)

**Trademark.** The names **ELY**, **Éli**, **agent-ely.fr**, the 3D avatar and the lightning-bolt logo are protected separately from the code.

📩 **Contact:** [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — replies within 48h, always.

---

## Contributing

ELY is open source under the Elastic License v2. ✅ Bug fixes · documentation · translations · channel adapters · performance · tests · ⚠️ Architectural changes — open an issue first.

[Full contribution guide →](./CONTRIBUTING.md) · [Code of Conduct →](./CODE_OF_CONDUCT.md) · [Security policy →](./SECURITY.md)

---

<div align="center">

**Built in Nouvelle-Aquitaine, France **

[Website](https://agent-ely.fr) · [Documentation](./docs/START_HERE.md) · [Sponsor](https://github.com/sponsors/franckolv-dev) · [Newsletter](https://agent-ely.fr/newsletter.html)

</div>
