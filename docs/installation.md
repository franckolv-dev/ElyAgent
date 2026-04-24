# ELY Agent — Installation

Ce guide couvre l'installation locale d'ELY sur macOS, Linux et Windows.  
Pour l'accès depuis l'extérieur (téléphone en 4G, webhooks…), consultez [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## Table des matières

1. [Prérequis](#1-prérequis)
2. [macOS](#2-macos)
3. [Linux — Ubuntu / Debian](#3-linux--ubuntu--debian)
4. [Windows (WSL2)](#4-windows-wsl2)
5. [Configuration initiale](#5-configuration-initiale)
6. [Premier démarrage](#6-premier-démarrage)
7. [Google OAuth (optionnel)](#7-google-oauth-optionnel)
8. [Référence des variables d'environnement](#8-référence-des-variables-denvironnement)

---

## 1. Prérequis

| Dépendance | Version minimum | Usage |
|-----------|----------------|-------|
| Docker | 24+ | Fait tourner tous les services |
| Git | any | Cloner le dépôt |
| Ollama *(optionnel)* | latest | Modèles IA locaux (gratuit) |

> **Docker suffit.** L'architecture est entièrement conteneurisée — Python, Node.js, nginx sont gérés dans les containers. Pas besoin de les installer sur la machine hôte.

---

## 2. macOS

### Étape 1 — Installer Docker Desktop

Téléchargez et installez [Docker Desktop pour Mac](https://www.docker.com/products/docker-desktop/).  
Démarrez Docker Desktop depuis vos Applications.

### Étape 2 — Installer Ollama (recommandé pour les modèles locaux)

```bash
brew install ollama
# ou téléchargez depuis https://ollama.com

# Démarrer Ollama
ollama serve &

# Télécharger un modèle (exemples)
ollama pull gemma4:26b      # Excellent rapport qualité/vitesse (26B, ~17 Go)
ollama pull qwen2.5:7b      # Léger et rapide (~4.7 Go)
ollama pull phi4-mini       # Ultra-léger (~2.5 Go)
```

> **Apple Silicon** (M1/M2/M3/M4) : Ollama exploite le GPU Metal nativement — les inférences sont très rapides même sur les grands modèles.

### Étape 3 — Cloner le dépôt

```bash
git clone https://github.com/franckolv-dev/PhysicalAgent.git
cd PhysicalAgent
```

### Étape 4 — Configurer l'environnement

```bash
cp .env.example .env
# Éditez .env avec vos valeurs (voir section 5)
```

---

## 3. Linux — Ubuntu / Debian

### Étape 1 — Installer Docker

```bash
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker $USER
newgrp docker   # ou déconnectez/reconnectez-vous
```

### Étape 2 — Installer Ollama (optionnel)

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Activer le service
sudo systemctl enable ollama
sudo systemctl start ollama

# Télécharger un modèle
ollama pull qwen2.5:7b
```

### Étape 3 — Cloner et configurer

```bash
git clone https://github.com/franckolv-dev/PhysicalAgent.git
cd PhysicalAgent
cp .env.example .env
# Éditez .env
```

---

## 4. Windows (WSL2)

WSL2 est fortement recommandé pour la meilleure compatibilité.

### Étape 1 — Activer WSL2

Dans PowerShell en administrateur :
```powershell
wsl --install
```
Redémarrez, puis ouvrez **Ubuntu** depuis le menu Démarrer.

### Étape 2 — Dans le terminal Ubuntu, suivez les instructions Linux

### Étape 3 — Docker Desktop pour Windows

Installez [Docker Desktop pour Windows](https://www.docker.com/products/docker-desktop/) et activez l'intégration WSL2 dans les paramètres Docker.

---

## 5. Configuration initiale

Éditez le fichier `.env` à la racine du projet. Valeurs minimales requises :

```env
# ── Sécurité (OBLIGATOIRE) ────────────────────────────────────────────
# Générez avec : python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=remplacez-par-une-vraie-clé-secrète

# ── Modèle IA ─────────────────────────────────────────────────────────
ACTIVE_LLM_PROVIDER=ollama
ACTIVE_LLM_MODEL=qwen2.5:7b

# Ollama sur macOS/Linux avec Docker : utiliser host.docker.internal
OLLAMA_BASE_URL=http://host.docker.internal:11434

# ── URLs (accès local uniquement) ────────────────────────────────────
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:3000
NEXT_PUBLIC_WS_URL=ws://localhost:3000
COOKIE_SECURE=false
```

> Pour un accès depuis l'extérieur (autre appareil, 4G…), consultez [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 6. Premier démarrage

```bash
# Depuis la racine du projet
make up        # Démarre tous les services (build automatique au premier lancement)
make ps        # Vérifie l'état des containers
```

Attendez que tous les containers soient `healthy` (30-60 secondes). Puis :

```
http://localhost:3000   → Interface ELY
http://localhost:8000/docs → API Swagger (debug)
```

### Créer le compte administrateur

La base de données est vide au premier démarrage. Créez votre compte :

```bash
docker exec cyberentity-backend uv run python -c "
import asyncio
from app.database import async_session
from app.models.user import User
from app.auth.passwords import hash_password

async def create():
    async with async_session() as db:
        user = User(
            email='admin',
            username='admin',
            hashed_password=await hash_password('votre-mot-de-passe'),
            role='admin',
            is_active=True
        )
        db.add(user)
        await db.commit()
        print('Compte admin créé !')

asyncio.run(create())
"
```

> Remplacez `admin` et `votre-mot-de-passe` par vos valeurs.

### Configurer les modèles IA dans l'interface

1. Connectez-vous → **Settings → Modèles IA**
2. Cliquez **+ Ajouter** → choisissez votre provider (Ollama, Anthropic, Gemini…)
3. Allez dans **Routage** pour assigner les modèles aux niveaux de complexité

### Commandes utiles

```bash
make up                   # Démarrer tout
make down                 # Arrêter tout
make restart s=backend    # Redémarrer un service
make logs s=backend       # Logs en temps réel
make build                # Rebuild complet (après modification du code)

# Modèles Ollama
make slm-pull m=llama3:8b  # Télécharger un modèle
make slm-enable            # Activer le SLM (modèle léger pour tâches simples)
```

---

## 7. Google OAuth (optionnel)

Permet à ELY d'accéder à Gmail, Calendar, Drive, Docs, Sheets et Tasks.

### Étape 1 — Créer un projet Google Cloud

1. Allez sur [console.cloud.google.com](https://console.cloud.google.com)
2. Créez un projet (ex: `ELY Agent`)
3. Activez les APIs : Gmail, Calendar, Drive, Docs, Sheets, Tasks

### Étape 2 — Créer des identifiants OAuth2

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
2. Type : **Web application**
3. URI de redirection autorisée :
   ```
   http://localhost:8000/auth/google/callback
   ```
   (ou `https://votre-domaine.fr/auth/google/callback` en production)
4. Téléchargez le fichier JSON

### Étape 3 — Placer le fichier credentials

```bash
cp ~/Téléchargements/client_secret_*.json backend/credentials.json
```

### Étape 4 — Autoriser dans l'interface

**Settings → Intégrations → Connecter Google** → suivez le flux OAuth.

---

## 8. Référence des variables d'environnement

### LLM (au moins un provider requis)

| Variable | Description | Exemple |
|----------|-------------|---------|
| `ACTIVE_LLM_PROVIDER` | Provider actif | `ollama` / `anthropic` / `gemini` / `mistral` / `deepseek` |
| `ACTIVE_LLM_MODEL` | Modèle par défaut | `gemma4:26b` |
| `ANTHROPIC_API_KEY` | Clé API Anthropic | `sk-ant-api03-...` |
| `GEMINI_API_KEY` | Clé API Google Gemini | `AIzaSy...` |
| `MISTRAL_API_KEY` | Clé API Mistral | — |
| `DEEPSEEK_API_KEY` | Clé API DeepSeek | — |
| `OPENROUTER_API_KEY` | Clé API OpenRouter | — |
| `ZHIPU_API_KEY` | Clé API Zhipu (GLM) | — |
| `OLLAMA_BASE_URL` | URL Ollama | `http://host.docker.internal:11434` |

### Sécurité

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Clé secrète JWT (obligatoire) — générez avec `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_ALGORITHM` | Algorithme JWT (défaut: `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée du token d'accès (défaut: `60`) |
| `COOKIE_SECURE` | `true` en HTTPS, `false` en local |

### URLs

| Variable | Description | Local | Production |
|----------|-------------|-------|------------|
| `FRONTEND_URL` | Origine autorisée CORS | `http://localhost:3000` | `https://votre-domaine.fr` |
| `BACKEND_URL` | URL publique du backend | `http://localhost:8000` | `https://votre-domaine.fr` |
| `NEXT_PUBLIC_API_URL` | URL API (baked dans le frontend) | `http://localhost:3000` | `https://votre-domaine.fr` |
| `NEXT_PUBLIC_WS_URL` | URL WebSocket | `ws://localhost:3000` | `wss://votre-domaine.fr` |

### Notifications push

Les notifications push sont gérées nativement par les apps mobiles :

- **Android** : FCM (Firebase Cloud Messaging) — le token est enregistré automatiquement au login, aucune variable d'environnement à positionner. Nécessite le fichier `google-services.json` dans `android/app/`.
- **iOS** : APNs (Apple Push Notification service) — même mécanisme, via la clé `.p8` configurée dans le projet Xcode.

Aucun serveur de notification self-hosted n'est requis.

### Voix

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TTS_VOICE` | Voix edge-tts | `fr-FR-DeniseNeural` |

Autres voix françaises : `fr-FR-HenriNeural` (H), `fr-BE-CharlineNeural` (F)

### SSH

| Variable | Description |
|----------|-------------|
| `SSH_KEYS_PATH` | Chemin vers les clés SSH (défaut: `~/.ssh`) |
