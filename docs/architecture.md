# ELY Agent — Architecture

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CANAUX D'ENTRÉE                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Web UI   │  │ Telegram │  │ WhatsApp │  │ Autres (futur)   │   │
│  │ (Next.js)│  │   Bot    │  │   Bot    │  │ Signal, Slack... │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │ WebSocket    │ HTTP        │                  │             │
└───────┼──────────────┼─────────────┼──────────────────┼─────────────┘
        │              │             │                  │
        ▼              ▼             ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     GATEWAY (FastAPI)                               │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │ Auth Layer  │  │ Rate Limiter │  │ Channel Router             │ │
│  │ JWT + Cookie│  │ 60/min       │  │ WebSocket / HTTP / Polling │ │
│  └─────────────┘  └──────────────┘  └────────────────────────────┘ │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    SECURITY LAYER                            │   │
│  │  ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐ │   │
│  │  │ Anonymisation │  │   HITL     │  │ Contraintes apprises │ │   │
│  │  │ (PII → [TAG]) │  │ Validation │  │ (Qdrant persistent)  │ │   │
│  │  └──────────────┘  └────────────┘  └──────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    AGENT (LangGraph)                          │   │
│  │                                                              │   │
│  │  ┌────────────┐    ┌──────────────┐    ┌─────────────┐      │   │
│  │  │ agent_node │───▶│should_continue│───▶│  tool_node  │──┐   │   │
│  │  │ (LLM call) │◀───│  (router)    │    │ (exécution) │  │   │   │
│  │  └────────────┘    └──────────────┘    └─────────────┘  │   │   │
│  │        ▲                                                │   │   │
│  │        └────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      OUTILS                                  │   │
│  │  ┌─────┐ ┌───────┐ ┌──────────┐ ┌──────┐ ┌──────┐ ┌──────┐ │   │
│  │  │ SSH │ │ Gmail │ │ Calendar │ │ Docs │ │Sheets│ │Tasks │ │   │
│  │  └─────┘ └───────┘ └──────────┘ └──────┘ └──────┘ └──────┘ │   │
│  │  ┌───────┐ ┌────────┐ ┌───────────┐                         │   │
│  │  │ Drive │ │ System │ │ File Anal │                         │   │
│  │  └───────┘ └────────┘ └───────────┘                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│   SQLite     │  │   Qdrant         │  │   Google APIs            │
│              │  │   (Vector DB)    │  │                          │
│ • users      │  │ • memories       │  │ • Gmail API              │
│ • messages   │  │ • constraints    │  │ • Calendar API           │
│ • convos     │  │ • interactions   │  │ • Drive API              │
│ • audit_log  │  │                  │  │ • Docs API               │
│ • sys_config │  │                  │  │ • Sheets API             │
│ • sched_tasks│  │                  │  │ • Tasks API              │
└──────────────┘  └──────────────────┘  └──────────────────────────┘
```

## Composants principaux

### 1. Frontend (Next.js / React)

**Localisation** : `frontend/`

- App Router Next.js 14+ avec pages `/chat`, `/settings`, `/admin`, `/dashboard`
- WebSocket pour le chat temps réel avec reconnexion automatique
- Avatar 3D animé (Three.js / react-three-fiber)
- Mode sombre / clair avec thème cyan
- `authFetch()` : wrapper fetch avec auto-refresh JWT

### 2. Backend (FastAPI / Python)

**Localisation** : `backend/`

- API REST + WebSocket
- Auth JWT avec refresh_token en cookie HttpOnly
- Rate limiting, CORS configurable
- Routeurs : `auth`, `chat`, `hosts`, `admin`, `health`, `google`, `tts`, `validation`

### 3. Agent IA (LangGraph)

**Localisation** : `backend/app/agent/`

- `graph.py` : construction du graphe LangGraph
- `state.py` : `AgentState` TypedDict (messages, user_id, conversation_id, google_credentials)
- `nodes.py` : `agent_node` (appel LLM), `tool_node` (exécution outils), `should_continue` (routage)
- `tools/` : 16 outils organisés par service

### 4. Mémoire (Qdrant + SQLite)

**Court terme** : historique de conversation (40 derniers messages) chargé depuis SQLite
**Long terme** : 3 collections Qdrant interrogées par similarité sémantique à chaque message :
- `memories` — résumés de conversation (générés à la déconnexion)
- `security_constraints` — règles de sécurité permanentes
- `interactions` — échanges passés pour contexte cross-conversation

**Embeddings** : fastembed (all-MiniLM-L6-v2), local, CPU-friendly, 384 dimensions

### 5. Sécurité

Voir [security.md](security.md) pour le détail complet.

## Flux d'un message

1. L'utilisateur envoie un message via un canal (Web, Telegram...)
2. Le canal authentifie l'utilisateur et route le message vers l'agent
3. Le `SecurityFilter` anonymise les données sensibles (PII)
4. L'historique de conversation est chargé depuis SQLite
5. L'`agent_node` reçoit : system prompt + contraintes Qdrant + mémoires + historique + message
6. Le LLM décide s'il répond directement ou appelle un outil
7. Si outil : le `tool_node` vérifie si HITL est requis, injecte les credentials, exécute
8. La réponse est dé-anonymisée et renvoyée au canal
9. L'interaction est stockée dans Qdrant pour enrichir la mémoire
10. À la déconnexion, la conversation est résumée en mémoire long terme

## Configuration

| Source | Priorité | Usage |
|---|---|---|
| `system_config` (DB) | 1 (plus haute) | OAuth credentials, config runtime |
| `.env` | 2 | Clés API, URLs, paramètres serveur |
| `config.py` defaults | 3 (fallback) | Valeurs par défaut |
