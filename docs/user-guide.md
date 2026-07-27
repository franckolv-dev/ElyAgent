# ELY Agent — User Guide

> **ELY** is your personal AI assistant: it connects to your Google Workspace, browses the web, manages your schedule, runs commands on your servers — all while keeping your data private and requiring your explicit approval before any irreversible action.

---

## Table of Contents

1. [First Launch and Login](#1-first-launch-and-login)
2. [Interface Overview](#2-interface-overview)
3. [How to Chat with ELY](#3-how-to-chat-with-ely)
4. [Google Integration Setup](#4-google-integration-setup)
5. [Skills Management](#5-skills-management)
6. [Scheduled Tasks](#6-scheduled-tasks)
7. [Conversational Channels (WhatsApp / Telegram / Discord / Slack)](#7-conversational-channels-whatsapp--telegram--discord--slack)
8. [Missions — Goal-Driven Persistence Loop](#8-missions--goal-driven-persistence-loop)
9. [HITL Validation](#9-hitl-validation)
10. [Memory — What ELY Remembers](#10-memory--what-ely-remembers)
11. [Security Overview](#11-security-overview)
12. [MCP Server & Personal API Keys](#12-mcp-server--personal-api-keys)

---

## 1. First Launch and Login

When you open ELY for the first time at `http://localhost:3000`, you will see the login screen.

<!-- TODO(screenshots): add docs/screenshots/login.png to illustrate the login UI -->

### Creating your account

On the login page, click the **"Créer un compte"** (Register) tab and fill in:
- A username
- An email address
- A password (minimum 12 characters, including at least one uppercase letter and one special character)

The **first account created is automatically assigned the Admin role**. Subsequent accounts are regular users.

### Logging in

Enter your credentials and click **"Se connecter"**. You will be redirected to the main chat interface.

> **Session duration**: access tokens expire after 15 minutes. ELY silently refreshes them in the background — you will not be logged out mid-conversation.

---

## 2. Interface Overview

<!-- TODO(screenshots): add docs/screenshots/chat-light.png showing chat + 3D avatar -->

The ELY interface has four main zones:

### Left sidebar

The navigation sidebar contains:
- **Chat** — main conversation area (currently selected by default)
- **Dashboard** — usage statistics and activity overview (coming soon)
- **Settings** — personal preferences, LLM provider selection, Google integration, skills
- **Admin** — user management and audit logs (admin accounts only)

At the bottom of the sidebar you will find the currently logged-in user's name and a logout button.

### Main chat area (centre)

This is where your conversation with ELY takes place. Messages appear in a chronological feed:
- Your messages appear right-aligned with a distinct background
- ELY's responses appear left-aligned
- Tool calls (actions ELY performed) are shown as collapsible blocks so you can inspect what happened
- HITL validation prompts (approval requests) appear inline as interactive cards

At the bottom of the chat area sits the **message input bar** with:
- A text field for typing your message
- A send button (or press Enter)
- A microphone button for voice input (wake-word « Éli », transcription via Whisper)
- A TTS toggle to enable/disable voice playback of ELY's responses

### Right panel — 3D Avatar

The right panel displays ELY's holographic 3D avatar head. This visual indicator reflects the agent's current state:

| Avatar state | Meaning |
|---|---|
| Idle (slow pulse) | ELY is ready and waiting |
| Thinking (rotating glow) | ELY is processing your request |
| Speaking (animated) | ELY is generating or reading a response |
| Alert (red flash) | An action is paused, awaiting your approval |

Below the avatar you will find:
- **Status indicator** — shows connection state (WebSocket connected / reconnecting)
- **Voice toggle** — enables Text-to-Speech playback

### Top-right controls

- **Theme toggle** (sun/moon icon) — switches between dark and light mode. Your preference is saved.
- **User menu** — access settings and logout

---

## 3. How to Chat with ELY

ELY understands natural language in French and English. You do not need to learn any commands — just write as you would to a person.

### Attachments / file upload

You can attach a file directly in the chat (up to **50 MB** per file; a per-user storage quota applies and uploads are purged after 90 days). ELY reads the file via its PDF/vision tools — the upload returns a server path, the file content itself is never pasted into the prompt.

> **`.zip` gotcha**: a `.zip` will upload, but ELY has **no unzip tool**, so it cannot read the archive's contents. Send files **unzipped**.

### Email (Gmail)

```
Lis mes 5 derniers emails
```
```
Envoie un email à alice@exemple.com avec comme sujet "Réunion vendredi" et dis-lui que la réunion est confirmée à 14h
```
```
Y a-t-il des emails urgents depuis hier ?
```

### Calendar (Google Calendar)

```
Quels sont mes rendez-vous cette semaine ?
```
```
Crée un rendez-vous "Dentiste" vendredi 28 mars à 10h30, durée 1 heure
```
```
Annule mon rendez-vous avec l'équipe marketing de demain
```

### Drive & Documents

```
Liste mes fichiers Google Drive récents
```
```
Lis le document "Rapport Q1 2026"
```
```
Crée un nouveau document Word avec le titre "Budget 2026" et ajoute un tableau avec les colonnes Poste, Prévu, Réel
```
```
Crée une feuille de calcul pour suivre mes dépenses mensuelles
```
```
Prends une capture du site exemple.com et enregistre-la sur mon Drive
```

> ELY can also save a local file/binary (a screenshot, a PNG, a PDF) to Drive via `drive_upload_local_file` — handy because `drive_create_file` only handles text.

### Tasks (Google Tasks)

```
Montre ma liste de tâches
```
```
Ajoute "Appeler le médecin" à mes tâches pour demain
```
```
Marque la tâche "Rapport mensuel" comme terminée
```

### Weather

```
Quel temps fait-il à Paris aujourd'hui ?
```
```
Météo à Lyon pour les 3 prochains jours
```

### News

```
Les dernières actualités en France
```
```
Actualités sur l'intelligence artificielle
```
```
Quoi de neuf en tech cette semaine ?
```

### Translation

```
Traduis "hello world" en français
```
```
Traduire ce texte en espagnol : "Bonjour, comment allez-vous ?"
```
```
Comment dit-on "merci beaucoup" en japonais ?
```

### Web browsing

```
Cherche le prix d'un vol Paris–New York pour juillet
```
```
Va sur lemonde.fr et lis la une
```
```
Prends une capture d'écran du site documentation.anthropic.com
```
```
Recherche les meilleurs restaurants japonais à Lyon
```

### SSH (requires HITL approval)

```
Lance "df -h" sur mon serveur de prod
```
```
docker ps sur my-server
```
```
systemctl status nginx sur prod
```

> SSH commands always require your explicit approval before execution. See [HITL Validation](#9-hitl-validation).

### Scheduled tasks

```
Rappelle-moi tous les lundis à 8h de vérifier mes emails
```
```
Crée une tâche planifiée qui résume mes emails non lus chaque vendredi soir à 18h
```
```
Envoie-moi la météo de Paris chaque matin à 7h30
```

---

## 4. Google Integration Setup

To allow ELY to access Gmail, Calendar, Drive, Docs, Sheets, and Tasks, you must connect your Google account.

### Step 1 — Open Settings

Click **Settings** in the left sidebar.

<!-- TODO(screenshots): add docs/screenshots/settings-google.png showing Google OAuth connect button -->

### Step 2 — Connect Google

Scroll to the **"Intégrations Google"** section. You will see buttons for each Google service:
- Gmail
- Google Calendar
- Google Drive
- Google Docs
- Google Sheets
- Google Tasks

Click **"Connecter Google"**. A Google OAuth consent screen will open in a new tab. Sign in with the Google account you want to use and grant the requested permissions.

> **Multiple Google accounts**: you can link several Google accounts/mailboxes to a single ELY user and target one per request via an `account` alias (e.g. *"envoie ça depuis mon compte perso"*).

> **Privacy note**: ELY stores your OAuth tokens locally in the database. Tokens are never sent to the LLM. When ELY calls a Google API on your behalf, the token is injected at execution time — the AI model only sees the result (e.g., a list of email subjects), never your credentials.

### Step 3 — Verify connection

After authorisation, the Settings page will show each Google service with a green "Connecté" badge. You can now use all Google-related skills.

### Disconnecting

To revoke access, click **"Déconnecter"** next to any Google service. This deletes the stored token. You can also revoke access directly from your [Google Account security page](https://myaccount.google.com/permissions).

---

## 5. Skills Management

Skills are ELY's capabilities. Each skill is a group of related tools. You can enable or disable skills individually.

### Viewing skills

Go to **Settings** and scroll to the **"Skills actifs"** section.

<!-- TODO(screenshots): add docs/screenshots/settings-skills.png showing the Skills toggle list -->

Each skill card shows:
- The skill's icon and name
- A short description
- A toggle to enable/disable it
- The list of tools it provides

### Available skills

> This is a curated overview, not the full catalog. ELY ships with ~190+ built-in tools (75 of them Google); the bound profile stays lean and the agent pulls any other catalog tool on demand via `find_tool`. Not shown below: image generation, MCP-client consumption of external MCP servers, the `delegate` parallel sub-task tool, and more.

| Skill | Tools provided |
|---|---|
| System | Date/time, basic calculations |
| Gmail | Read, send, search emails |
| Google Calendar | List, create, delete events |
| Google Drive | List, read files |
| Google Docs | Create, read, append documents |
| Google Sheets | Create, read, update spreadsheets |
| Google Tasks | List, create, complete tasks |
| Scheduler | Create and manage scheduled tasks |
| Weather | Current weather and forecasts |
| News | Latest news by topic |
| Translation | Translate text between 50+ languages |
| Web Browser | Navigate, search, screenshot, interact |
| SSH | Execute whitelisted commands on remote servers |
| TTS | Text-to-speech voice synthesis |

### Disabling a skill

Toggle the switch next to a skill to disable it. ELY will stop using its tools and will not mention it in responses. Useful if you want to restrict ELY's capabilities for a given account.

---

## 6. Scheduled Tasks

ELY can execute tasks automatically on a schedule — without you being present.

### Creating a scheduled task via chat

The most natural way is to ask ELY directly:

```
Rappelle-moi tous les lundis matin à 9h de consulter mon agenda de la semaine
```
```
Chaque vendredi à 17h, résume mes emails non lus et envoie-moi le résumé par Telegram
```

ELY will create the scheduled task and confirm with the cron expression it will use.

### Managing scheduled tasks

In **Settings**, scroll to the **"Tâches planifiées"** section to see all your active tasks. For each task you can:
- See the next scheduled execution time
- Enable or disable the task
- Delete the task

### What happens when a task runs

When a scheduled task fires, ELY executes the prompt autonomously and delivers the result to your preferred channel (web UI or Telegram). If the task requires an irreversible action (e.g., sending an email), ELY will pause and send you a HITL approval request — even without you being present in the chat.

---

## 7. Conversational Channels (WhatsApp / Telegram / Discord / Slack)

ELY can be reached from multiple chat apps so you keep talking to Éli even when you're away from the web UI. All channel setup happens from **Settings → Channels** — no terminal, no `.env` edits.

Beyond the four messaging apps detailed below, ELY is also reachable through **voice** (wake-word « Éli », WebSocket `/ws/voice`, Whisper transcription + TTS), **ntfy push notifications**, the installable **PWA**, and the native **Android** (FCM) and **iOS** apps.

> **Memory is shared across channels.** Whatever you tell Éli on WhatsApp, she'll remember on the web UI and vice-versa.

### 7.1. WhatsApp (QR-paired personal account)

Uses the unofficial WhatsApp Web protocol — same thing WhatsApp Desktop does. **No Meta Developer account required.**

1. **Settings → Channels → WhatsApp → Lier mon WhatsApp**
2. A ~420 px QR code appears. On your phone: WhatsApp → Settings → **Linked devices** → **Link a device** → scan.
3. Once paired, the card shows *"lié — +<your number>"*.
4. Open WhatsApp on your phone, go to the **"Message yourself"** chat (search for your own name), and start typing.

**Important:** ELY only reads and replies to messages you send **to yourself** (the self-chat). All your other WhatsApp conversations stay completely untouched — friends, family, work groups never see ELY.

If scanning fails: click *"Le QR échoue ? Essayer avec un numéro de téléphone"*, enter your number (`33612345678` format, no `+`), and WhatsApp will accept the 8-character code instead.

### 7.2. Telegram (BotFather bot)

1. Open Telegram → search **@BotFather** (with blue checkmark).
2. Send `/newbot` → pick a name and a username ending in `_bot`.
3. BotFather replies with a token like `8537074323:AAHxxxxxx...` — copy it.
4. In ELY: **Settings → Channels → Telegram**, paste the token → **Activer**.
5. The UI shows *"actif — @your_bot"*.
6. In Telegram, open a chat with your bot → **Start**.
7. Send `/link <your_ELY_username> <your_ELY_password>` (the credentials you use on the web UI).
8. Done — just send any message normally.

The UI deletes your `/link` message immediately so your password doesn't sit in the chat history. Replies have ~10 s latency in polling mode (default); switch to webhook via the tunnel config for instant delivery.

### 7.3. Discord (Developer Portal bot)

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**.
2. **Bot** tab → **Reset Token** → copy (shown once).
3. In *Privileged Gateway Intents*, enable **MESSAGE CONTENT INTENT** (mandatory). Save.
4. (Optional) **OAuth2 → URL Generator** → scope `bot` + permissions *Send Messages / Read Message History / Add Reactions / Manage Messages*, open the URL, invite the bot to a server you admin.
5. In ELY: **Settings → Channels → Discord**, paste the token → **Activer**.
6. In Discord, DM your bot: `!link <username> <password>`. HITL approvals arrive as emoji reactions.

### 7.4. Slack (Socket Mode app)

Socket Mode avoids the need for a public HTTPS endpoint — Slack opens a WebSocket back to the bot.

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**.
2. **Socket Mode** → enable → generate an **App-Level Token** with scope `connections:write` → copy the `xapp-...` token.
3. **OAuth & Permissions** → Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `reactions:write`.
4. **Install App to Workspace** → copy the **Bot User OAuth Token** `xoxb-...`.
5. **Event Subscriptions** → enable → subscribe to `message.im` and `app_mention`.
6. In ELY: **Settings → Channels → Slack**, paste **both** tokens → **Activer**.
7. DM your bot with `!link <username> <password>`.

### 7.5. Security

- Channel tokens are stored encrypted in the `system_config` table, marked `is_secret=True` — they never show up in logs or the UI again after save.
- Only users who `/link`ed their chat account to an ELY account can invoke the agent — other messages are silently ignored.
- HITL approvals show as inline buttons (Telegram), emoji reactions (Discord), or Block Kit buttons (Slack).
- Disabling a channel clears its tokens from DB and stops the bot immediately.

---

## 8. Missions — Goal-Driven Persistence Loop

Beyond the request/response chat, ELY can be given a **Mission** : a long-running goal that she breaks down into steps, executes one at a time, evaluates after each step, and replans if she gets stuck. The mission survives backend restarts and runs autonomously in the background.

> **Parallel sub-tasks (`delegate`).** For work that splits into independent pieces, ELY can fan out 2–6 sub-tasks to concurrent instances of the same agent and then returns a single synthesis. These parallel runs are HITL-blocked, so any irreversible action (sending mail, deleting, SSH) is refused inside them — only the top-level agent can ask you for approval.

### When to use a mission vs a chat

| Use case | Mode |
|----------|------|
| "What's the weather?" | Chat (instant answer) |
| "Find 3 articles about Gemma 4, summarise them, put the summary in a Google Doc, and email me the link" | **Mission** (multi-step, stateful) |
| "Translate this paragraph" | Chat |
| "Every morning, build me a brief from my unread emails" | Mission (recurring, see scheduled missions) |

Rule of thumb : if it's a one-shot fact lookup, chat. If it requires *planning + multiple tool calls + a final synthesis*, mission.

### 8.1. Creating a mission from the web UI

1. **Sidebar → Missions**
2. Top-right button **"Nouvelle mission"**
3. Fill in :
   - **Titre** : short label, displayed in lists (max 80 chars)
   - **Goal** : detailed description of what Éli should accomplish (full sentence — be specific !)
   - **Budget itérations** : max number of Plan→Act→Eval cycles (default 15, range 1-200)
   - **Budget tokens** : max LLM tokens consumed (default 50 000)
4. Click **Créer la mission** → mission appears in the list with status `draft`
5. Open the mission detail → click **Démarrer** → next heartbeat (within 10 s) picks it up and starts executing

### 8.2. Creating a mission from Telegram

In a DM with your ELY bot :

```
/mission Météo Paris :: Donne-moi la météo actuelle à Paris et compare avec hier
```

Format : `/mission <titre> :: <goal>` (separator is space-colon-colon-space).

The bot replies instantly with the mission ID + a link to follow progress on the web UI. The mission then runs autonomously and you'll receive the result back as a DM when it's done (or fails).

### 8.3. Watching a mission progress

On `/missions/<id>` you see in real time :

- **Header card** : goal, status badge (Brouillon / Planification / En cours / Terminée / Échec / Abandonnée), iteration counter, token counter, progress bar
- **Plan vN** : checklist of subtasks the agent built, each marked ✅ done / ❌ failed / ⏳ pending. New version appears if the agent had to replan
- **Timeline** : every Plan/Act/Eval/Replan step in chronological order. Click on a step to expand and see the agent's thought, the tool name + input JSON, the tool output, the evaluation, and which model was used

Auto-refresh every 3 s while the mission is active.

### 8.4. Controlling a mission

| Button | Action | When to use |
|--------|--------|-------------|
| Démarrer | draft → planning, schedule first tick | Mission was created in draft |
| Reprendre | paused → planning | Mission was paused, resume it |
| Pause | running → paused | You want to halt without aborting |
| Tick manuel | Run one iteration immediately (don't wait for heartbeat) | Debug, or you're in a hurry |
| Abandonner | Kill switch — instant terminal abort | Mission is going wrong, stop it now |

### 8.5. Heartbeat & guardrails

The **heartbeat** is a background loop that fires every 10 seconds. On each beat :

1. It picks all missions whose `next_tick_at` ≤ now and that are still active (running or planning).
2. For each one, it runs **exactly one iteration** of Plan→Act→Eval (or Replan if 3+ recent failures).
3. If `done` → mission completes + notification fires.
4. Otherwise → schedule next tick at `now + tick_interval_seconds` (default 60 s).

Five **hard guardrails** protect you from runaway missions :

- **Token budget** : if the mission consumes more than `budget_tokens` tokens total → auto-fail
- **Iteration budget** : if it ticks more than `budget_iterations` times → auto-fail
- **Deadline** (optional) : kill at a wall-clock timestamp
- **HITL on critical tools** : send mail / SSH / file delete / etc. always ask for your approval before executing — same UX as in chat mode (web pop-up, ntfy push, Telegram inline button)
- **Anti-loop** : 3 consecutive failed actions → forced replan with reflection (LLM produces a new plan version that explicitly addresses what went wrong)

### 8.6. End-of-mission notifications

When a mission terminates (completed / failed / aborted), you get notifications on **3 channels in parallel** :

- **Web UI** : a message lands in your `[Missions] Notifications` conversation (visible in the chat sidebar)
- **Telegram** : DM with the result, but only if the mission was created via Telegram
- **ntfy** : push notification on your phone (via the ntfy app), if `NTFY_URL` is configured at server level

Each channel is independent — failure of one doesn't block the others.

### 8.7. Routing & cost

By default, missions route the local tier through **Gemma 4 E4B-it** (host-native Ollama). This means **zero API cost** for the typical mission.

If the local model isn't enough, the mission falls back to the configured cloud LLM tiers (e.g. DeepSeek on tier C), with per-conversation auto-fallback. These cost a few cents per mission max.

The tool inventory (~196 ELY tools) is automatically pre-filtered down to ~15 most relevant tools per step (based on the tool hint from the plan + keywords in the goal), so smaller local models can handle the bind without choking.

### 8.8. Structured missions (YAML)

For repeatable multi-step workflows, the free-text goal can be replaced by a
**structured spec**. Why : with a monolithic prompt, forgetting one edge case
("company name is ambiguous", "company not found") means rewriting and
re-testing the whole prompt. With a spec, **adding a forgotten case = adding
ONE line**.

In the **Nouvelle mission** modal, expand *« Mission structurée (YAML) —
optionnel »* :

```yaml
version: 1
steps:
  - id: read_companies
    do: "Lis les noms d'entreprises du Google Sheet « Prospection »."

  - id: enrich
    foreach: "{{ read_companies.output }}"
    do: |
      Trouve le dirigeant de {{ item }} sur LinkedIn et récupère
      nom + email professionnel.
    on_ambiguous: ask_user("Plusieurs résultats pour {{ item }} — lequel ?")
    on_not_found: skip_with_note("{{ item }} introuvable")
    on_in_liquidation: ask_user("{{ item }} est en redressement — continuer ?")
    on_error: resume_next
```

**The contract :**

| Element | Meaning |
|---------|---------|
| `do` | The step instruction, in natural language — the LLM stays in the loop, the spec *frames* execution |
| `foreach` | Iterate over a previous step's result (`{{ step.output }}`) or a free-text source ; one item per tick |
| `on_<case>` | Edge-case handler. **Case names are free** (`on_ambiguous`, `on_in_liquidation`, anything) ; **actions are a closed vocabulary** |
| `ask_user("…")` | Mission pauses on THIS item, pings you (web + ntfy + Telegram), resumes on your answer — the other items keep running |
| `skip_with_note("…")` | Item skipped, note shown in the viewer |
| `resume_next` | Log and move on (also the default for `on_error`) |
| `fail` | Hard-stop the mission |

`{{ item }}` is substituted everywhere (instructions and handler messages).
The spec is validated at creation : **all** errors are listed at once, in
French.

**The execution viewer** — the mission detail page shows a live list (not a
canvas) :

```
✓ read_companies          done
⏳ enrich  5/47            Trouve le dirigeant de {{ item }}…
    ✓ Acme Corp           — Jean Dupont, jean@acme.fr
    ⏸ Gamma SARL          ⚠ Plusieurs résultats pour Gamma SARL — lequel ?
    ⊝ Delta Industries    — Delta Industries introuvable
```

Click the answer field under a ⏸ item, type your reply, press Enter : the
item restarts immediately with your answer injected into the agent's prompt
("RÉPONSE DE L'UTILISATEUR : …"), and the answer stays visible on the item
afterwards (`↳ …`) so you can audit why the agent chose what it chose.

**Guarantees** : structured missions never replan (the spec IS the plan) ;
a repeatedly-failing item is auto-skipped after 2 attempts unless you
declared `on_error` ; the mission completes when every step is done/skipped
— deterministically, not by LLM judgment. Legacy free-text missions are
untouched : `spec_yaml` is optional.

---

## 9. HITL Validation

**HITL (Human-in-the-Loop)** is ELY's mechanism for pausing before irreversible actions and asking for your explicit approval.

### Which actions require approval?

The following actions always require HITL:

| Action | Why |
|---|---|
| Sending an email | Cannot be unsent |
| Creating a calendar event | Modifies your schedule |
| SSH command execution | Can affect remote systems |
| Clicking a button on a web page | May trigger irreversible actions |
| Filling a form on a web page | May submit data |

### How approval works in the web UI

When ELY needs approval, a validation card appears inline in the chat:

```
ELY souhaite exécuter l'action suivante :
  Outil  : send_email
  À      : alice@exemple.com
  Objet  : "Réunion vendredi"

[ ✅ Autoriser ]  [ ❌ Refuser ]  [ 🛡️ Interdire toujours ]
```

**The three buttons:**

| Button | Effect |
|---|---|
| **Autoriser** (Allow once) | The action executes this one time. ELY will ask again next time. |
| **Refuser** (Deny once) | The action is cancelled. ELY continues the conversation. |
| **Interdire toujours** (Ban permanently) | The action is cancelled AND a permanent rule is stored. ELY will never propose this action again, even in future sessions. |

### How approval works on Telegram

The same three choices appear as Telegram inline keyboard buttons directly in the chat message.

### How approval works via push notification (Android / iOS apps)

If you have the ELY Android or iOS app installed, ELY sends a rich push
notification to your device (FCM on Android, APNs on iOS). The notification
contains the action details and three action buttons — **Autoriser**,
**Refuser**, **Interdire toujours** — tappable directly from the notification
shade without opening the app.

### Permanent security rules

When you click "Interdire toujours", ELY stores a rule in Qdrant:

> "Never send emails to external addresses without confirming the recipient first."

This rule is loaded into every future session's system prompt. ELY learns your security preferences over time.

---

## 10. Memory — What ELY Remembers

ELY maintains a persistent memory across all your conversations using a hybrid storage system.

### What is stored

At the end of each conversation, ELY automatically extracts **durable facts** from the dialogue:
- Your name, nickname, preferred language
- Your family members and relationships
- Your work context (role, company, projects)
- Your preferences and habits
- Key dates and commitments

You do not need to configure this — it happens automatically.

### How memory is used

At the start of each response, ELY retrieves the most relevant memories using:
- **Semantic search** (Qdrant vector database): finds conceptually related memories
- **Keyword search** (SQLite FTS5): finds exact term matches
- **Temporal decay**: recent memories score higher than old ones

The retrieved memories are injected into the system prompt invisibly, so ELY's responses are contextualised.

### Influencing ELY's memory

You can directly tell ELY what to remember or forget:

```
Souviens-toi que je préfère les réponses courtes
```
```
Mon adresse email professionnelle est pro@example.com
```
```
Oublie ce que tu sais sur mon ancien projet
```

### What is NOT stored

- The content of your emails, calendar events, or documents — ELY reads these on demand but does not store them in memory
- Your passwords or API keys — these are never visible to the LLM
- Sensitive personal data sent through the SecurityFilter (card numbers, IBANs, etc.)

---

## 11. Security Overview

ELY was designed with security as a first-class concern. Here is a summary of the key mechanisms.

### Data masking (SecurityFilter)

Before ANY data is sent to the LLM, ELY's SecurityFilter scans the input and replaces sensitive values with opaque placeholders:

| Real value | Placeholder sent to LLM |
|---|---|
| `alice@exemple.com` | `[EMAIL_0]` |
| `4532 1234 5678 9012` | `[CARD_0]` |
| `FR76 3000 6000 0112 3456 7890 189` | `[IBAN_0]` |
| `sk-ant-api03-...` | `[TOKEN_0]` |
| `+33 6 12 34 56 78` | `[PHONE_0]` |

The real values are stored in a local session map and restored in the final response before it is shown to you. **The LLM never sees your real sensitive data.**

### HITL (Human-in-the-Loop)

Every irreversible action is paused and requires your explicit approval. See [Section 9](#9-hitl-validation) for full details.

### No credential exposure

Your OAuth tokens and API keys are stored in the local database and injected at execution time using `InjectedToolArg`. The AI model only sees the result of tool calls, never the credentials used to make them.

### JWT authentication

All API requests require a valid JWT token. Access tokens expire after 15 minutes (refresh tokens after 7 days). Rate limiting is enforced at 60 requests per minute per IP address.

### Isolated browser contexts

Each user session gets its own sandboxed Playwright browser context with no shared cookies, history, or local storage. A website visited by one user cannot affect another user's browsing session.

### RGPD-friendly LLM options

If you do not want your data processed outside Europe, switch to:
- **Mistral AI**: processes data on European servers, subject to RGPD
- **Ollama**: runs entirely on your own machine — no data ever leaves your infrastructure

Change the provider in **Settings** > **Fournisseur LLM**.

---

## 12. MCP Server & Personal API Keys

ELY is exposed **as a Model Context Protocol (MCP) server**, so you can drive it from MCP-aware clients such as **Claude Desktop** or **Cursor**.

### Personal API keys

The MCP endpoint is authenticated with a **personal API key** (not your password). To create one:

1. Go to **Settings → Clés API** (`/settings/api-keys`).
2. Click to mint a new key. It is shown **in clear text only once** (prefix `ely_api_` followed by 64 hex characters) — copy it now, because only a SHA-256 hash is stored afterwards.
3. You can hold up to **20 active keys**; revoke any of them at any time.

### Connecting an MCP client

Point your MCP client at the `/api/mcp` endpoint (FastMCP Streamable-HTTP) and send your key as a Bearer token:

```
Authorization: Bearer ely_api_<your-key>
```

The v1 server exposes four tools:

| Tool | What it does |
|---|---|
| `ely_chat` | Run one agent turn in autonomous-safe mode (irreversible actions like sending mail, deleting, or SSH are blocked, since no human can validate from an MCP client). Returns the answer plus a conversation id so you can continue the thread. |
| `ely_list_scheduled_tasks` | List your scheduled tasks (read-only). |
| `ely_create_scheduled_task` | Create a scheduled task (cron expression or `@once <ISO date>`). |
| `ely_memory_search` | Semantic search over your typed memory. |
