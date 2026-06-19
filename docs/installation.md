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
| Docker + Docker Compose v2 | 24+ | Fait tourner tous les services (syntaxe `docker compose`, pas `docker-compose`) |
| Git | any | Cloner le dépôt |
| RAM | 16 Go (32 Go recommandés pour les LLM locaux) | Faire tourner les services + l'inférence locale |
| Ollama *(optionnel)* | latest | Modèles IA locaux (gratuit) |

> **Docker suffit.** L'architecture est entièrement conteneurisée — Python, Node.js, nginx sont gérés dans les containers. Pas besoin de les installer sur la machine hôte.

> **Au moins un fournisseur LLM est requis** (une clé cloud OU un Ollama natif sur l'hôte). Sans aucun fournisseur configuré, ELY démarre mais chaque chat échoue.

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
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent
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
git clone https://github.com/franckolv-dev/ElyAgent.git
cd ElyAgent
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
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
COOKIE_SECURE=false
```

> **Ollama tourne en natif sur l'hôte** (pas dans un conteneur), pour exploiter le GPU Metal sur Mac. Le service `ollama` en conteneur a été retiré — utilisez `make ollama-cleanup` pour purger d'anciens conteneurs s'il en reste. Sous Docker, ELY le joint via `host.docker.internal:11434`.

> **`NEXT_PUBLIC_*` sont figées au build du frontend** (`next build`). Un changement de ces variables nécessite un rebuild du frontend (`make restart s=frontend`), pas un simple redémarrage.

> Sous Docker Compose, `DATABASE_URL` et `QDRANT_URL` sont **forcées** par compose (`sqlite+aiosqlite:////app/data/cyberentity.db` et `http://qdrant:6333`) — les valeurs de `.env` pour ces deux variables ne s'appliquent qu'en bare-metal.

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

Aucun script à lancer : ouvrez [http://localhost:3000](http://localhost:3000) et **inscrivez-vous**. Le **premier utilisateur qui s'inscrit est automatiquement promu administrateur**.

> **Politique de mot de passe** : minimum 12 caractères, au moins 1 majuscule, au moins 1 caractère spécial.

Pour une installation sans navigateur (headless), créez l'admin en ligne de commande :

```bash
make create-admin USER=<nom> PASS=<motdepasse> EMAIL=<email>
```

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
ollama pull qwen2.5:7b     # Télécharger un modèle (sur l'hôte, PAS dans Docker)
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
   http://localhost:8000/api/google/callback
   ```
   (ou `https://votre-domaine.fr/api/google/callback` en production)
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
| `OPENAI_API_KEY` | Clé API OpenAI | `sk-...` |
| `OPENROUTER_API_KEY` | Clé API OpenRouter | — |
| `ZHIPU_API_KEY` | Clé API Zhipu (GLM) | — |
| `QWEN_API_KEY` | Clé API Qwen (+ `QWEN_API_BASE_URL`) | — |
| `MOONSHOT_API_KEY` | Clé API Moonshot (+ `MOONSHOT_BASE_URL`) | — |
| `LM_STUDIO_BASE_URL` | URL LM Studio (MLX local) | `http://host.docker.internal:1234` |
| `OLLAMA_BASE_URL` | URL Ollama | `http://host.docker.internal:11434` |

### Sécurité

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Clé secrète JWT (**obligatoire**) — générez avec `openssl rand -hex 32` (ou `python -c "import secrets; print(secrets.token_hex(32))"`). Le backend **refuse de démarrer** (ValueError au boot) si la valeur est restée au défaut du code ou fait moins de 32 caractères. |
| `JWT_ALGORITHM` | Algorithme JWT (défaut: `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée du token d'accès (défaut: `15` ; refresh : 7 jours) |
| `COOKIE_SECURE` | `true` en HTTPS, `false` en local |

### URLs

| Variable | Description | Local | Production |
|----------|-------------|-------|------------|
| `FRONTEND_URL` | Origine autorisée CORS | `http://localhost:3000` | `https://votre-domaine.fr` |
| `BACKEND_URL` | URL publique du backend | `http://localhost:8000` | `https://votre-domaine.fr` |
| `NEXT_PUBLIC_API_URL` | URL API (figée au build du frontend) | `http://localhost:8000` | `https://votre-domaine.fr` |
| `NEXT_PUBLIC_WS_URL` | URL WebSocket | `ws://localhost:8000` | `wss://votre-domaine.fr` |

### Notifications push

Les notifications push sont gérées nativement par les apps mobiles :

- **Android** : FCM (Firebase Cloud Messaging) — le token est enregistré automatiquement au login, aucune variable d'environnement à positionner. Nécessite le fichier `google-services.json` dans `android/app/`.
- **iOS** : APNs (Apple Push Notification service) — même mécanisme, via la clé `.p8` configurée dans le projet Xcode.

Aucun serveur de notification self-hosted n'est requis.

### Voix

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TTS_VOICE` | Voix edge-tts | `fr-FR-VivienneMultilingualNeural` |

> Ne pas figer `TTS_VOICE` dans `.env` sauf pour la changer — une valeur figée masque les futurs défauts du code.

Autres voix françaises : `fr-FR-HenriNeural` (H), `fr-BE-CharlineNeural` (F)

### SSH

| Variable | Description |
|----------|-------------|
| `SSH_KEYS_PATH` | Chemin vers les clés SSH (défaut: `~/.ssh`) |

### Upload de fichiers

Taille maximale d'un upload : **50 Mo** (`MAX_FILE_SIZE` côté backend + `client_max_body_size 50M` côté nginx).

> ⚠️ Les `.zip` s'uploadent mais **ne sont pas lisibles** par l'agent (aucun outil d'extraction n'existe) — envoyez les fichiers **non zippés**.

### Clés API personnelles & serveur MCP

Les utilisateurs créent des clés API personnelles dans **Settings → Clés API** (`/settings/api-keys`). Une clé a le préfixe `ely_api_` suivi de 64 caractères hexadécimaux, n'est affichée **en clair qu'une seule fois**, et est limitée à 20 clés actives par utilisateur (révocable à tout moment).

Ces clés authentifient le **serveur MCP d'ELY**, exposé sur `/api/mcp` (FastMCP Streamable-HTTP), via l'en-tête `Authorization: Bearer ely_api_…`. Il est consommable depuis **Claude Desktop, Cursor** ou tout autre client MCP. Outils v1 : `ely_chat`, `ely_list_scheduled_tasks`, `ely_create_scheduled_task`, `ely_memory_search`.

---

## 8. Exposer ELY à l'extérieur (3 options, du plus souverain au plus pratique)

ELY n'a **aucune dépendance** vis-à-vis d'un service externe pour fonctionner en local. Si vous voulez y accéder depuis l'extérieur de votre LAN (téléphone en déplacement, autre poste), voici les trois approches courantes, classées par niveau de souveraineté.

### Option A — **Tailscale / WireGuard** (recommandé pour la souveraineté maximale)

Votre machine ELY apparaît dans un VPN privé maillé. Aucun port n'est ouvert publiquement, aucun proxy externe ne voit votre trafic, et la connexion est de bout-en-bout chiffrée. **Aucun acteur tiers ne voit jamais vos requêtes.**

```bash
# Sur macOS, exemple Tailscale
brew install tailscale && tailscale up
# Notez l'IP 100.x.y.z attribuée
# Sur vos autres appareils : installez Tailscale, login → ELY est joignable à https://100.x.y.z:3000
```

Avantage : zéro confiance en un tiers, RGPD-strict, gratuit pour ≤ 100 appareils.
Coût : chaque utilisateur doit installer un client Tailscale.

### Option B — **Reverse proxy local avec certificat Let's Encrypt sur votre IP fixe**

Si vous avez une IP publique fixe (FAI pro, VPS dédié), vous pouvez exposer ELY via un **nginx / Caddy / Traefik** sur votre propre serveur, avec un certificat Let's Encrypt obtenu en validation DNS-01 (pas besoin d'ouvrir le port 80 sortant).

```bash
# Exemple Caddy minimal
caddy reverse-proxy --from ely.mondomaine.fr --to localhost:3000
```

Avantage : aucun tiers entre le navigateur et ELY après le DNS. Certificat TLS sans tiers de confiance autre que Let's Encrypt.
Coût : maintenance du reverse proxy + nécessite une IP publique stable.

### Option C — **Cloudflare Tunnel** (le plus pratique mais avec un compromis souveraineté)

Cloudflare Tunnel ouvre une connexion sortante depuis votre machine vers le réseau CF, qui sert ensuite votre domaine. **Aucun port public à ouvrir, IP cachée**, déploiement en 5 minutes. C'est l'option utilisée par `agent-ely.fr` actuellement.

**Compromis assumé** : le trafic HTTP transite via les serveurs Cloudflare (US-based holding). CF voit donc les requêtes et réponses en clair (puisqu'il termine TLS de son côté). Pour la majorité des cas d'usage personnels c'est acceptable — pour des déploiements professionnels avec données sensibles, préférer Option A ou B.

```bash
# Installation cloudflared sur macOS
brew install cloudflared
cloudflared tunnel login            # ouvre votre dashboard CF dans le navigateur
cloudflared tunnel create ely
cloudflared tunnel route dns ely ely.mondomaine.fr
cloudflared tunnel run --url http://localhost:3000 ely
```

Avantage : zéro configuration réseau, gratuit, résilient.
Coût : Cloudflare est un acteur US-based. À ne pas utiliser pour transmettre des données qui doivent rester en UE par construction.

### Résumé du choix

| Cas d'usage | Recommandation |
|---|---|
| Usage perso, sécurité maximale | Option A (Tailscale) |
| Petite équipe / asso, IP fixe disponible | Option B (Caddy + Let's Encrypt) |
| Démo publique, prototype rapide | Option C (Cloudflare Tunnel) |
| Déploiement pro avec données sensibles (santé, juridique, finance) | Option A obligatoire |
