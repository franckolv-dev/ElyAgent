# ELY Agent — Architecture

> *Dernière mise à jour : 2026-05-10. Reflète la stack actée pour l'ouverture publique semaine du 11 mai 2026.*

ELY (Exactly Like You) est un **agent IA personnel souverain**, multi-canal, multi-LLM, avec capacité d'action sur le système de fichiers local de l'utilisateur. Cette page décrit l'architecture en mai 2026 — les choix faits, leurs raisons, et où trouver le code.

---

## 1. Vue d'ensemble

```
                           CANAUX D'ENTRÉE
   ┌─────────────────────────────────────────────────────────────────┐
   │  Web UI (Next.js)   App Android (Kotlin)   App iOS (SwiftUI)    │
   │  Telegram bot       Discord bot            Slack Socket Mode    │
   │  WhatsApp Web/Cloud Voice WS (/ws/voice)                        │
   └────────────┬────────────────────────────────────────────────────┘
                │ JWT + WebSocket / HTTP
                ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                    BACKEND (FastAPI / Python)                   │
   │                                                                 │
   │   ┌──── Auth + Rate limit + CORS ──────────────────────────┐   │
   │   │                                                        │   │
   │   │   ┌── Security ───────────────────────────────────┐    │   │
   │   │   │  PII anonymizer • HITL multicanal             │    │   │
   │   │   │  ALWAYS_CRITICAL_TOOLS • LOCKED_HITL_TOOLS    │    │   │
   │   │   │  Anti-confabulation (system prompt)           │    │   │
   │   │   └────────────────────────────────────────────────┘    │   │
   │   │                                                        │   │
   │   │   ┌── Agent (LangGraph supervisor) ──────────────┐    │   │
   │   │   │  router → {research|workspace|infra|general} │    │   │
   │   │   │   → tools → loop, force_summary at iter≥80   │    │   │
   │   │   │  Sticky toolset profile (~41 tools)          │    │   │
   │   │   └────────────────────────────────────────────────┘    │   │
   │   │                                                        │   │
   │   │   ┌── LLM routing (4 tiers) ─────────────────────┐    │   │
   │   │   │  A:Ministral 3B local · B:Mistral Small 4    │    │   │
   │   │   │  C:Mistral Large 3 · IMG:DeepSeek v4-flash   │    │   │
   │   │   │  Fallback chain transparent                  │    │   │
   │   │   └────────────────────────────────────────────────┘    │   │
   │   └────────────────────────────────────────────────────────┘   │
   └────────┬──────────────────┬─────────────────┬────────┬─────────┘
            │                  │                 │        │
            ▼                  ▼                 ▼        ▼
  ┌──────────────┐  ┌──────────────────┐  ┌─────────┐  ┌──────────────┐
  │   SQLite     │  │   Qdrant         │  │ Google  │  │ ELY Desktop  │
  │              │  │   (Vector DB)    │  │  APIs   │  │ daemon (Go)  │
  │ users        │  │  memories        │  │ Gmail   │  │ filesystem   │
  │ messages     │  │  constraints     │  │ Calendar│  │ sandbox      │
  │ convos       │  │  interactions    │  │ Drive   │  │ HITL forced  │
  │ llm_instances│  │  user_profile    │  │ Docs    │  │ on writes    │
  │ missions     │  │                  │  │ Sheets  │  │              │
  │ hitl_prefs   │  │  fastembed local │  │ Tasks   │  │ WebSocket    │
  │ scheduled    │  │  (CPU, 384 dim)  │  │ People  │  │ /ws/desktop  │
  └──────────────┘  └──────────────────┘  └─────────┘  └──────────────┘
```

---

## 2. Frontend — Next.js + 3D avatar

📁 `frontend/`

- **App Router Next.js 14+**, pages `/chat`, `/settings`, `/admin`, `/dashboard`, `/missions`, `/arena`, `/login`, `/offline`
- **i18n** via `next-intl` (FR par défaut, EN dispo) — fichiers `frontend/messages/{fr,en}.json`
- **WebSocket** `/ws/chat` avec reconnexion automatique pour le chat temps réel
- **Avatar 3D cyberpunk** (Three.js / react-three-fiber) — états `idle`, `thinking`, `speaking`, `alert` (HITL)
- **TTS client** (`lib/tts.ts`) — appelle `/tts/speak` avec sanitizer côté serveur (URLs, JSON, IDs longs filtrés). Toggle « Voix active » persisté par utilisateur via `/api/preferences/voice`
- **HITL** : double canal — carte sur l'avatar (WebSocket `hitl_pending`) **et** push ntfy → résolu en cliquant l'un ou l'autre
- **PWA** : manifest + service worker `sw.js` (production uniquement, network-first sur les navigations, jamais de cache pour `/api/*` ni `/ws/*`)
- **Mode sombre/clair**, thème cyan-cyberpunk

---

## 3. Backend — FastAPI

📁 `backend/`

- **API REST + WebSocket**, FastAPI + uvicorn
- **Auth** JWT access (15 min) + refresh cookie HttpOnly (30 j) — admin via rôle `admin` sur `User`
- **Rate limiting** (60 req/min/IP), **CORS** configurable
- **Routers** principaux :
  - `auth`, `chat` (WS), `voice` (WS), `validation` (HITL resolve), `tts`
  - `google` (OAuth flow), `setup`, `licence`, `arena`
  - `settings_llm` (CRUD instances + tier routing), `voice_prefs`, `hitl_prefs`
  - `desktop_status` / `desktop_config` / `desktop_binaries`, `desktop_ws` (daemon connection)
  - `missions`, `scheduler`, `watchdog`, `audit`, `analytics`
  - `attachments`, `upload`, `transcribe`
  - Channel webhooks : `telegram_webhook`, `whatsapp_webhook`
- **Database** : SQLite (idempotent migration au boot via `_safe_columns` dans `database.py` — pas d'Alembic)

---

## 4. Agent — LangGraph + Supervisor multi-agent

📁 `backend/app/agent/`

### Topology

```
           ┌─────────────┐
           │   router    │  classifie le domaine via IntentRouter
           └──────┬──────┘
                  │
       ┌──────────┼──────────┐
       │          │          │       │
       ▼          ▼          ▼       ▼
  ┌────────┐ ┌─────────┐ ┌──────┐ ┌────────┐
  │research│ │workspace│ │infra │ │general │
  └───┬────┘ └────┬────┘ └──┬───┘ └───┬────┘
      │           │         │         │
      └───────────┴─────────┴─────────┘
                  │
                  ▼
           ┌────────────┐
           │   tools    │ exécute, avec HITL si critique
           └─────┬──────┘
                 │
                 ▼
           ┌─────────────────┐
           │ should_continue │
           └──┬──────────┬───┘
              │          │
              │          ▼
              │   ┌────────────────┐
              │   │ force_summary  │ si iter≥80
              │   └───────┬────────┘
              │           ▼
              │         END
              │
              ▼
              loop back to specialist
```

### Spécialistes (`supervisor.py`)

- **research** : `web_search`, `browser_*`, `weather_get`, `news_*`, `translate_text`
- **workspace** : Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts (~50 outils Google)
- **infra** : SSH, cron, watchdog, briefing
- **general** : tous les outils (cross-domaine)

Le routeur (`IntentRouter`) classifie chaque message et envoie vers le bon spécialiste. Si le score d'intent est ambigu, fallback sur `general`.

### Sticky toolset profile (Hermes Chantier 1)

📁 `agent/toolset_profiles.py`

Au lieu de filtrer dynamiquement les outils par mots-clés (technique abandonnée pour le chat), chaque conversation a un **profile sticky** stocké dans `conversations.toolset_profile` :

- `default` : ~41 tools curés à la main couvrant 80% des workflows quotidiens (mail + calendar + drive + browser + desktop + memory + tasks)
- Profile détecté à la 1re message, persisté pour toute la conversation
- Avantages : **prompt cache** byte-stable, **muscle memory** des LLM, pas de tool-blindness sur les petits modèles

Les missions, elles, utilisent un filtrage dynamique par mots-clés (`missions/nodes.py`) — différent des conversations chat car chaque step est isolée.

### Iteration budget + force_summary (Hermes Chantier 9)

📁 `agent/nodes.py`

Sur les workflows lourds (audit 30 j de mail, drive_find_duplicates), le compteur `iteration_count` dans `AgentState` incrémente à chaque tour avec tool_calls. Quand il atteint `MAX_AGENT_ITERATIONS = 80`, `should_continue` route vers un nœud terminal `force_summary` qui fait **un dernier appel LLM sans tools** et conclut en texte. Garantit que l'utilisateur reçoit toujours une sortie même sur les tâches qui dépasseraient le `recursion_limit=100` de LangGraph.

### Anti-confabulation (system prompt, 2026-05-09)

📁 `agent/nodes.py:_SYSTEM_PROMPT_BASE` et `_SYSTEM_PROMPT_SLM`

Règle inviolable injectée dans tous les system prompts :

> Si un tool retourne 0 résultat, dire « Je n'ai trouvé aucun élément correspondant ». **Jamais** de liste fabriquée. Si pas de tool appelé pour une info factuelle, demander à l'utilisateur ou dire « je n'ai pas l'information ».

Garantit la fiabilité du discours sur des actions destructives. Ajoutée après l'incident Mistral Medium 3.5 qui inventait 7 événements de calendrier sur un calendrier vide (2026-05-09).

---

## 5. Stack LLM — routage par tier

📁 `backend/app/services/llm_provider.py` + `agent/intent_router.py`

### 4 tiers, chacun avec sa chaîne de fallback transparent

| Tier | Primary | Fallback 1 | Fallback 2 | Latence typique |
|---|---|---|---|---|
| **A — Simple** | Ministral 3B (MLX local) 🇪🇺 | Ministral 14B local | Mistral Small 4 | **~2 s** |
| **B — Standard** | Mistral Small 4 (API) 🇪🇺 | DeepSeek v4-flash 🇨🇳 | Anthropic Haiku | ~10-15 s |
| **C — Complex** | Mistral Large 3 (API) 🇪🇺 | DeepSeek v4-pro 🇨🇳 | Anthropic Sonnet | ~30 s |
| **IMG — Vision** | DeepSeek v4-flash (API) 🇨🇳 | Mistral Small 4 🇪🇺 | Mistral Large 3 🇪🇺 | ~20 s |

**Pitch souverain** : *3 tiers sur 4 en Europe par défaut*. Tier IMG sur DeepSeek pour la performance vision (3-4× plus rapide que Mistral). Mode « 100 % EU strict » planifié post-lancement (toggle UI qui pousse Mistral en primary IMG).

### Fallback chain transparent (Hermes Chantier 4)

📁 `backend/app/services/fallback_manager.py`

Quand un provider échoue (timeout, 4xx/5xx, hallucination détectée par `H-1`), le `fallback_manager` bascule **sticky par conversation** sur le suivant de la chaîne. L'utilisateur ne voit qu'un toast `provider.switched` discret. Le state `chain_pos` survit le temps de la conv pour ne pas réessayer le primary tombé en panne à chaque tour.

### Modèles supportés

📁 `settings_llm.py:_PROVIDER_IDS`

`mistral`, `deepseek`, `anthropic`, `openai`, `google` (Gemini), `moonshot`, `zhipu`, `ollama` (local), `lm_studio` (local), `openrouter`, `xai` (Grok). L'utilisateur configure des **instances** en UI (Paramètres → Modèles IA), avec **edit-in-place** (icône ✏️) pour rotation de clés API sans recréer.

### Bug fix DeepSeek v4-flash thinking-mode

DeepSeek v4-flash et v4-pro ont thinking ON par défaut, ce qui casse le multi-tour avec tool_calls (HTTP 400 « reasoning_content must be passed back »). Fix automatique : `extra_body={"thinking": {"type": "disabled"}}` injecté pour ces modèles. Voir `_deepseek_extra_body()` dans `llm_provider.py`.

---

## 6. ELY Desktop — daemon local Go

📁 `desktop/`

Petit binaire Go (~5 MB) que l'utilisateur lance sur son Mac/PC/Linux. Se connecte au backend via WebSocket `/ws/desktop` avec un token JWT signé valide 30 j. Donne à l'agent un accès **sandboxé** au système de fichiers local.

### Architecture daemon

| Module | Rôle |
|---|---|
| `main.go` | Entry point, version injectée via `-ldflags -X main.version=v1.1.0+<sha>` |
| `config.go` | Charge `ely-config.json` (URL backend + token + user_id) |
| `filesystem.go` | 9 outils : `list_dir`, `read_file`, `write_file`, `move_file`, `delete_file`, `create_dir`, `stat_file`, `hash_file`, `search_files`. Sandbox via `validatePath()` qui résout symlinks et bloque toute sortie des dossiers autorisés. Expand `~` vers `$HOME` au boot ET sur chaque request |
| `browser.go` | (futur) contrôle de navigateur local |
| `input.go` | (futur) automation OS |

### Outils côté backend

📁 `agent/tools/desktop_tool.py` (via `desktop_skill.py`)

- 5 read-only : `desktop_list_dir`, `desktop_read_file`, `desktop_search_files`, `desktop_stat_file`, `desktop_hash_file`
- 4 destructifs : `desktop_write_file`, `desktop_move_file`, `desktop_delete_file`, `desktop_create_dir` — **tous dans `LOCKED_HITL_TOOLS`** (HITL non désactivable)

Le daemon vérifie sa connexion via `desktop_registry.is_connected(user_id)` avant chaque tool call. Si déconnecté, le tool retourne un message clair plutôt qu'une erreur opaque.

### Configuration UI

Paramètres → Intégrations → ELY Desktop : badge connecté/déconnecté, liste des répertoires autorisés (saisie libre + chips raccourcis `~/Documents`, `~/Downloads`, `~/Desktop`, `~/Pictures`), téléchargement du `ely-config.json` et des binaires pré-buildés.

### Capacité fichiers locaux côté Android

📁 `android/app/src/main/kotlin/com/ely/agent/core/files/`

L'app Android n'a **pas** de daemon. Mais elle expose un écran natif « Gestionnaire de fichiers » (`FileManagerRepository`, `FileHashing`) qui scanne via Storage Access Framework et permet scan + dedup + delete en UI. **Pas connecté au chat agent** — c'est une feature standalone à intégrer post-lancement (piste UX : bouton « demander à Ely d'analyser »).

---

## 7. Mémoire

### Court terme — SQLite

`messages` table : 40 derniers messages chargés depuis SQLite à chaque message pour le contexte de tour.

### Long terme — Qdrant (vectoriel)

3 collections principales interrogées par similarité sémantique au début de chaque message :

| Collection | Contenu | Source |
|---|---|---|
| `memories` | Faits durables (« Franck habite à Paris », « préfère le format markdown ») | Extraits par un LLM silencieux à la déconnexion |
| `security_constraints` | Règles permanentes (« ne jamais envoyer à @x »). Signalé HITL « ban » → constraint persistée |
| `interactions` | Echanges passés sur des sujets similaires, pour le cross-conversation context |
| `user_profile` | Profil agrégé (nom, contexte, projets en cours) reconstruit en background |

**Embeddings** : `fastembed` (all-MiniLM-L6-v2), 384 dim, **local CPU**. Pas d'API embedding payante.

### Frozen memory snapshot (Hermes Chantier 2)

Au début d'une conversation, le backend construit un `FrozenMemorySnapshot` — bloc texte byte-stable contenant profil + contraintes + mémoires + interactions. Ce bloc est inséré dans le **préfixe cacheable** du system prompt. Sur Anthropic et Gemini, le prompt cache exploite cette stabilité pour des hits ~70-90% qui réduisent latence et coût.

---

## 8. Sécurité

### HITL (Human In The Loop) multicanal

📁 `services/hitl_manager.py`

Quand l'agent veut exécuter un tool dans `ALWAYS_CRITICAL_TOOLS`, le backend :

1. Suspend l'exécution
2. Dispatche en parallèle :
   - WebSocket `/ws/chat` → carte avatar magenta avec 3 boutons (Allow / Deny / Ban)
   - ntfy push → notification mobile avec actions HTTP signées (token JWT)
   - Telegram inline keyboard si linked
   - Discord DM avec emojis
   - FCM push pour app Android
3. Le **1er « allow »** sur n'importe quel canal débloque, les autres voient « Résolu »

Tools les plus sensibles dans `LOCKED_HITL_TOOLS` : non désactivables même par préférence utilisateur (`hitl_preferences` table). Couvre : Gmail trash batch, Drive delete, Calendar delete, Desktop write/move/delete/create_dir, SSH execute, Vault, raw API calls.

### Anonymisation PII

📁 `services/security_filter.py`

Avant l'appel LLM, les emails, numéros de téléphone, IBAN, etc. sont remplacés par des tokens (`[EMAIL_1]`, `[PHONE_2]`) via un registry per-conversation. Désanonymisé à la sortie. Évite que l'utilisateur leak ses données quand le LLM est cloud.

### Mode souverain

L'utilisateur peut configurer son routage en local-only (Tier A Ministral 3B suffit pour 80% des chats simples). Roadmap post-lancement : toggle « 100% EU strict » qui force Mistral sur tous les tiers (y compris IMG), au prix d'une latence vision 3-4× plus longue.

---

## 9. Outils dédiés serveur — pattern architectural

📁 `backend/app/agent/tools/`

**Principe** : quand un scénario nécessite > 10 tool calls successifs (recherche récursive, agrégation, analyse), coder un **outil serveur dédié** plutôt que de laisser le LLM orchestrer 30 appels.

3 cas livrés en mai 2026 :

| Tool | Remplace |
|---|---|
| `gmail_trash_by_category` | search + select + trash en boucle |
| `gmail_update_settings` | filter creation step-by-step |
| `drive_find_duplicates` | listing récursif + hash + grouping |

Bénéfices :
- 1 tool call au lieu de 30 → tractable pour Ministral 3B local comme pour Mistral Large 3
- 0 confabulation possible (le LLM ne fait que présenter le résultat)
- Pas de KV cache qui explose sur les contextes longs
- Latence prédictible (dépend du serveur, pas du LLM)

**À documenter quand on en ajoute un** : docstring claire avec « PREFER ce tool quand X », « DO NOT use quand Y », exemples de cas couverts/non couverts.

---

## 10. Missions Loop — agent goal-driven persistant

📁 `backend/app/agent/missions/`

Au-delà du chat requête-réponse, ELY embarque un agent capable de poursuivre une mission long-terme à travers plusieurs itérations qui survivent aux redémarrages.

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

Chaque mission a son propre `thread_id` LangGraph. State persisté dans `data/missions_checkpoints.sqlite` via `AsyncSqliteSaver`. Quand le heartbeat revient sur une mission au tick suivant, l'état est restauré exactement où on l'a laissé.

### Garde-fous (5)

1. **Budget tokens** — défaut 50 000, configurable
2. **Budget itérations** — défaut 30 ticks, configurable
3. **Deadline** absolue (optionnelle)
4. **HITL** sur outils critiques (réutilise l'infra HITL chat)
5. **Anti-boucle** — 3 échecs consécutifs → `replan_node`

### Routing LLM par mission

Les nodes utilisent les mêmes tiers que le chat (Mistral Small 4 / Large 3 selon la complexité du step). Filtrage dynamique de tools par mots-clés (`_filter_tools_for_step`) — 145 tools → ~10-15 par step pour rester sous les limites de payload des modèles locaux.

### Sources de goals

| Source | Comment |
|---|---|
| Web UI | `/missions` → bouton « Nouvelle mission » → modal titre + goal + budgets |
| Telegram | Commande `/mission <titre> :: <goal>` |
| Scheduled tasks | Une `scheduler_create_task` peut créer + démarrer une mission récurrente |

### Notifications de fin (3 canaux parallèles)

Web UI (conv auto-créée `[Missions] Notifications`) + Telegram DM (si source Telegram) + ntfy push. Chaque canal isolé, l'échec d'un n'arrête pas les autres.

---

## 11. Multi-canal

| Canal | Fichier backend | Notes |
|---|---|---|
| Web UI | `routers/chat.py` (`/ws/chat`) | JWT handshake, principal canal |
| Voice | `routers/voice.py` (`/ws/voice`) | STT → Agent → TTS en boucle, wake-word « Éli » |
| Telegram | `channels/telegram_bot.py` | HITL via inline keyboard, DM-first |
| Slack | `channels/slack_bot.py` | Socket Mode, Block Kit HITL |
| Discord | `channels/discord_bot.py` | DM + @mention, emoji HITL (✅/❌/🚫) |
| WhatsApp | `channels/whatsapp.py` + `whatsapp_web` | Webhook Twilio + WhatsApp Web Selenium pour les comptes perso |
| App Android | `android/` (Kotlin/Compose) | Native, FCM push HITL, chat + écran File Manager standalone |
| App iOS | `ios/` (SwiftUI, iOS 17+) | Chat + push HITL, voice mode |

---

## 12. Flux complet d'un message (récap)

1. **Canal** authentifie l'utilisateur, route le message vers `/ws/chat` ou équivalent
2. **PII anonymizer** masque les données sensibles (`[EMAIL_N]`)
3. **Frozen memory snapshot** construit ou rechargé depuis le cache de session
4. **Sticky profile** chargé pour la conv (~41 outils bound)
5. **Router** classifie le domaine → spécialiste correspondant
6. **LLM** primary du tier sélectionné (Simple/Standard/Complex/IMG) inférence
7. Si **fallback** (timeout, hallucination détectée par H-1, 4xx/5xx) → `fallback_manager` bascule sticky + toast `provider.switched`
8. Si **tool_call** : tool_node vérifie HITL (`ALWAYS_CRITICAL_TOOLS`), injecte credentials, exécute. HITL multicanal si nécessaire
9. Boucle agent → tool → agent jusqu'à `MAX_AGENT_ITERATIONS` (force_summary) ou réponse texte finale
10. **Réponse dé-anonymisée** renvoyée au canal d'origine
11. **Mémoire long terme** : interaction stockée dans Qdrant (collection `interactions`)
12. **À la déconnexion WS** : conversation résumée par un LLM silencieux et stockée dans `memories`

---

## 13. Configuration

| Source | Priorité | Usage |
|---|---|---|
| `system_config` (DB) | 1 (la plus haute) | OAuth credentials, tier_routing_config, runtime config |
| `llm_instances` (DB) | — | Instances LLM avec clés API stockées (chiffrées au repos) |
| `.env` | 2 | Clés API par défaut, URLs, paramètres serveur |
| `config.py` defaults | 3 (fallback) | Valeurs par défaut |

L'admin peut tout reconfigurer en UI sans redémarrer (sauf `.env` qui exige restart container).

---

## 14. Hôte de production

- **Mac Studio M1 Max, 32 GB RAM** (machine de l'auteur)
- VPS abandonné en 2026-05-07
- Domaine `ely.catalogmaker.fr` exposé via **Cloudflare Tunnel** (équivalent Snowflake)
- Tailscale pour l'admin/SSH

Cf. `infra_2026-05-07.md` (mémoire utilisateur) pour la décision et le détail.

---

## 15. Pour aller plus loin

| Document | Contenu |
|---|---|
| [security.md](security.md) | HITL, anti-confabulation, sandbox, anonymisation |
| [features.md](features.md) | Liste des capacités utilisateur |
| [SETUP_DESKTOP.md](SETUP_DESKTOP.md) | Installation du daemon ELY Desktop |
| [SETUP_GOOGLE.md](SETUP_GOOGLE.md) | OAuth Google |
| [SETUP_AI_PROVIDERS.md](SETUP_AI_PROVIDERS.md) | Config des providers LLM |

---

*Cette page est le point d'entrée canonique pour comprendre ELY. Elle est versionnée — chaque changement majeur d'architecture devrait synchroniser ce fichier dans le même commit.*
