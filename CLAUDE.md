# CLAUDE.md — Projet ELY / PhysicalAgent

## Vue d'ensemble

Agent IA personnel **Éli** (féminin, "Éli" phonétique — jamais "ELY" lettre par lettre).
- **Repo GitHub** : `github.com:franckolv-dev/PhysicalAgent.git`
- **Branche principale** : `master`
- **VPS production** : `root@ely.catalogmaker.fr` → `/opt/agent`
- **Domaine** : `https://ely.catalogmaker.fr`

## Structure du projet

```
PhysicalAgent-master/
├── android/          # App Android Kotlin / Jetpack Compose
├── ios/              # App iOS SwiftUI (22 fichiers, iOS 17+)
├── backend/          # FastAPI + LangGraph (Python, uv)
│   ├── app/
│   │   ├── agent/        # Graph LangGraph, supervisor, nodes, sub-agents
│   │   ├── channels/     # Telegram, Slack, Discord, WhatsApp
│   │   ├── routers/      # REST + WebSocket endpoints
│   │   ├── services/     # RAG, voice, marketplace, audit, memory, etc.
│   │   ├── skills/       # Builtin + community skills
│   │   └── models/       # SQLAlchemy models
│   └── tests/        # Tests unitaires (pytest)
├── frontend/         # Next.js + avatar 3D cyberpunk
├── desktop/          # ELY Desktop (Go)
├── config/           # Fichiers de configuration (monté en :ro)
├── data/db/          # SQLite (volume Docker, non commité)
├── docker-compose.yml
├── Makefile
└── .env              # Variables d'environnement (non commité)
```

## Commandes Docker (toujours depuis la racine du projet)

```bash
make up               # Démarrer tous les services
make down             # Arrêter
make build            # Rebuild + restart tout
make restart s=backend  # Rebuild + restart un service
make logs s=backend   # Logs d'un service
make ps               # État des containers

# SLM / Ollama
make slm-pull [m=qwen2.5:7b-instruct]
make slm-enable / make slm-disable
```

**IMPORTANT** : Ne jamais lancer depuis un sous-répertoire — les contextes de build seront incorrects.

## Containers Docker

| Container | Service |
|-----------|---------|
| `cyberentity-backend` | FastAPI backend |
| `cyberentity-frontend` | Next.js frontend |
| `cyberentity-ollama` | Ollama SLM |
| `cyberentity-qdrant` | Mémoire vectorielle |

## Tests backend

```bash
cd backend
python -m pytest tests/ -v
```

## Déploiement VPS — méthode obligatoire

Le VPS `/opt/agent` **n'est pas un repo git** — le code est baked dans les images Docker.

### Fix rapide backend (sans rebuild image)
```bash
rsync -av backend/app/chemin/fichier.py root@ely.catalogmaker.fr:/opt/agent/backend/app/chemin/
ssh root@ely.catalogmaker.fr "docker cp /opt/agent/backend/app/chemin/fichier.py cyberentity-backend:/app/chemin/ && docker restart cyberentity-backend"
```

### Changements structurels ou frontend
```bash
# 1. Sync les fichiers modifiés
rsync -av backend/ root@ely.catalogmaker.fr:/opt/agent/backend/
rsync -av frontend/ root@ely.catalogmaker.fr:/opt/agent/frontend/

# 2. Rebuild et restart SUR LE VPS
ssh root@ely.catalogmaker.fr "cd /opt/agent && docker compose build backend && docker compose up -d backend"

# 3. Vérifier via https://ely.catalogmaker.fr — JAMAIS via localhost ou 100.100.150.110
```

**⚠️ `100.100.150.110` = machine locale Franck (Tailscale) — NE PAS confondre avec le VPS (72.61.192.29)**

## Variables d'environnement

Deux fichiers `.env` :
- `/Agent/.env` — root, utilisé par docker-compose (`env_file:`)
- `backend/.env` — dev local uniquement

Docker Compose v5 ne charge plus le `.env` automatiquement → `env_file:` obligatoire dans chaque service.

Les vars `NEXT_PUBLIC_*` doivent être passées en `ARG`/`ENV` au stage builder du Dockerfile frontend (baked at build time).

## Règles importantes

### Architecture agent (supervisor.py)
Pour ajouter un skill Google/tool à l'agent, il faut l'ajouter dans **3 endroits** de `supervisor.py` :
1. `_DOMAIN_DESCRIPTIONS["workspace"]`
2. `_SPECIALIST_PROMPTS["workspace"]` (description + liste des outils)
3. `_WORKSPACE_SKILLS`

Oublier l'un des trois rend le tool **invisible à l'agent**.

### Sécurité
- Les tools `InjectedToolArg` ne voient jamais leur valeur dans le prompt LLM (by design)
- `async_session()` utilisé directement dans les tools (pas de DI FastAPI)
- Ne jamais commiter `.env`, clés Firebase, secrets JWT

### Docker Compose
- `env_file: - .env` explicite sur chaque service (Docker Compose v5)
- Ne jamais déplacer `backend/` ou `frontend/` — ce sont les contextes de build trackés par git

## Workflow git + mémoire

1. Développement local → tests → commit
2. Dans le même commit : mettre à jour `docs/memory.md` (ce qui a été fait / pourquoi / comment / où)
3. Push sur GitHub (`master`)
4. Déploiement sur VPS via rsync + rebuild docker

## Canaux de communication

| Canal | Fichier backend | Notes |
|-------|----------------|-------|
| Web UI (WebSocket) | `app/routers/chat.py` | `/ws/chat` — JWT handshake |
| Voice mode (WebSocket) | `app/routers/voice.py` | `/ws/voice` — STT→Agent→TTS en boucle |
| Telegram | `app/channels/telegram_bot.py` | HITL via inline keyboard |
| Slack | `app/channels/slack_bot.py` | Socket Mode, Block Kit HITL |
| Discord | `app/channels/discord_bot.py` | DM + @mention, emoji HITL |
| WhatsApp | `app/channels/whatsapp.py` | Webhook Twilio |

## Services clés ajoutés (Phase 1-4)

| Service | Fichier | Rôle |
|---------|---------|------|
| RAG documentaire | `app/services/rag_service.py` | Ingestion → chunking → embedding → retrieval |
| Context manager | `app/services/context_manager.py` | Compteur tokens, troncation, résumé glissant |
| Voice service | `app/services/voice_service.py` | Config voix, prompt voice-optimized |
| Marketplace | `app/services/marketplace.py` | Skills communautaires sécurisés |
| Audit service | `app/services/audit_service.py` | Logging enrichi + export CSV |
| RAG detector | `app/services/rag_detector.py` | Détecte si une requête justifie une recherche documentaire |
| Agentic RAG tool | `app/agent/tools/agentic_rag_tool.py` | `smart_knowledge_query` — recherche proactive + reranking |
| Arena service | `app/services/arena_service.py` | Comparaison LLM en aveugle + classement ELO (K=32) |

## Mode Arena

- Page frontend `/arena` (visible dans la sidebar de tous les users)
- Endpoints : `POST /api/arena/match`, `POST /api/arena/vote`, `GET /api/arena/leaderboard`, `GET /api/arena/history`, `GET /api/arena/models`
- Deux modèles sont tirés aléatoirement parmi les providers configurés (gemini, anthropic, mistral, deepseek, openrouter, zhipu, ollama)
- Les réponses sont **en aveugle** ("Modèle A/B") jusqu'au vote ; révélation après vote
- ELO commence à 1000, K=32, `(1, 0.5, 0)` pour (victoire, égalité, défaite). Voter `both_bad` = égalité (pénalisation symétrique).

## PWA

- Manifest `/manifest.json` déclaré dans `layout.tsx` via `metadata.manifest`
- Service worker `/sw.js` enregistré en **production uniquement** (évite le conflit avec le hot-reload Next)
- Strategies : network-first pour les navigations, stale-while-revalidate pour les assets, **jamais de cache** pour `/api/*`, `/ws/*`, `/auth/*`, `/tts/*`
- Install prompt différé de 30 s, re-déclenchable après 7 jours si "plus tard"
- Page `/offline` dédiée servie quand fetch échoue

## Identité Éli

- Féminin, "Éli" phonétique
- Ne jamais écrire "ELY" lettre par lettre dans les prompts système
- Ne jamais simuler des erreurs d'outils manquants (anti-hallucination stricte)
