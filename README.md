<div align="center">

<a href="README.md">English</a> · <a href="README.fr.md">Français</a>

<img src="https://agent-ely.fr/ely-logo.jpeg" alt="ELY — sovereign AI agent" width="200" />

# ELY

### A self-hosted AI agent that anonymises sensitive data *before* any LLM call.

Multi-user · multi-channel · GDPR-native · HITL on every irreversible action.
Built for individuals, families and SMBs that can't afford to leak data to third-party AI.

[**Website**](https://agent-ely.fr) ·
[**Documentation**](./docs/START_HERE.md) ·
[**Pricing**](https://agent-ely.fr/pricing.html) ·
[**Discussions**](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Source-available](https://img.shields.io/badge/source--available-PolyForm%20Strict%201.0-13bbc2?style=flat-square)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/franckolv-dev/ElyAgent/ci.yml?style=flat-square&label=tests)](https://github.com/franckolv-dev/ElyAgent/actions)
[![Stars](https://img.shields.io/github/stars/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/stargazers)
[![Discussions](https://img.shields.io/github/discussions/franckolv-dev/ElyAgent?style=flat-square&color=13bbc2)](https://github.com/franckolv-dev/ElyAgent/discussions)

[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-orange?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

</div>

> **Note on licensing.** ELY is **source-available**, not open-source in the OSI sense. The full source is published, auditable and free for personal, family and educational use. Commercial deployment requires a [commercial licence](https://agent-ely.fr/pricing.html). We chose this model so the project can be sustained long-term without venture capital or shutdown risk.

---

## Why ELY

Most AI agents send your raw data — emails, IBANs, client names, medical notes — straight to a third-party LLM. The agent ecosystem grew up fast in 2025-2026; security didn't. ELY was built on three uncompromising design choices:

<table>
<tr>
<td width="50%" valign="top">

### 🛡️ PII never reaches the LLM
Emails, IBANs, credit cards, API tokens, phone numbers, French SIRET — automatically detected and replaced with deterministic placeholders **before** any prompt is built. The model sees `[EMAIL_0]`. You see the real value. **Native, not a plugin. Cannot be silently disabled.**

</td>
<td width="50%" valign="top">

### ✋ HITL on every irreversible action
Mail send, file delete, SSH command, sharing — every destructive tool pauses for explicit approval. Same UX on web, Telegram, Slack, Outlook, mobile push. Approve once · deny once · **ban permanently**, persisted across sessions.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 👥 Multi-user, native
A single deployment serves a family, a team, or a small business. Each user has their own memory, their own credentials vault, their own approval queue. Channel mappings prevent impersonation across messaging platforms.

</td>
<td width="50%" valign="top">

### ⚡ Hybrid local / cloud routing
Simple and medium tasks route to your local model (Ollama, LM Studio MLX). Complex tasks reach a cloud API — only after PII has been masked. **Configurable per complexity tier, no code, no restart.**

</td>
</tr>
</table>

---

## ELY vs alternatives — an honest comparison

We respect what other projects do well. We're explicit about where we draw the line.

| | **ELY** | Other self-hosted agents | Hosted AI assistants |
|---|:---:|:---:|:---:|
| Self-hosted on your hardware | ✅ | ✅ | ❌ |
| **PII anonymised before LLM call** | ✅ Native | ⚠️ Plugin or absent | ❌ |
| **HITL on by default, not removable** | ✅ Structural | ⚠️ Configurable | N/A |
| **Multi-user (family / team / SMB)** | ✅ | ❌ Mostly single-user | ✅ (vendor cloud) |
| **Hybrid local / cloud routing** | ✅ Explicit tiers | ⚠️ Manual / partial | ❌ |
| Native mobile apps (iOS + Android) | ✅ | ❌ Rare | ✅ |
| Encrypted vault (zero-knowledge) | ✅ AES-256-GCM | ❌ Rare | ❌ |
| Native French interface | ✅ | ⚠️ Often EN-only | ⚠️ Partial |
| License | Source-available | Varies | Proprietary |
| Commercial licence available | ✅ | Varies | N/A |
| Maintained by | Solo (FR 🇫🇷) | Varies | Big Tech |

> **Honest take.** Other self-hosted agents have larger communities and more channel adapters. **If you handle data you can't afford to leak — yours, your family's, your clients' — ELY's anonymisation pipeline and structural HITL are why you'd pick it over the alternatives.**

---

## Who ELY is for

ELY is made for two distinct audiences. Both run the same codebase.

🏠 **Privacy-conscious individuals & families** — you want a powerful AI assistant but you refuse to send your inbox, banking details and medical history to OpenAI or Anthropic. Free under the personal licence. Up to 4 family members on one deployment.

🏢 **SMBs in regulated sectors** *(commercial licence)* — law firms, accounting practices, medical practices, HR consultancies, notaries, local government. You handle data covered by professional secrecy or GDPR. ELY's anonymisation pipeline is the difference between *"we considered AI"* and *"we deployed AI."*

→ Detailed personas, deployment scenarios and pricing on **[agent-ely.fr](https://agent-ely.fr)**.

---

## Quick start

**Prerequisites:** Docker · Docker Compose · 16 GB RAM (32 GB for local LLMs) · 20 GB disk.

```bash
# 1. Clone
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent

# 2. Configure — minimum: a JWT secret
cp .env.example .env
echo "JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" >> .env

# 3. Boot the stack
make up

# 4. Open http://localhost:3000 — first signup becomes admin
```

→ **[Full setup guide for non-developers →](./docs/START_HERE.md)**
Four scenarios, from 30-min local install (Scenario A) to fully remote deployment with Cloudflare Tunnel and all messaging channels (Scenario D). No prior knowledge of Docker, Google Cloud or APIs assumed.

---

## What ELY can do

A real product UI on every surface — **not a terminal dressed as a website.** Many self-hosted agents ship terminal-first; ELY treats the UI as a first-class citizen, including for non-technical users.

<details>
<summary><strong>🔒 Security pipeline</strong> — PII masking · HITL · vault · audit trail</summary>

- **PII masking pipeline.** Regex + ML-assisted detection of emails, IBANs, credit cards, API tokens, phone numbers, French SIRET, employee IDs. Deterministic placeholders. Reversed only when displayed back to you.
- **Human-in-the-loop.** Blocks 30+ tool categories by default. Three actions: allow once, deny once, **ban permanently** (persisted across all future sessions).
- **Encrypted vault.** AES-256-GCM, per-user key derived from password. Zero-knowledge — the server cannot read after lock. Stores API keys, OAuth tokens, channel credentials.
- **Audit trail.** Every approval decision logged immutably (JSON Lines). Exportable for compliance.

[Full security model →](./docs/security.md)

</details>

<details>
<summary><strong>🤖 Multi-LLM engine</strong> — bring your own keys, route by complexity</summary>

Configure providers in **Settings → AI Models**. Assign each tier (A/B/C/IMG/SYS) to a model. Switch any time, no restart. Local models (Ollama, LM Studio) get auto-detected compact prompts so 7B models actually obey `tool_choice="required"`.

- **Cloud:** OpenAI · Anthropic · Gemini · Qwen API · Moonshot Kimi K2.x · Mistral · DeepSeek · Zhipu · OpenRouter
- **Local:** Ollama · LM Studio (MLX on Apple Silicon)
- **Auto-fallback** if a provider goes down — disable per-tier for pure-local testing.
- **Anthropic prompt caching** enabled where supported (up to 90% cost reduction).

</details>

<details>
<summary><strong>🎯 Missions</strong> — goal-driven loop that survives restarts</summary>

Give ELY a goal — she breaks it into steps, picks tools, executes, evaluates, replans on failure, and notifies you on completion. Survives backend restarts (LangGraph SQLite checkpointer).

Five guardrails: token budget · iteration budget · optional deadline · HITL on critical tools · anti-loop replan after 3 consecutive failures. Notifications in parallel: web UI · Telegram DM · ntfy push.

</details>

<details>
<summary><strong>📡 Channels</strong> — 10 ways to reach ELY</summary>

Web UI · Voice (wake-word "Éli") · PWA · iOS native · Android native · Telegram · WhatsApp · Slack · Discord · ntfy push.

Same agent, same memory, same security across all surfaces. Native iOS (SwiftUI) and Android (Kotlin/Compose) apps with FCM/APNs push for HITL approvals — most competitors only proxy via messaging bots.

</details>

<details>
<summary><strong>📚 Memory & RAG</strong> — local Qdrant + SQLite FTS5</summary>

PDF · TXT · Markdown · CSV · JSON · DOCX. fastembed + Qdrant for semantic retrieval, SQLite FTS5 for keyword. ELY decides whether to search before answering, reranks results, cites sources. No data sent to remote embedding services — everything local.

</details>

<details>
<summary><strong>⚔️ LLM Arena</strong> — blind head-to-head ELO ranking</summary>

Pick any two of your configured providers. Vote without knowing which is which. K=32 ELO leaderboard. Local providers pinged before being added — no `[connection failed]` matches.

</details>

<details>
<summary><strong>🖥️ ELY Desktop</strong> — native Go daemon for local automation</summary>

Outbound WebSocket — your desktop never needs to be publicly reachable. Capabilities: screen capture · keyboard/mouse · app launcher · clipboard · local file ops (HITL) · system info.

</details>

<details>
<summary><strong>📱 Smart File Manager (Android)</strong> — on-device cleanup</summary>

MD5-based exact-duplicate detection (size-pruned), perceptual dHash for visual duplicates (Hamming ≤6), declarative filters (size/age/category/extension). **Files never transit the backend** — everything stays on your phone.

</details>

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  USER INPUT  ─→  SecurityFilter (PII masking)  ─→  Complexity Router │
│                                                          │           │
│  RESPONSE  ←─  Restore real values  ←─  HITL gate  ←─  LangGraph     │
│                                                          │           │
│                                              ┌───────────┼─────────┐ │
│                                              ▼           ▼         ▼ │
│                                          Local LLM    Tools     Cloud│
│                                          (Ollama)     (148)    (PII-│
│                                                                masked)│
└──────────────────────────────────────────────────────────────────────┘
```

A multi-channel, multi-user, hybrid local/cloud agent built on FastAPI + LangGraph (backend), Next.js 16 (frontend), native iOS/Android clients, and a Go desktop daemon.

→ [Full architecture deep-dive](./docs/architecture.md) · [Security model](./docs/security.md)

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
| Browser automation | Playwright |
| STT / TTS | faster-whisper · edge-tts |
| Auth | JWT HS256 · Argon2id · HttpOnly refresh cookie |
| Vault | AES-256-GCM, per-user key derivation |
| Push | FCM · APNs · Telegram · WebSocket |
| Infra | Docker Compose · nginx · Cloudflare Tunnel |

---

## Roadmap

**Sprint 0** ✅ *May 2026* — Public launch. UI refresh, multi-domain routing, mono-agent toggle, Moonshot Kimi K2.x, anti-hallucination guards, 92/92 tests green.

**Sprint 1** *June 2026* — Cross-conversation memory recall (FTS5 + LLM-summarised retrieval). Biggest perceived-value sprint of the year.

**Sprint 2** *June 2026* — Auto-discovery tool registry (AST-based `@register` decorator).

**Sprint 3** *July 2026* — User State Vector (mood · current_focus · open_loops · energy_budget) — closest functional equivalent to a transparent World Model.

**Sprint 4** *August 2026* — MCP client + server. Consume any MCP server (Claude Desktop, Cursor, Zed). Expose ELY as MCP server too.

→ [Full public roadmap with effort tags →](https://agent-ely.fr/roadmap.html)

🤝 [Want to influence the roadmap? Open a discussion →](https://github.com/franckolv-dev/ElyAgent/discussions)

---

## Contributing

ELY is source-available. Contributions are welcome within the bounds of the licence:

✅ Bug fixes · documentation · translations · channel adapters · performance improvements · test coverage
⚠️ Architectural changes — open an issue first
❌ Forks for commercial use without prior agreement · removal of licence headers · code disabling HITL by default

[Full contribution guide →](./CONTRIBUTING.md) · [Code of Conduct →](./CODE_OF_CONDUCT.md) · [Security policy →](./SECURITY.md) (please disclose vulnerabilities responsibly via email)

---

## Licence & commercial use

**Source code** — [PolyForm Strict License 1.0.0](LICENSE)

✅ **Free for:** personal use · family use · learning · non-commercial research
❌ **Requires a commercial licence:** any deployment generating revenue · integration into a paid product · redistribution of modified versions · training other AI models on this codebase

We offer **transparent annual pricing**, by organisation, no per-user or per-LLM-call cost:

| Tier | Scope | Price |
|------|-------|-------|
| **Personal** | Family, learning, evaluation | **Free** |
| **Pro** | 1 organisation · up to 5 users | **€490 / year** |
| **Business** | 1 organisation · up to 25 users · SSO included | **€1,990 / year** |
| **Enterprise** | Multi-instance · unlimited users · 4h SLA | On quote |

→ [Full licensing FAQ + sample contract →](https://agent-ely.fr/pricing.html)

**Trademark.** The names **ELY**, **Éli**, **agent-ely.fr**, the 3D avatar and the lightning-bolt logo are protected separately from the code. Fork freely — pick your own name and your own logo. [Trademark policy →](./TRADEMARK.md)

📩 **Contact:** [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — replies within 48h, always.

---

<div align="center">

**Built in Nouvelle-Aquitaine, France 🇫🇷** by [Franck Ollivier](https://github.com/franckolv-dev)

[Website](https://agent-ely.fr) · [Documentation](./docs/START_HERE.md) · [Newsletter](https://agent-ely.fr/newsletter.html)

</div>
