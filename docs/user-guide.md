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
7. [Telegram Bot Setup](#7-telegram-bot-setup)
8. [HITL Validation](#8-hitl-validation)
9. [Memory — What ELY Remembers](#9-memory--what-ely-remembers)
10. [Security Overview](#10-security-overview)

---

## 1. First Launch and Login

When you open ELY for the first time at `http://localhost:3000`, you will see the login screen.

![Login screen](./screenshots/login.png)

### Creating your account

On the login page, click the **"Créer un compte"** (Register) tab and fill in:
- A username
- An email address
- A password (minimum 8 characters)

The **first account created is automatically assigned the Admin role**. Subsequent accounts are regular users.

### Logging in

Enter your credentials and click **"Se connecter"**. You will be redirected to the main chat interface.

> **Session duration**: access tokens expire after 1 hour. ELY silently refreshes them in the background — you will not be logged out mid-conversation.

---

## 2. Interface Overview

![Light mode chat interface](./screenshots/chat-light.png)

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
- A microphone button for future voice input
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

> SSH commands always require your explicit approval before execution. See [HITL Validation](#8-hitl-validation).

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

![Settings — Google section](./screenshots/settings-google.png)

### Step 2 — Connect Google

Scroll to the **"Intégrations Google"** section. You will see buttons for each Google service:
- Gmail
- Google Calendar
- Google Drive
- Google Docs
- Google Sheets
- Google Tasks

Click **"Connecter Google"**. A Google OAuth consent screen will open in a new tab. Sign in with the Google account you want to use and grant the requested permissions.

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

![Settings — Skills section](./screenshots/settings-skills.png)

Each skill card shows:
- The skill's icon and name
- A short description
- A toggle to enable/disable it
- The list of tools it provides

### Available skills

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

## 7. Telegram Bot Setup

ELY can be reached via Telegram, giving you mobile access with full feature parity.

### Prerequisites

You need a Telegram bot token. Create one by messaging [@BotFather](https://t.me/BotFather) on Telegram and following the `/newbot` instructions.

### Configuration

1. Go to **Admin** > **Configuration** in the ELY interface
2. Enter your bot token in the **"Token Telegram"** field and save
3. In the **Admin** > **Utilisateurs** panel, click your username and add your **Telegram User ID** to your profile

> To find your Telegram User ID, message [@userinfobot](https://t.me/userinfobot) on Telegram.

### Using ELY on Telegram

Once configured, open your bot in Telegram and start chatting. ELY will respond with the same capabilities as the web interface:
- All skills are available
- Memory is shared (ELY remembers the same facts regardless of channel)
- HITL approvals appear as **inline keyboard buttons** (Allow / Deny / Ban)

### Security note

Only Telegram users whose ID is linked to an ELY account can interact with the bot. All other messages are silently ignored.

---

## 8. HITL Validation

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

## 9. Memory — What ELY Remembers

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
Mon adresse email professionnelle est franck@entreprise.com
```
```
Oublie ce que tu sais sur mon ancien projet
```

### What is NOT stored

- The content of your emails, calendar events, or documents — ELY reads these on demand but does not store them in memory
- Your passwords or API keys — these are never visible to the LLM
- Sensitive personal data sent through the SecurityFilter (card numbers, IBANs, etc.)

---

## 10. Security Overview

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

Every irreversible action is paused and requires your explicit approval. See [Section 8](#8-hitl-validation) for full details.

### No credential exposure

Your OAuth tokens and API keys are stored in the local database and injected at execution time using `InjectedToolArg`. The AI model only sees the result of tool calls, never the credentials used to make them.

### JWT authentication

All API requests require a valid JWT token. Tokens expire after 1 hour. Rate limiting is enforced at 60 requests per minute per IP address.

### Isolated browser contexts

Each user session gets its own sandboxed Playwright browser context with no shared cookies, history, or local storage. A website visited by one user cannot affect another user's browsing session.

### RGPD-friendly LLM options

If you do not want your data processed outside Europe, switch to:
- **Mistral AI**: processes data on European servers, subject to RGPD
- **Ollama**: runs entirely on your own machine — no data ever leaves your infrastructure

Change the provider in **Settings** > **Fournisseur LLM**.
