# Cyber-Entity — AI Agent

Agent IA omni-connecté avec interface web cyberpunk. Permet d'interagir avec des machines distantes via SSH, d'analyser des fichiers et de gérer des systèmes depuis une interface chat en temps réel.

## Stack

| Composant | Technologie |
|-----------|------------|
| Backend | Python 3.12 + FastAPI + LangGraph |
| Frontend | Next.js 16 + React + Tailwind CSS |
| Auth | JWT (python-jose) + Argon2 |
| LLM | Claude Haiku (Anthropic) / Ollama / DeepSeek |
| SSH | Paramiko + whitelist de commandes |
| VPN | Tailscale (recommandé) |
| DB | SQLite (aiosqlite + SQLAlchemy) |

## Démarrage rapide

### 1. Configuration

```bash
cp .env.example backend/.env
# Éditer backend/.env : renseigner ANTHROPIC_API_KEY et JWT_SECRET_KEY
```

### 2. Backend

```bash
cd backend
pip install uv
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
# Ouvre http://localhost:3000
```

### 4. Premier lancement

- Ouvrir http://localhost:3000
- Créer un compte (le premier compte est automatiquement **admin**)
- Commencer à chatter avec l'agent

## Configuration des hosts SSH

Éditer `config/hosts.yaml` :

```yaml
hosts:
  mon-serveur:
    hostname: 192.168.1.100
    port: 22
    username: ubuntu
    key_file: ~/.ssh/id_rsa
    allowed_commands:
      - "df -h"
      - "docker ps"
      - "systemctl status *"
    blocked_patterns:
      - "rm -rf"
      - "dd if="
```

## Changer de provider LLM

Dans `backend/.env` :

```env
# Option A - Local (nécessite Ollama + GPU)
ACTIVE_LLM_PROVIDER=ollama
ACTIVE_LLM_MODEL=qwen2.5:7b

# Option B - Hybride (recommandé)
ACTIVE_LLM_PROVIDER=anthropic
ACTIVE_LLM_MODEL=claude-haiku-4-5-20251001

# Option C - Performance
ACTIVE_LLM_PROVIDER=anthropic
ACTIVE_LLM_MODEL=claude-sonnet-4-6
```

## Sécurité

- Chaque commande SSH est vérifiée contre une whitelist par host
- Toutes les actions SSH sont auditées en base de données
- JWT avec expiration courte (1h access token)
- Rate limiting : 60 req/min par IP
- Premier utilisateur créé = admin automatiquement

## Structure

```
Agent/
├── backend/         # FastAPI + LangGraph
├── frontend/        # Next.js + Tailwind
└── config/
    ├── hosts.yaml   # SSH hosts + whitelists
    └── providers.yaml  # LLM providers
```
