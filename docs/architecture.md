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

---

## Missions Loop — Goal-Driven Persistence

Au-delà du modèle requête-réponse standard, ELY embarque un agent
**goal-driven** capable de poursuivre une mission long-terme à travers
plusieurs itérations qui survivent aux redémarrages.

### Boucle Plan → Act → Eval → Replan

```
                    ┌─── HEARTBEAT (every 10s) ───┐
                    ▼                              │
            ┌────────────┐    ┌──────┐    ┌─────┐ │
            │   Plan     │───►│ Act  │───►│Eval │─┤
            └────────────┘    └──────┘    └──┬──┘ │
                  ▲                          ▼    │
                  │       ┌────────┐    ┌─────────┴───┐
                  └───────│ Replan │◄───│ ≥3 failures │
                          └────────┘    └─────────────┘
```

Chaque mission a son propre `thread_id` LangGraph et son state est
persisté dans `data/missions_checkpoints.sqlite` via
`AsyncSqliteSaver`. Quand le heartbeat revient sur une mission au tick
suivant, l'état est restauré exactement où on l'a laissé.

### Composants principaux

| Module | Rôle |
|---|---|
| `app/models/mission.py` | Modèles SQLAlchemy : `Mission`, `MissionPlan` (versionné), `MissionStep` (audit trail). |
| `app/services/mission_service.py` | CRUD + transitions de status atomiques (draft→planning→running→completed/failed/aborted). |
| `app/services/mission_heartbeat.py` | APScheduler interval job (10 s par défaut). Pour chaque beat : lock async, query `list_due_missions()`, 1 tick par mission, dispatch notifications de fin. |
| `app/agent/missions/checkpointer.py` | Singleton `AsyncSqliteSaver` ouvert au boot, fermé au shutdown. |
| `app/agent/missions/state.py` | `MissionState` (TypedDict) avec reducer `add_messages`. |
| `app/agent/missions/graph.py` | Topology LangGraph (nodes + routes conditionnelles). |
| `app/agent/missions/nodes.py` | Implémentation réelle des nodes Plan/Act/Eval/Replan + helper `dispatch_tool` (HITL + vault + credentials). |
| `app/routers/missions.py` | REST API : POST/GET `/api/missions`, `/steps`, `/plan`, `/start`, `/pause`, `/abort`, `/tick`. |

### Garde-fous (5)

Une mission ne peut pas tourner indéfiniment. Cinq limites sont
contrôlées à chaque tick :

1. **Budget tokens** — par défaut 50 000, configurable à la création
2. **Budget itérations** — par défaut 30 ticks, configurable
3. **Deadline** (optionnelle) — kill à un timestamp absolu
4. **HITL** sur outils critiques (mail, file delete, SSH…) — réutilise
   l'infrastructure HITL du chat mode (web pop-up + ntfy push)
5. **Anti-boucle** — 3 échecs consécutifs déclenchent un `replan_node`
   qui produit une nouvelle version du plan en réfléchissant à ce qui
   a foiré

### Sources de goals

| Source | Comment |
|---|---|
| Web UI | `/missions` → bouton "Nouvelle mission" → modal titre + goal + budgets |
| Telegram | Commande `/mission <titre> :: <goal>` en DM avec le bot |
| Scheduled tasks | (à venir) Une scheduled task peut créer + démarrer une mission récurrente |
| Autonomous | (futur) L'agent se fixe ses propres goals à partir du `UserProfile` |

### Notifications de fin (3 canaux parallèles)

Quand une mission termine (`completed` / `failed` / `aborted`), le
heartbeat dispatche en parallèle :

1. **Web UI** — message persisté dans une conv auto-créée
   `[Missions] Notifications` (visible sidebar Chat)
2. **Telegram DM** — uniquement si la mission a été créée via Telegram
   (`source_ref` commence par `telegram:`)
3. **ntfy** — push notif sur téléphone si `NTFY_URL` est configuré

Chaque canal est isolé : l'échec d'un n'arrête pas les autres.

### Routing LLM par mission

Les nodes utilisent les tiers de routing standard ELY :

| Node | Tier | Modèle typique |
|---|---|---|
| `plan_node` | `medium` | xLAM-2 8B / Qwen API (raisonnement structuré) |
| `act_node` | `medium` | xLAM-2 8B (function calling, fallback Gemini si échec) |
| `eval_node` | `medium` | xLAM-2 / Qwen (judgment) |
| `replan_node` | `medium` | xLAM-2 / Qwen (réflexion sur l'échec) |

Le filtre dynamique de tools (`_filter_tools_for_step` dans
`nodes.py`) réduit l'inventaire de 151 → ~10-15 tools selon le `tool_hint`
du plan + keywords du goal, pour rester sous les limites de payload des
modèles locaux 8B.
