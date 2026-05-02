# ELY — Exactly Like You

[![License](https://img.shields.io/badge/license-PolyForm%20Strict%201.0.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-orange)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docs.docker.com/compose/)
[![Self-hosted](https://img.shields.io/badge/self--hosted-100%25-brightgreen)](#deployment)

> **Your personal AI agent. Trained on your habits. Runs on your hardware. Never acts without your approval.**

ELY is a fully self-hosted AI agent that integrates with your entire digital life — Google Workspace, servers, smart home, files, web — while keeping your sensitive data out of the LLM and pausing before every irreversible action.

**Run it on your laptop, a Mac Studio, or a VPS. Access it from anywhere via Cloudflare Tunnel or Tailscale. No subscription. No data leaving your machine unless you choose it.**

> 💡 **Free for personal use.** Commercial use requires a separate license — see [§ License](#-license) at the bottom or contact [contact@agent-ely.fr](mailto:contact@agent-ely.fr).

---

## 🧭 New here ? Start with this

**👉 [docs/START_HERE.md](./docs/START_HERE.md)** — single entry point that walks you through every setup scenario (local-only, LAN+mobile, public domain) with step-by-step guides for Docker install, AI provider keys (Anthropic / Gemini / Kimi / OpenAI / local Ollama / LM Studio), Google OAuth, and mobile push notifications.

The documentation is written for **non-developers**. No prior knowledge of Docker, Google Cloud, or APIs assumed. Every external account creation is linked, every step screenshotted in spirit.

| You're a… | Quick path |
|---|---|
| **Curious user, just wants to try** | [Scenario A](./docs/START_HERE.md#-scénario-a--je-veux-juste-essayer) — 30 min local install with a free Gemini key |
| **Power user, wants Gmail + Calendar** | [Scenario B](./docs/START_HERE.md#-scénario-b--je-veux-quely-voie-mon-gmailcalendar) — adds Google OAuth |
| **Mobile user, wants push notifications** | [Scenario C](./docs/START_HERE.md#-scénario-c--je-veux-des-notifs-sur-mon-mobile) — adds ntfy in 5 min |
| **Self-hosting fanatic, full setup** | [Scenario D](./docs/START_HERE.md#-scénario-d--je-veux-y-accéder-depuis-nimporte-où) — full domain + Cloudflare Tunnel + all channels |

---

## Where ELY runs (April 2026)

ELY is **infra-agnostic by design** — same codebase, three deployment profiles:

| Profile | Hardware | LLM stack | Purpose |
|---------|---------|-----------|---------|
| **Personal / dev / production** | Mac Studio (M-series) | LM Studio (xLAM-2 8B, Gemma 4 E4B, Gemma REAP 21B) + cloud APIs as fallback | Daily driver — full feature set, 100% local inference, max privacy |
| **Public demo** *(coming)* | VPS — `https://agent-ely.fr` | Qwen API only (managed, low-latency for shared use) | Showcase for newcomers — try the UI without installing |
| **Self-hosted by you** | Anything that runs Docker (laptop, NAS, VPS) | Bring your own keys / Ollama | Full control, your hardware, your rules |

> 🌍 **Roadmap — agent-ely.fr (Q2 2026)** — landing page + hosted chat UI plugged on Qwen API, so anyone can try ELY in one click without setting up Docker. The on-prem version (this repo) remains the only way to get the full agent with your own data, your own LLM, and zero cloud round-trip.
>
> 🇪🇺 **Why this matters** — ELY combines GDPR-compliant architecture (PII never leaves your hardware) with a product-grade UI on every surface (web, mobile native, PWA, voice) and unique capabilities most agents lack: HITL approval gate, persistent goal-driven missions, blind LLM Arena with ELO ranking, multi-channel messaging, encrypted vault, on-device dedup.

---

## What's new — May 2, 2026

Final polish before the public push. UI refresh, agentic robustness, and a new LLM provider :

- **🎨 UI refonte (Claude.ai handoff)** — full design pass on every page : oklch color tokens, Inter + JetBrains Mono fonts, layered surfaces, full-width layouts, cyan accent (`#13bbc2`) unified across all CTAs. Sidebar, topbar, settings tabs, chat dock and avatar panel all revamped. Dark + light themes both supported.
- **🌙 Moonshot — Kimi K2.x provider** — Kimi K1.5 / K2 / K2.6 (long-context agentic models from Moonshot AI) selectable in Settings → Modèles IA. International endpoint by default (`api.moonshot.ai/v1`), `.cn` region overridable via `MOONSHOT_BASE_URL`.
- **⚡ Mode mono-agent** — admin toggle in Settings → Routage. When on, every query bypasses the LLM router and goes straight to the `general` specialist with all 148 tools bound. Best for benchmarking long-context agentic models (Kimi K2.6, Claude Sonnet 4.6, GPT-5) without classification errors. ~25s for an 8-tool brief on Kimi K2.6.
- **🛣️ Multi-domain routing fix** — queries that touch 2+ domains (e.g. *"search web → put in Google Doc → send WhatsApp"*) now route to `general` instead of grabbing the first matching specialist. Specialists also got an anti-hallucination guard : *"if you need a tool from another domain, redirect — don't claim the tool doesn't exist"*.
- **📅 RDV / abbreviations support** — French abbreviation `RDV` (and variants `rdvs`) added to the workspace router. *"Mes RDV cette semaine"* now properly invokes `calendar_list_events`.
- **🏆 Arena reflects your real LLMs** — the head-to-head ELO board now picks 2 candidates from your configured `llm_instances` table (Kimi K2, Haiku 4.5, Gemini 3.1, Qwen 3.6, LM Studio locals…) instead of a hardcoded list. Local providers (Ollama, LM Studio) are pinged before being added — no more `[Erreur du modèle : All connection attempts failed]` matches.
- **📈 Dashboard daily chart** — backfilled with empty days so today's bar shows even when the user hasn't yet generated traffic. Fixes the *"chart stuck on the 28th"* perception.
- **🤖 Specialists honor tier config** — workspace / research / infra specialists now use `get_llm_for_tier(MEDIUM)` instead of the global active LLM, so the priority list defined in Settings → Routage is respected everywhere (not just in the `general` handler).
- **📂 Channels endpoint** — `/api/channels/active` returns OFF / ON / LINK state for each channel (web / telegram / discord / slack / whatsapp / android / ntfy), feeding the avatar panel's *Canaux Actifs* widget.
- **📝 Anti-hallucination guards** — workspace prompt now reminds the LLM that Gmail's `after:` operator silently ignores hours (use Unix timestamps). General prompt enforces *"never leave a section empty in a structured doc — write 'Rien à signaler' instead"*.

---

## What's new — April 26, 2026

This release was the final pre-public push before the GitHub repo opens and `agent-ely.fr` goes live. Highlights :

- **🌍 Bilingual UI (FR ↔ EN)** — every page switchable from a header button. The agent **switches reply language too** (sandwich language directive injected in every sub-agent prompt). 616 i18n keys, perfect FR/EN parity.
- **🤖 OpenAI provider** — GPT-4o, GPT-4o-mini, GPT-5, o1, o3 (and Azure OpenAI / private proxy via `OPENAI_BASE_URL`). Pickable in Settings → Modèles IA.
- **📧 Multi-Google accounts** — link several mailboxes (perso, perso2, work) to one ELY user. Tools accept an `account` arg, the agent picks the right one based on your phrasing ("send a mail from my pro to …"). Backward compat strict — existing single-account setups keep working untouched.
- **🔍 Self-introspection (Phase A)** — Éli reads her own logs / missions / scheduled tasks / channels / LLM providers / health. *"Why didn't my email arrive?"* now triggers a real diagnostic instead of a guess.
- **🛡️ Public-demo hardening** — `DEMO_MODE=true` flag enables stricter tenant isolation : non-admin users on the shared `agent-ely.fr` instance can't see cross-tenant logs or global linked-user counts. Qdrant queries refuse empty `user_id` by construction (no silent leaks).
- **📊 Dashboard analytics fix** — *"Usage by LLM"* now shows real provider/model names (`lm_studio / llama-xlam-2-8b-fc-r-mlx`, `qwen_api / qwen3.6-plus`) instead of `unknown / tier-medium`.
- **🤝 Repo prep for public** — license headers updated to `contact@agent-ely.fr`, security audit pass, CONTRIBUTING / SECURITY / CODE_OF_CONDUCT in place.

---

## 🎨 The graphical UI — what nobody else gives you

Most open-source AI agents are **terminal-first** : Hermes, OpenClaw, Aider, Claude Code, Codex CLI, even most ChatGPT clones. They're built by developers, for developers. You install them, you `cd`, you type — no avatar, no mobile app, no PWA, no visual missions, no theming, no installer.

**ELY is the opposite.** From day one the bet was : *if your grandmother can't use it, it's not finished*. That means a real product surface :

| Surface | What you get |
|---|---|
| **Web app (Next.js 16 + Tailwind 4)** | Chat with streaming markdown, missions board with live status, knowledge ingestion via drag-drop, blind LLM Arena with ELO ladder, security console, dashboard with token analytics — every page polished, dark + light theme, oklch tokens, Inter typography, fully responsive |
| **3D cyberpunk avatar** | Real-time wireframe head with idle/talking/listening states, framed by a HUD showing latency / tokens / current model / active channels (Telegram / Discord / WhatsApp…) |
| **Voice mode with wake-word "Éli"** | Always-on overlay, Web Speech API or Whisper fallback, voice-optimised system prompt (no markdown, shorter sentences) |
| **Native iOS app (SwiftUI 17+)** | 22 files, real chat UI, push notifications, biometric unlock |
| **Native Android app (Kotlin + Jetpack Compose)** | Material You, foreground service for HITL push, FCM |
| **PWA install** | Manifest + service worker + offline page + 30-second deferred install prompt — works on iPhone home screen and Android |
| **HITL via UI in every channel** | Telegram inline keyboard with Allow / Deny / Ban buttons, Slack Block Kit, Discord emoji reactions — never a raw text "do you confirm ?" prompt |
| **i18n FR ↔ EN** | One-click toggle, the agent itself switches reply language too (sandwich directive injected per turn) |
| **Bilingual setup wizard** | Conversational onboarding at first login — Éli asks 5 questions to learn your vocabulary (your Gmail labels, your shortcuts, your morning briefing time) |

This matters because the product is now in a place where someone non-technical can use it daily. Compare with the competition :

| Surface | ELY | Hermes | OpenClaw / Aider | ChatGPT app | Claude.ai |
|---|---|---|---|---|---|
| Rich graphical web UI | ✅ Next.js native | ⚠️ Vite dashboard around xterm.js | ❌ Terminal | ✅ Web | ✅ Web |
| Native mobile apps (iOS + Android) | ✅ Both | ❌ Telegram only | ❌ | ✅ Both | ✅ Both |
| 3D avatar / visual identity | ✅ | ❌ | ❌ | ❌ | ❌ |
| Voice wake-word | ✅ "Éli" | ⚠️ Voice mode, no wake-word | ❌ | ✅ "Hey ChatGPT" | ❌ |
| PWA installable | ✅ | ❌ | ❌ | ❌ | ❌ |
| Self-hosted (your data, your hardware) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Visual mission planner (Plan→Act→Eval→Replan) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Blind LLM Arena (ELO K=32) | ✅ | ❌ | ❌ | ❌ | ❌ |
| French native (UI + agent reply) | ✅ | ❌ EN only | ❌ | ⚠️ partial | ⚠️ partial |

→ **ELY is the only self-hosted agent that ships with a product-grade UI on every surface**. The terminal crowd has Hermes (deeply technical, very mature). The cloud crowd has ChatGPT. ELY is the bridge : self-hosted privacy + grand-public ergonomics.

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

### 🎯 Missions — Goal-Driven Persistence Loop

ELY is also a **goal-driven autonomous agent**. Give her a goal — she breaks it into steps, picks tools, executes them, evaluates the result, replans if she fails, and notifies you when the mission is complete. All of this survives backend restarts (LangGraph checkpointer in SQLite).

```
                    ┌─── HEARTBEAT (every 10s) ───┐
                    ▼                              │
            ┌────────────┐    ┌──────┐    ┌─────┐ │
            │   Plan     │───►│ Act  │───►│Eval │─┤
            └────────────┘    └──────┘    └──┬──┘ │
                  ▲                          ▼    │
                  │       ┌────────┐    ┌─────────┴───┐
                  └───────│ Replan │◄───│ ≥3 failures │
                          └────────┘    └─────────────┘
```

**How to launch a mission**:

| From | How |
|------|-----|
| Web UI | `/missions` → button "Nouvelle mission" → fill title + goal + budgets |
| Telegram | `/mission <title> :: <goal>` (DM the bot) |
| (Coming) | Schedule a recurring mission via `/scheduler` |

**5 hard guardrails** (mandatory, no opt-out):
- Token budget (per mission, default 50k, configurable)
- Iteration budget (default 30 ticks, configurable)
- Optional deadline (kill at timestamp)
- HITL on critical tools (mail send, file delete, SSH, etc.)
- Anti-loop : 3 consecutive failures → automatic replan with reflection

**Notifications when done**: 3 channels in parallel:
- Web UI (auto-created `[Missions] Notifications` conversation in your sidebar)
- Telegram DM (if mission was created via Telegram)
- ntfy push to your phone (if `NTFY_URL` configured)

Routing: missions use the local **xLAM-2 8B** model for tool-calling (specialised for function calls, ~5s per action), with auto pre-filtering of the tool inventory (151 → 15 most relevant) so smaller models don't choke on payload size.

---

### 🔍 Self-Introspection — ELY answers questions about herself

ELY can read her own runtime state. Ask her things like *"Pourquoi mon mail planifié de ce matin n'est pas arrivé ?"*, *"Quel modèle tu utilises ?"*, *"Tous les canaux fonctionnent-ils ?"*, *"Comment tu te portes ?"* and she will actually look at logs / scheduled tasks / mission history / channel status / LLM provider config and answer factually — instead of guessing or hallucinating.

**6 read-only diagnostic tools** (Phase A — no self-modification, that comes later behind HITL):

| Tool | What it inspects |
|------|------------------|
| `system_get_logs` | Last N lines of the in-memory ring buffer (5000 entries, secrets auto-masked) |
| `system_list_scheduled_tasks` | All scheduled tasks for the calling user — next run, last run, channel, status |
| `system_list_missions` | All missions for the calling user — state, ticks consumed, last error |
| `system_check_channels` | Telegram / Discord / Slack / WhatsApp / ntfy — which are configured + connected |
| `system_check_llm_providers` | Configured providers, current tier mapping, default model per tier |
| `system_get_health` | Backend uptime, RAM, DB size, Qdrant collections, scheduler running, log buffer stats |

**Security model**: pure read-only, no shell, no DB writes, no secret disclosure. The log capture handler (`app/services/log_buffer.py`) sanitises 13 secret patterns *before* storing — Bearer tokens, API keys, JWTs, refresh tokens, SMTP passwords, Slack signing secrets, etc. — so even if the LLM ends up paraphrasing a log line in chat, no key leaks.

Self-modification (restart bot, change tier, edit config) is reserved for **Phase B** with mandatory HITL gating.

#### 🔧 Self-Healing in practice — a real case study

This isn't a feature on a slide deck. **It's how the project gets debugged.**

While building the FR/EN i18n flow (April 2026), a bug appeared : Éli answered in French even when the user had switched the UI to English. Six layers of fixes later, she was still doing it. Conventional debugging meant SSH-ing into the server, tailing logs, grepping for stack traces — minutes per cycle.

Instead, the developer typed in chat :

> **User**: *"Show me the last 5 logs containing LANG_FETCH"*
>
> **Éli**: *"There are 4 entries containing LANG_FETCH in the recent logs. They show a repeated exception : **`name 'async_session' is not defined`** in the language detection module, with automatic fallback to French. This error occurred three times between 18:25:30 and 18:25:45 UTC."*

The bug was a **silent `NameError`** — a missing import inside a try/except that swallowed the exception and returned the default. The next commit fixed it in 30 seconds. **Éli debugged her own bilingual layer in plain language, in three messages.**

This is what *"Exactly Like You"* means — not just an assistant that does what you ask, but an agent that **diagnoses itself when you don't know what to ask**. Most self-hosted agents treat the LLM as a chatbox over a closed runtime. ELY treats the runtime as **legible to the LLM**, with safe boundaries (read-only, secrets sanitised, per-user scoped).

Phase B will let the agent *act* on what she diagnoses — restart a stalled scheduler job, retry a failed mission with reflection, propose a config change for HITL approval. Phase A is the foundation : an agent that **knows herself**.

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
- **Cloud API** — **OpenAI** (GPT-4o, GPT-5, o1, o3, Azure OpenAI proxy ready) · Qwen API (Alibaba DashScope) · OpenRouter (200+ models) · Anthropic Claude · Google Gemini · DeepSeek · Mistral AI · Zhipu GLM
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

All four chat channels below are configured from **Settings → Channels** in the UI — no `.env` editing required. Each card validates the token with the provider, persists it encrypted, and hot-restarts the bot.

| Channel | Setup | Notes |
|---------|-------|-------|
| **WhatsApp** | Settings → Channels → Lier mon WhatsApp (QR scan) | Uses your **personal** WhatsApp account via the unofficial Web protocol (no Meta Business needed). ELY only replies in your **self-chat** — other conversations are never intercepted. |
| **Telegram** | Settings → Channels → paste @BotFather token | Inline keyboard buttons for HITL (Allow / Deny / Ban); `/link <user> <pwd>` in DM to pair. Polling mode by default (~10s latency); webhook mode requires exposing `/webhook/*` via your reverse proxy / tunnel. |
| **Discord** | Settings → Channels → paste Developer Portal token | Needs **Message Content Intent** enabled. DM or `@Éli` mention in any channel; emoji-based HITL reactions (✅ allow · ❌ deny · 🛡️ ban). |
| **Slack** | Settings → Channels → paste Bot + App tokens | Socket Mode — **no public URL needed**; Block Kit interactive buttons for HITL; works in channels and DMs with `@Éli`. |

#### 🔔 Push Notifications

| Channel | Setup | Notes |
|---------|-------|-------|
| **Android (FCM)** | Install the Android app — the FCM token is registered automatically on login | Delivers HITL approval requests as rich push notifications with **Allow / Deny / Ban** action buttons, even when the app is closed |
| **iOS (APNs)** | Install the iOS app — the push token is registered automatically on login | Same UX as Android, via Apple Push Notification service |

---

#### WhatsApp — Personal Account via QR Pairing (default)

No Meta Developer account needed — ELY bridges the **WhatsApp Web protocol** the same way the WhatsApp Desktop app does.

1. Open ELY → **Settings → Channels → WhatsApp** → **Lier mon WhatsApp**
2. A large QR code appears. On your phone: WhatsApp → Settings → **Linked devices** → **Link a device** → scan.
3. Once paired, chat with Éli by sending messages to **yourself** (the self-chat).

**Privacy design:** ELY reads and replies only in your self-chat conversation. All your other WhatsApp chats (friends, family, work groups) remain untouched. Session keys are stored locally on the server — delete via the *Disconnect* button anytime.

> **Alternative:** *"Le QR échoue ?"* offers a phone-number code pairing (8 digits) for cases where iPhone camera decoding is unreliable.
>
> **Meta Cloud API (business accounts)** is still supported for users who need the official API — set `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_VERIFY_TOKEN` in `.env`, `send_whatsapp_message` falls back to Meta when no QR session is available.

---

#### Telegram — Quick Start

1. Telegram → search **@BotFather** (blue checkmark) → `/newbot` → copy token.
2. ELY → **Settings → Channels → Telegram** → paste → **Activer**.
3. In Telegram, open your bot, click **Start**, then send `/link <ELY_username> <ELY_password>` (your web-UI credentials).

Polling mode is used by default — if your backend is reachable over HTTPS without path restrictions, the bot automatically switches to webhook mode (instant delivery). Set `TELEGRAM_USE_POLLING=1` in `.env` to force polling (useful when `/webhook/*` isn't exposed by your reverse proxy).

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

**Prerequisites:** Docker, Git, [LM Studio](https://lmstudio.ai/) *(recommended on Apple Silicon — MLX models)* or [Ollama](https://ollama.com)

> 🍎 **Mac Studio is the reference dev/prod target** — Apple Silicon + LM Studio MLX gives the best local inference on consumer hardware (xLAM-2 8B 8-bit for tool calls, Gemma 4 E4B 4-bit for chat, Gemma REAP 21B for complex reasoning). Linux/Windows + Ollama works too but is less battle-tested as of April 2026.

> 🌐 **UI language** — bilingual FR ↔ EN out of the box, switchable from the header. The agent itself replies in the language you write to her in.

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
- **LM Studio (free, local, recommended on Apple Silicon):** open LM Studio → Local Server → load any MLX model → just type the model name in Settings.
- **Cloud providers:** Anthropic Claude, Google Gemini, OpenAI, Mistral, DeepSeek, OpenRouter, Zhipu GLM, Qwen API (Alibaba Cloud), **Moonshot Kimi K2.x** — enter your API key in Settings, no restart needed.

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

## ⚖️ License & Trademark

### Source code
**PolyForm Strict License 1.0.0** — see [LICENSE](./LICENSE).

✅ **Allowed:** personal use, learning, non-commercial research, evaluation up to 30 days.

❌ **Not allowed without written agreement:**
- Commercial use or integration into a paid service
- Redistribution of modified versions
- Training other AI models on this codebase

→ **For commercial licensing**: see **[COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md)** (transparent pricing : Solo €29/mo, Team €99/mo, Business €399/mo, Enterprise on quote — most requests get a yes within a week).

### Names & branding
The names **ELY**, **Éli**, **agent-ely.fr**, the **3D cyberpunk avatar** and the **lightning-bolt logo** are **trademarks owned by Franck OLLIVIER** — protected separately from the code.

→ See **[TRADEMARK.md](./TRADEMARK.md)** for what you can and can't do with the marks. **TL;DR:** fork freely, build derivatives — but pick your own name and your own logo.

📧 **Contact**: [contact@agent-ely.fr](mailto:contact@agent-ely.fr) — replies within 48h, always.
