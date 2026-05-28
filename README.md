<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — sovereign AI agent" width="200" />

# ELY

### The sovereign AI agent for people and organisations that can't afford to leak data.

Self-hosted · GDPR-native · multi-user · multi-LLM · 10 channels · 148 tools.

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

> **Note on licensing.** ELY is licensed under the **[Elastic License v2](LICENSE)** — free for any personal use AND any internal business use, regardless of organisation size. You can run it, modify it, distribute it. The only restriction: you cannot offer ELY as a hosted or managed service to third parties (no SaaS resale). Full source published and auditable.

---

<p align="center">
  ELY masks personal data before any LLM call
  <br>
  <sub><i>PII masking in action — your sensitive values never reach the model.</i></sub>
</p>

---

## Why ELY exists

Cloud AI agents — ChatGPT, Claude, Gemini, the upcoming Google Remy, OpenAI Operator, Microsoft Copilot — are powerful, but they all share the same architecture: **your raw data goes to a third-party server in the United States.** Emails, IBANs, client names, medical records, contract drafts — all transit through models you don't control, in jurisdictions that aren't yours.

For a curious individual, that's a tradeoff. **For a law firm, a medical practice, an SMB handling contracts or client files — it's a non-starter.** Professional secrecy, GDPR, regulated sectors don't allow that compromise.

ELY is the answer for the people and organisations who need an AI agent **that runs on their hardware, anonymises sensitive data before any model call, asks before every irreversible action, and respects European sovereignty by default.**

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
**Sensitive data never reaches the LLM. Irreversible actions never run unattended.**

- **Native PII anonymisation** — emails, IBANs, credit cards, API tokens, phone numbers, French SIRET, employee IDs masked before any prompt is built. Cannot be silently disabled.
- **Structural HITL** — every irreversible tool (mail send, file delete, SSH, sharing) pauses for explicit approval. Allow once · deny once · **ban permanently** (persisted across sessions).
- Encrypted vault (AES-256-GCM, zero-knowledge) for credentials.
- Immutable audit trail — every approval logged, exportable for compliance.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Integration
**Plugged into the tools your team already uses.**

- **Full Google Workspace** — Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts (76 tools, full read/write with HITL on every destructive action)
- 10 channels — Web · Voice (wake-word "Éli") · PWA · iOS native · Android native · Telegram · WhatsApp · Slack · Discord · ntfy push
- Native push notifications for HITL approvals (FCM + APNs) — most competitors only proxy via messaging bots
- 148 tools across web automation, system, RAG, vault, missions

</td>
<td width="50%" valign="top">

### Architecture
**Multi-user. Multi-LLM. Built to scale across a family or an organisation.**

- **Multi-user native** — one deployment serves a family, a team, or an SMB. Each user has their own memory, vault, approval queue.
- **Multi-LLM with complexity tiers** — assign different models to Tier A (fast) / B (standard) / C (deep) / IMG / SYS. Local for simple tasks, Mistral or Anthropic for complex ones — your choice, no restart.
- 11 LLM providers supported · auto-fallback on outage · Anthropic prompt caching enabled
- Channel-to-user mapping prevents impersonation across messaging platforms

</td>
</tr>
</table>

---

## ELY vs. the Alternatives — An Honest Comparison

We respect what other projects do well. We are explicit about what sets us apart.

| | **ELY** | Other Self-Hosted Agents | Hosted AI Assistants |
|---|:---:|:---:|:---:|
| Self-Hosted on Your Hardware | ✅ | ✅ | ❌ |
| **Anonymized PII before LLM Call** | ✅ Native | ⚠️ Plugin or Absent | ❌ |
| **HITL Enabled by Default, Cannot Be Disabled** | ✅ Structural | ⚠️ Configurable | N/A |
| **Multi-User (Family / Team / SMB)** | ✅ | ❌ Often Single-User | ✅ (Cloud Publisher) |
| **Hybrid Local/Cloud Routing** | ✅ Explicit Third Parties | ⚠️ Manual / Partial | ❌ |
| Native Mobile Apps (iOS + Android) | ✅ | ❌ Rare | ✅ |
| Encrypted Vault (Zero-Knowledge) | ✅ AES-256-GCM | ❌ Rare | ❌ |
| Full French Interface | ✅ | ⚠️ Often EN Only | ⚠️ Partial |
| License | Elastic v2 (free internal use, no SaaS resale) | Variable | Proprietary |

> **Our Honest Read.** Other self-hosted agents have larger communities and more channel adapters. **If you handle data that you cannot afford to leak—yours, your family's, your clients'—ELY's anonymization pipeline and structural HITL are the reasons why you should choose it over the alternatives.**

---

## Who ELY is for

**Privacy-conscious individuals & families** — you want a powerful AI assistant but you refuse to send your inbox, banking details and medical history to OpenAI, Google or Anthropic. Run ELY on your own hardware. Free under the Elastic License v2.

**SMBs in regulated sectors** — law firms, accounting practices, medical practices, HR consultancies, notaries, local government. You handle data covered by professional secrecy or GDPR. ELY's anonymisation pipeline is the difference between *"we considered AI"* and *"we deployed AI."* Internal business use is fully covered by the licence — no extra agreement needed.

→ Detailed personas and deployment scenarios on **[agent-ely.fr](https://agent-ely.fr)**.

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

- **PII masking pipeline.** Regex + ML-assisted detection of emails, IBANs, credit cards, API tokens, phone numbers, French SIRET, employee IDs. Deterministic placeholders. Reversed only when displayed back to you.
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
<summary><strong>Google Workspace integration</strong> — 76 tools, full read/write with HITL</summary>

Gmail · Calendar · Drive · Docs · Sheets · Tasks · Contacts. High-level tools, batch operations, and a `raw_api_call` escape hatch for any method of the official Google Python client. Critical raw calls still trigger HITL. Multi-Google-account support — link several mailboxes to one ELY user.

</details>

<details>
<summary><strong>Missions</strong> — goal-driven loop that survives restarts</summary>

Give ELY a goal — she breaks it into steps, picks tools, executes, evaluates, replans on failure, and notifies you on completion. Five guardrails: token budget · iteration budget · optional deadline · HITL on critical tools · anti-loop replan after 3 consecutive failures.

</details>

<details>
<summary><strong>Channels</strong> — 10 ways to reach ELY</summary>

Web UI · Voice (wake-word "Éli") · PWA · iOS native · Android native · Telegram · WhatsApp · Slack · Discord · ntfy push. Same agent, same memory, same security across all surfaces.

</details>

<details>
<summary><strong>Memory & RAG</strong> — local Qdrant + SQLite FTS5</summary>

PDF · TXT · Markdown · CSV · JSON · DOCX. Everything local — no remote embedding services. ELY decides when to search, reranks results, cites sources.

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
│                                         (Ollama,      (148)    (PII-│
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

**Sprint 0** *May 2026* — Public launch. UI refresh, multi-domain routing, Mistral as default cloud tier, mono-agent toggle, anti-hallucination guards, 92/92 tests green.

**Sprint 1** *June 2026* — Cross-conversation memory recall.

**Sprint 2** *June 2026* — Auto-discovery tool registry.

**Sprint 3** *July 2026* — User State Vector (transparent user model).

**Sprint 4** *August 2026* — MCP client + server. Consume any MCP server, expose ELY as MCP server too.

→ [Full public roadmap →](https://agent-ely.fr/roadmap.html)

---

## Licence

**Source code** — [Elastic License v2](LICENSE)

ELY is free for any personal use and for any internal business use of any organisation, regardless of size. Modify it, redistribute it, run it on your hardware — go ahead. The single restriction is that you cannot offer ELY as a hosted or managed service to third parties (no SaaS resale).

→ [Plain-language summary on the official site →](https://agent-ely.fr/pricing.html)

**Trademark.** The names **ELY**, **Éli**, **agent-ely.fr**, the 3D avatar and the lightning-bolt logo are protected separately from the code. Fork freely — pick your own name and your own logo.

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
