<!-- Français : README.fr.md -->

# Ely

**Exactly Like You** — a self-hosted personal agent that does things, checks its
own work, and asks before it commits you to anything.

Ely is a **non-commercial personal project**, published under the Elastic
License 2.0. Free for personal use and for internal professional use; reselling
it as a hosted service is not permitted.

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

---

## What it can do

**196 built-in tools**, plus whatever the MCP servers you connect bring in.
The larger families:

- **Google** — Gmail, Calendar, Drive, Sheets, Docs, Contacts, Tasks
- **Documents** — read PDFs, vision analysis, and PDF → Word rebuilt from page
  geometry (the text never passes through the model, so integrity is structural)
- **Web** — search, images, maps
- **Browser** — two families, deliberately: a server-side headless Chromium with
  **no cookies**, and your **real Chrome** through the extension, which is the
  only way to reach anything behind a login
- **Machine** — files, screenshots, desktop control, SSH
- **Memory** — typed recall, vector search, full-text search over past
  conversations
- **Scheduling** — recurring tasks
- **Channels** — Telegram, Slack, Discord, WhatsApp, all on the same runtime as
  the web chat
- **MCP** — Ely is both a client of external MCP servers and an MCP server
  herself

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

**46 tools** require your approval by name. On top of that, the **content** of a
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

Before any call to a **third-party hosted** model, personal data is replaced by
stable placeholders — the same address becomes the same marker throughout a
conversation — and the answer is restored on the way back. A call to a **local**
model skips this entirely: nothing leaves the machine.

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

Surfaces: web, REST API, Telegram, Slack, Discord, WhatsApp, voice over
WebSocket, a Chrome extension, a desktop app, Android and iOS.

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

**Elastic License 2.0** — see [LICENSE](LICENSE), with a plain-language summary
in [licence-ELY.md](licence-ELY.md) and commercial terms in
[COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).

- **Allowed** — personal use, and internal professional use, free of charge.
- **Not allowed** — reselling Ely as a hosted or managed service to third
  parties, or stripping copyright and licence notices.

Trademark: [TRADEMARK.md](TRADEMARK.md). Security policy:
[SECURITY.md](SECURITY.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Ely is a personal project, so the pace is what it is. Bug reports and precise,
reproducible findings are the most useful thing you can send.
