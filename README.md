<!-- Français : README.fr.md -->

# Ely

**Exactly Like You** — a self-hosted personal agent. Your data stays local, the
power comes from the cloud, and nothing irreversible happens without your
approval.

Ely is a **non-commercial personal project**, published under the **MIT**
licence. Do what you like with it; just keep the copyright notice.

---

## Local, cloud, and the line between them

Ely runs on your machine and picks a model per request. A request takes one
of three routes.

**On your machine.** A small local model (LM Studio or Ollama) carries the
background work: reading the tool directory, extracting the facts worth
remembering from a turn, summarising, choosing which tool families a mission
gets, testing a candidate skill. Enable the local lane (`SLM_ENABLED`, off by
default) and it also answers the simple requests of the chat, with its tools:
the weather, your agenda, a translation, a search. None of that traffic leaves
the machine, and none of it is billed.

**Masked, then sent.** What needs real reasoning — code, a 400-page document,
a mission that runs for hours — goes to the cloud model you configured. Ely
speaks to a dozen providers (Gemini, Claude, Mistral, DeepSeek, OpenAI and the
ChatGPT subscription, OpenRouter, Moonshot, Qwen, Zhipu); the split is set tier
by tier by the admin, never per user. Before a call leaves the machine,
personal data — addresses, IBANs, company numbers, phone numbers, API keys — is
replaced by stable placeholders, the same address becoming the same marker
throughout a conversation, and the answer is restored on the way back. The
boundary is the **network**, not the prompt: a local model gets your data in
clear, because masking it would protect nothing and would cost accuracy. If
masking fails, the turn stops rather than sending anything in clear.

**On hold.** Sending a message, deleting a file, running a remote command: Ely
stops and waits for your approval, showing the exact call before it goes out.
No answer, and the action expires instead of happening.

Two limits worth stating. The local lane is opt-in, and it needs a machine
that can serve a model (32 GB of RAM in practice). Missions and scheduled
tasks always take the cloud tier: a small model does not hold an unattended,
multi-tool job.

---

## The idea

Most assistants either answer questions or run wild. Ely draws the line
somewhere more useful — not between *talking* and *doing*, but between three
kinds of decision:

| | Who decides | Who acts | Control |
|---|---|---|---|
| **Mechanical** — one correct answer | nobody | Ely | internal check |
| **Judgement** — several defensible answers | **the model** | Ely | conformity loop |
| **Committing** — irreversible, or visible to a third party | model proposes | Ely **after approval** | human in the loop |

The test: *would two competent people, given the same information, answer
differently?* No → mechanical. Yes → judgement.

A language model cannot act on the world; it only emits text. So Ely always
does the acting — that is physics, not architecture. What she must not do is
**settle a judgement on your behalf** using thresholds hard-coded in advance.

"Archive mail older than six months" is mechanical: the rule is in the sentence.
"Tidy up my inbox" is a judgement, and needs your say.

---

## What runs

One agent. No supervisor, no specialists — that architecture existed and was
removed after an A/B bench gave the single agent the edge on all four criteria
measured, latency and tool choice included.

```
entry ──▶ agent ──▶ tools ──▶ back to agent
             │
             ├──▶ verify ──▶ conforming? end : back to agent with the named gap
             └──▶ force_summary ──▶ end   (iteration budget spent)
```

The loop **fails open** — without a clear signal of non-conformance it returns
the answer rather than spinning — and **progress bounds it, not a counter**: a
retry only continues while the gaps are shrinking.

Which model answers is decided by a **pure function**, not by a model: a request
is either an image or an ordinary one, and the tier follows. That routing used
to be a model call, and it was removed — measured, it downgraded requests and
unplugged the tools it judged unnecessary.

The choice of the local model is not cosmetic: on the same tool-directory
task, two of them scored 4/4 — one in 1.1 s, the other in 8.9 s.

---

## What it can do

**199 tools** built in, with default feature flags. Enabling the MCP client
(`mcp_client_v2_enabled`, off by default) adds **10** MCP management tools, and
every MCP server you connect contributes its own on top, as
`mcp__server__tool`.

The larger families:

- **Google** — Gmail, Calendar, Drive, Sheets, Docs, Contacts, Tasks
- **Documents** — read PDFs, vision analysis, and PDF → Word rebuilt from page
  geometry (the text never passes through the model, so integrity is structural)
- **Web** — search, images, maps (see below)
- **Browser** — three families, deliberately: **one-shot** tools that take a URL
  and return a result (screenshot, PDF, text, diff) without any open session —
  what scheduled tasks need; a **session** on a server-side headless Chromium
  with **no cookies**, for exploring a site step by step; and your **real
  Chrome** through the extension, the only way to reach anything behind a login
- **Machine** — files, screenshots, desktop control, SSH
- **Memory** — typed recall, vector search, full-text search over past
  conversations
- **Scheduling** — recurring tasks
- **Channels** — Telegram, on the same runtime as the web chat
- **MCP** — Ely is both a client of external MCP servers and an MCP server
  herself

---

## Search, without renting it

A **SearXNG** instance ships in the compose file and heads the chain. It is a
metasearch engine: it queries dozens of engines in parallel and merges what they
return, instead of taking the first ten links from a single source. No key, no
account, no quota, and no third party linking your queries to you under your own
API key.

Ely can aim it at a family of sources — `it`, `news`, `images`, `videos`,
`science`, `social_media`, `files`, `shopping`. The requested family is **added**
to the generalists, never substituted: "the news about AI" queries Reuters *and*
the open web, or you would be reading a single source.

Behind it, key-based providers remain as a **net**, tried only when the one above
returns nothing: Exa (semantic), SearchCans, Google CSE, Tavily, DuckDuckGo. A
provider out of quota is dropped for thirty minutes rather than retried each
turn.

⚠️ SearXNG has no index of its own — it queries upstream engines from your
machine's IP, so the risk of being rate-limited moves to you. Breadth is what
absorbs it: with three engines blocked during testing, twenty-six results still
came through.

At boot, in the background, Ely places a **real** call on each head of the chain
— every model tier and every search provider — and reports what actually
answered. The previous check only verified a service could be *built*; two
outages in a single day walked through that gap.

---

## Quick start

**You need:** Docker, Docker Compose, 16 GB RAM (32 GB for local models), 20 GB
disk, `make`, `openssl`.

```bash
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent
cp .env.example .env

# 1. Signing secret — the app refuses to start without a real one
openssl rand -hex 32          # paste into JWT_SECRET_KEY= in .env

# 2. One model provider (required — otherwise Ely cannot answer)
#    e.g. ACTIVE_LLM_PROVIDER=gemini + GEMINI_API_KEY=…
#    Local paths also work: Ollama, LM Studio
#    Optional: SLM_ENABLED=true gives the simple requests to a local model

# 3. Boot (first run pulls several GB, 5-10 min)
make up
make logs                     # wait for the backend to report healthy

# 4. Open http://localhost:3000 — the first account created becomes admin
```

⚠️ **`.env` lives at the repository root.** The container reads that one, not
`backend/.env`. This is the single most common configuration mistake here.

Full walkthrough: **[docs/installation.md](docs/installation.md)** (French).

---

## Approval, and where it actually lives

**44 tools** require your approval by name. On top of that, the **content** of a
request can trigger a check — a transfer, a purchase, a deletion, a checkout
page.

Three rules worth knowing:

1. **It fails closed.** An unclassified tool is treated as committing. A false
   positive costs a question; a false negative costs a sent message.
2. **A waiver is not a reclassification.** Some committing actions are exempted
   with a written reason — a click in Chrome is not a commitment, filling a form
   field is not submitting it. The tool stays classified as committing: what a
   tool *is* stays separate from what needs your consent.
3. **A docstring is not a guardrail.** "Always ask for confirmation" in a tool's
   documentation is an instruction to the model, not a lock. Those sentences were
   removed; the guard alone decides.

---

## Your data

The masking described above is a regex layer, applied at the network boundary
and only there: a local model is served in clear. Which route a request takes
is decided before the call, and the trace of a turn says which model answered.

Ely reports what a request cost when it used a per-call model.

---

## How it learns

A skill is born from a **success reached after correction**: Ely failed, saw it,
named the gap, fixed it, and the result passed verification. The procedure is
then written up and offered as a **candidate**. Nothing becomes active without
review.

A tool is only built when a request demands an **action** — touching a file, an
API, a service. Otherwise it becomes a skill: a written procedure, not new code.

---

## Stack

FastAPI · LangGraph · Next.js · SQLite (Alembic is the sole schema authority) ·
Qdrant · nginx · Squid for egress filtering · Docker Compose.

Surfaces: web, REST API, Telegram, voice over WebSocket, a Chrome extension
and a desktop app. The Android and iOS apps, along with the WhatsApp, Slack
and Discord bridges, were archived on 2026-09-02 — see
[archive/README.md](archive/README.md).

---

## Documentation

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | how it works inside (French) |
| [docs/installation.md](docs/installation.md) | install and configure (French) |
| [docs/guide-utilisateur.md](docs/guide-utilisateur.md) | day-to-day use (French) |
| `.env.example` | every setting, annotated |

---

## Licence

**MIT** — see [LICENSE](LICENSE). Use it, modify it, redistribute it, sell it,
run it as a service. The only condition is that the copyright notice and the
licence text travel with the code.

Ely moved from Elastic License 2.0 to MIT on 3 September 2026. It is a personal
project, not a product; a permissive licence removes every reason to hesitate
before forking it.

Trademark: [TRADEMARK.md](TRADEMARK.md). Security policy:
[SECURITY.md](SECURITY.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Ely is a personal project, so the pace is what it is. Bug reports and precise,
reproducible findings are the most useful thing you can send.
