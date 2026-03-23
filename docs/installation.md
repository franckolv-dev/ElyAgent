# ELY Agent — Installation Guide

This guide covers installing ELY on Linux (Ubuntu/Debian), macOS, and Windows. Choose the section for your platform.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Linux — Ubuntu / Debian](#2-linux--ubuntu--debian)
3. [macOS](#3-macos)
4. [Windows](#4-windows)
5. [Environment Variables Reference](#5-environment-variables-reference)
6. [First Run](#6-first-run)
7. [Google OAuth Setup](#7-google-oauth-setup)
8. [Verifying the Installation](#8-verifying-the-installation)

---

## 1. Prerequisites

ELY requires the following on all platforms:

| Dependency | Minimum version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| Node.js | 18+ | Frontend build and dev server |
| npm | 9+ | Frontend package manager (bundled with Node.js) |
| Docker | 24+ | Runs the Qdrant vector database |
| Git | any | Clone the repository |

---

## 2. Linux — Ubuntu / Debian

These instructions are tested on Ubuntu 22.04 LTS and 24.04 LTS.

### Step 1 — Install system dependencies

```bash
sudo apt update
sudo apt install -y git python3.12 python3.12-venv python3-pip curl

# Install Node.js 20 via NodeSource
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Docker
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker $USER
# Log out and back in, or run: newgrp docker
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/your-username/ely-agent.git
cd ely-agent
```

### Step 3 — Start Qdrant (vector database)

```bash
docker run -d \
  --name qdrant \
  --restart unless-stopped \
  -p 6333:6333 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

Verify it is running:
```bash
curl http://localhost:6333/readyz
# Expected: {"status":"ok"}
```

### Step 4 — Configure the backend

```bash
cd backend
cp .env.example .env
```

Open `.env` in your editor and fill in the required values at minimum:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...   # Required if using Claude
JWT_SECRET_KEY=...                    # Generate with: openssl rand -hex 32
```

Generate a secure `JWT_SECRET_KEY`:
```bash
openssl rand -hex 32
```

### Step 5 — Install backend dependencies

```bash
# Install uv (fast Python package manager)
pip install uv

# Install all Python dependencies from pyproject.toml / uv.lock
uv sync

# Install Playwright's Chromium browser (needed for web browsing tools)
uv run playwright install chromium
```

### Step 6 — Install frontend dependencies

```bash
cd ../frontend
npm install
```

### Step 7 — Launch ELY

From the repository root:

```bash
cd ..
chmod +x start.sh
./start.sh
```

The `start.sh` script starts both the backend (FastAPI on port 8000) and the frontend (Vite dev server on port 3000) concurrently.

Alternatively, start them in separate terminals:

```bash
# Terminal 1 — backend
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

### Step 8 — Open the app

Navigate to **http://localhost:3000** in your browser.

---

## 3. macOS

Tested on macOS 13 (Ventura) and 14 (Sonoma), Apple Silicon and Intel.

### Step 1 — Install Homebrew

If you do not have Homebrew installed:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Step 2 — Install system dependencies

```bash
brew install python@3.12 node@20 git

# Add Python 3.12 to PATH (Apple Silicon)
echo 'export PATH="/opt/homebrew/opt/python@3.12/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Verify
python3.12 --version
node --version
```

### Step 3 — Install Docker Desktop

Download and install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/). After installation, start Docker Desktop from your Applications folder.

### Step 4 — Follow Linux steps 2–8

Once Docker, Python 3.12, and Node.js 20 are installed, the remaining steps are identical to the Linux instructions above (Steps 2 through 8).

> **Tip**: If you encounter permission errors with npm, do NOT use `sudo npm install`. Instead, fix npm's permissions by running `npm config set prefix ~/.npm-global` and adding `~/.npm-global/bin` to your `PATH`.

---

## 4. Windows

There are two approaches for Windows. **WSL2 is strongly recommended** for the best compatibility.

---

### Option A — WSL2 (Recommended)

WSL2 runs a real Ubuntu environment inside Windows. It provides the best compatibility with all ELY features.

#### Step 1 — Enable WSL2

Open PowerShell as Administrator:
```powershell
wsl --install
```
Restart your computer when prompted. By default, this installs Ubuntu.

#### Step 2 — Open Ubuntu terminal

From the Start menu, open **Ubuntu**. Set your username and password.

#### Step 3 — Follow the Linux instructions

Inside the Ubuntu terminal, follow the [Linux — Ubuntu / Debian](#2-linux--ubuntu--debian) instructions exactly.

> **Accessing ELY**: open `http://localhost:3000` in your Windows browser. WSL2 automatically forwards ports.

---

### Option B — Native Windows (PowerShell)

Use this only if WSL2 is not available on your machine.

#### Step 1 — Install prerequisites

- **Python 3.12**: download from [python.org](https://www.python.org/downloads/). During installation, check "Add Python to PATH".
- **Node.js 20**: download from [nodejs.org](https://nodejs.org/).
- **Docker Desktop**: download from [docker.com](https://www.docker.com/products/docker-desktop/).
- **Git**: download from [git-scm.com](https://git-scm.com/).

#### Step 2 — Clone the repository

```powershell
git clone https://github.com/your-username/ely-agent.git
cd ely-agent
```

#### Step 3 — Start Qdrant

```powershell
docker run -d `
  --name qdrant `
  --restart unless-stopped `
  -p 6333:6333 `
  -v qdrant_storage:/qdrant/storage `
  qdrant/qdrant
```

#### Step 4 — Configure the backend

```powershell
cd backend
copy .env.example .env
# Edit .env with notepad or VS Code
```

#### Step 5 — Install backend dependencies

```powershell
pip install uv
uv sync
uv run playwright install chromium
```

#### Step 6 — Install frontend dependencies

```powershell
cd ..\frontend
npm install
```

#### Step 7 — Launch ELY

```powershell
# Terminal 1 — backend
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

Navigate to **http://localhost:3000**.

---

## 5. Environment Variables Reference

The `.env` file lives at `backend/.env`. Below is the complete reference.

### Required

| Variable | Description | Example |
|---|---|---|
| `JWT_SECRET_KEY` | Secret key for signing JWT tokens. Generate with `openssl rand -hex 32`. | `a3f8c...` |

### LLM Providers (at least one required)

| Variable | Description | Default |
|---|---|---|
| `ACTIVE_LLM_PROVIDER` | Active LLM provider: `anthropic`, `mistral`, `ollama`, or `deepseek` | `anthropic` |
| `ACTIVE_LLM_MODEL` | Model identifier for the active provider | `claude-sonnet-4-5` |
| `ANTHROPIC_API_KEY` | API key from [console.anthropic.com](https://console.anthropic.com) | — |
| `MISTRAL_API_KEY` | API key from [console.mistral.ai](https://console.mistral.ai) | — |
| `DEEPSEEK_API_KEY` | API key from [platform.deepseek.com](https://platform.deepseek.com) | — |
| `OLLAMA_BASE_URL` | URL of your local Ollama instance | `http://localhost:11434` |

**Provider + model combinations:**

```env
# Anthropic Claude (cloud, highest capability)
ACTIVE_LLM_PROVIDER=anthropic
ACTIVE_LLM_MODEL=claude-sonnet-4-5

# Mistral AI (cloud, European servers, RGPD-compliant)
ACTIVE_LLM_PROVIDER=mistral
ACTIVE_LLM_MODEL=mistral-small-latest

# Ollama (100% local, no data leaves your machine)
ACTIVE_LLM_PROVIDER=ollama
ACTIVE_LLM_MODEL=qwen2.5:7b

# DeepSeek (cloud, cost-efficient)
ACTIVE_LLM_PROVIDER=deepseek
ACTIVE_LLM_MODEL=deepseek-chat
```

### Infrastructure

| Variable | Description | Default |
|---|---|---|
| `QDRANT_URL` | URL of the Qdrant instance | `http://localhost:6333` |
| `FRONTEND_URL` | URL of the frontend, used for CORS | `http://localhost:3000` |
| `DATABASE_URL` | SQLite database path | `sqlite+aiosqlite:///./ely.db` |

### Optional — Notifications

| Variable | Description |
|---|---|
| `NTFY_URL` | URL of your ntfy server (e.g., `https://ntfy.sh`) |
| `NTFY_TOPIC` | ntfy topic name for push notifications |

When both are set, ELY sends HITL approval requests as push notifications to the [ntfy Android app](https://ntfy.sh).

### Optional — Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |

### Optional — SSH

| Variable | Description | Default |
|---|---|---|
| `SSH_CONFIG_PATH` | Path to the SSH hosts YAML config file | `config/hosts.yaml` |

---

## 6. First Run

### Creating the admin account

The first time you open `http://localhost:3000`, you will see the login screen. Click the **"Créer un compte"** tab and register.

**The first account created automatically receives the Admin role.** Subsequent accounts are regular users.

### Verifying the backend is running

The FastAPI backend exposes interactive API documentation at:
```
http://localhost:8000/docs
```

This Swagger UI is useful for debugging and exploring the API.

### Database initialisation

ELY automatically creates and migrates the SQLite database on first startup. No manual database setup is required.

---

## 7. Google OAuth Setup

To enable Gmail, Calendar, Drive, Docs, Sheets, and Tasks, you need OAuth2 credentials from Google Cloud Console.

### Step 1 — Create a Google Cloud project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "ELY Agent")

### Step 2 — Enable APIs

In the project, go to **APIs & Services** > **Enabled APIs** and enable:
- Gmail API
- Google Calendar API
- Google Drive API
- Google Docs API
- Google Sheets API
- Google Tasks API

### Step 3 — Create OAuth2 credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth client ID**
3. Application type: **Web application**
4. Add the following to **Authorised redirect URIs**:
   ```
   http://localhost:8000/auth/google/callback
   ```
5. Click **Create** and download the JSON file

### Step 4 — Configure ELY

Place the downloaded credentials file at:
```
backend/credentials.json
```

ELY will automatically detect this file on startup and enable the Google OAuth flow.

### Step 5 — Authorise in the app

In ELY's **Settings** > **Intégrations Google**, click **"Connecter Google"** and complete the OAuth flow in the browser.

> **Note for production use**: you must verify your Google OAuth application with Google before accounts outside your organisation can authorise it. For personal use, add your own Google account as a **test user** in the OAuth consent screen settings.

---

## 8. Verifying the Installation

Run through this checklist to confirm everything is working:

```
[ ] http://localhost:3000 loads the ELY login page
[ ] You can create an account and log in
[ ] The chat interface loads with the 3D avatar visible
[ ] ELY responds to "bonjour" in the chat
[ ] http://localhost:6333/readyz returns {"status":"ok"}
[ ] http://localhost:8000/docs loads the API documentation
```

### Common issues

**Backend fails to start — "qdrant connection refused"**
Make sure the Qdrant Docker container is running:
```bash
docker ps | grep qdrant
# If not running:
docker start qdrant
```

**Frontend shows "Cannot connect to backend"**
Check that the backend is running on port 8000 and that `FRONTEND_URL` in `.env` matches the frontend address.

**Playwright install fails**
Run with verbose output:
```bash
uv run playwright install chromium --with-deps
```
On Ubuntu, this also installs required system libraries automatically.

**Google OAuth "redirect_uri_mismatch" error**
Ensure the redirect URI in your Google Cloud Console credentials exactly matches:
```
http://localhost:8000/auth/google/callback
```
(including the `/callback` path, with no trailing slash)
