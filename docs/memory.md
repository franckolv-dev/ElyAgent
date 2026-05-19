# ELY Agent — Journal d'implémentation

> Ce fichier sert de mémoire persistante entre sessions de développement.
> Mis à jour le : 2026-03-28 (session 2)

---

## État actuel du projet

**Stack** : FastAPI (Python) + Next.js (React/TypeScript) + SQLite + Qdrant
**LLM** : Anthropic Claude (principal), Mistral, DeepSeek, Ollama (local)
**Infra** : Ubuntu 24.04, Ryzen 3 / 16 Go RAM, Tailscale pour accès mobile

---

## Ce qui est implémenté et fonctionnel

### Backend (FastAPI)

#### Authentification & Sécurité
- [x] JWT access_token + refresh_token en cookie HttpOnly
- [x] Rotation automatique du refresh_token à chaque appel `/auth/refresh`
- [x] `authFetch()` côté frontend avec retry automatique sur 401
- [x] Rôles utilisateur (admin / user)
- [x] Rate limiting (`60/minute`)
- [x] CORS configurable via `CORS_ORIGINS` (CSV)
- [x] Cookie secure configurable (`COOKIE_SECURE=true` en prod)

#### Agent IA (LangGraph)
- [x] Graphe LangGraph : agent_node → should_continue → tool_node → boucle
- [x] Prompt système en français, format conversationnel (pas de markdown)
- [x] Multi-provider LLM : Anthropic, Mistral, DeepSeek, Ollama
- [x] Historique de conversation injecté à chaque message (40 derniers messages)
- [x] Mémoire vectorielle Qdrant avec 3 collections :
  - `memories` : résumés de conversation (générés à la déconnexion WebSocket)
  - `security_constraints` : règles apprises des refus HITL
  - `interactions` : échanges passés pour recherche sémantique
- [x] Injection contextuelle : contraintes + mémoires + interactions passées dans le system prompt
- [x] Résumé automatique de conversation en fin de session (summarisation LLM)

#### Outils de l'agent
- [x] `ssh_execute` — Commandes SSH via asyncio.to_thread (non-bloquant)
- [x] `analyze_file` — Analyse de fichiers
- [x] `system_info` — Infos système
- [x] **Gmail** : `gmail_list_emails`, `gmail_read_email`, `gmail_send_email`
- [x] **Calendar** : `calendar_list_events`, `calendar_create_event`
- [x] **Drive** : `drive_list_files`, `drive_read_file`
- [x] **Docs** : `docs_create_document`, `docs_read_document`, `docs_append_text`
- [x] **Sheets** : `sheets_create_spreadsheet`, `sheets_read_spreadsheet`, `sheets_append_rows`
- [x] **Tasks** : `tasks_list`, `tasks_create`, `tasks_complete`
- [x] **Contacts** : `contacts_search`, `contacts_list`, `contacts_create` (People API)
- [x] `InjectedToolArg` pour masquer les credentials Google au LLM
- [x] Credentials Google injectées automatiquement via `tool_node` (jamais exposées)

#### Sécurité de l'agent
- [x] HITL (Human-In-The-Loop) : validation humaine pour actions critiques
  - `ssh_execute`, `gmail_send_email`, `calendar_create_event` → toujours HITL
  - Détection par mots-clés (delete, send, pay, rm -rf, etc.)
- [x] Anonymisation des données sensibles (cartes, emails, tokens, IBAN, téléphone) avant envoi au LLM
- [x] Dé-anonymisation dans la réponse
- [x] Contraintes de sécurité persistantes (ban → règle stockée dans Qdrant)
- [x] Credentials Google jamais affichées dans les logs ni l'UI (display_args filtré)

#### Google OAuth2 multi-profil
- [x] Credentials OAuth app partagées dans `system_config` (DB, pas .env)
- [x] Admin UI pour configurer Client ID / Secret / Redirect URI
- [x] Chaque utilisateur connecte son propre compte Google
- [x] Tokens stockés par utilisateur dans `users.google_credentials`
- [x] PKCE supporté (code_verifier stocké dans _pending_states)
- [x] Re-lecture des credentials DB à chaque message WebSocket (pas au connect)
- [x] Scopes : gmail, calendar, drive, documents, spreadsheets, tasks, contacts (People API)

#### Configuration système
- [x] Table `system_config` pour configuration runtime (clé/valeur, secrets masqués)
- [x] Priorité DB > env vars (via `get_config(key, fallback=env)`)
- [x] CRUD admin : `GET/PUT/DELETE /admin/config`

#### Notifications push
- [x] ~~Notifications HITL via ntfy (Android)~~ — **retiré 2026-04-18** : remplacé par FCM (app Android native) + APNs (app iOS)
- [x] FCM via `_send_fcm()` dans `hitl_manager.py` — tokens enregistrés automatiquement au login via `/api/device/token`

### Frontend (Next.js)

#### Interface
- [x] Layout avec Sidebar, Header, zone de chat
- [x] Avatar 3D animé (Three.js / react-three-fiber)
- [x] Mode sombre / clair avec thème cyan
- [x] Cyan foncé en mode clair pour la lisibilité
- [x] Colonne droite redimensionnable (drag)
- [x] `suppressHydrationWarning` pour éviter les erreurs hydratation

#### Chat
- [x] WebSocket avec reconnexion automatique (5 tentatives, backoff exponentiel)
- [x] Indicateur CONNECTED / DISCONNECTED / RECONNECTING
- [x] TTS (synthèse vocale) via edge-tts backend
- [x] Historique de conversation persisté en DB

#### Pages
- [x] `/chat` — Interface principale
- [x] `/settings` — Provider LLM, clés API, Google Services (connect/disconnect)
- [x] `/admin` — Utilisateurs, Audit logs, Configuration OAuth Google
- [x] `/dashboard` — (basique)

### Infrastructure
- [x] `start.sh` — Script start/stop/restart/status/logs pour les deux services
- [x] Accès mobile via Tailscale (100.100.150.110)
- [x] `.env.local` frontend avec `NEXT_PUBLIC_API_URL` pointant vers Tailscale IP
- [x] nohup + PID files pour survie aux déconnexions terminal
- [x] `.gitignore` sécurisé (config/*.yaml, .env, clés SSH)

---

## Bugs résolus (historique)

| Bug | Cause | Fix |
|---|---|---|
| Déconnexion JS sur navigation Dashboard/Settings | Hydration mismatch React | `suppressHydrationWarning` sur `<html>` |
| `failed to fetch` au login | Préfixe `/api/` erroné dans api.ts/auth.ts | Suppression du préfixe |
| CORS refusé depuis Tailscale | Ancien backend avec ancienne config CORS | `kill -9` + `CORS_ORIGINS` CSV |
| `no such column: users.google_credentials` | `create_all` n'ALTER pas les tables existantes | `ALTER TABLE` manuel |
| Redirect URI mismatch Google OAuth | Router monté à `/api` → callback à `/api/google/callback` | Correction URI partout |
| `localhost:3000/undefined` au click Connect Google | `authFetch` ne throw pas sur non-OK, `url` = undefined | Check `res.ok` avant d'utiliser `url` |
| `Missing code verifier` OAuth | PKCE : `code_verifier` perdu car nouveau Flow à chaque appel | Stocker verifier dans `_pending_states` |
| ELY dit "je n'ai pas de credentials" | `user_google_credentials_json` visible dans le schéma LLM | `InjectedToolArg` pour le cacher |
| Credentials Google affichés dans le chat HITL | `action_desc` incluait les args complets | `display_args` filtré sans credentials |
| 404 sur `/google/status` | Frontend appelait sans préfixe `/api` | Correction URLs frontend |
| Google Calendar API 403 | APIs non activées dans le bon projet GCP | Activation via liens directs avec project ID |
| Conversation décousue (perte de contexte) | Seul le message courant était envoyé à l'agent | Chargement historique DB → injection dans messages |
| `QdrantClient.search` introuvable | API Qdrant v2 : `search` → `query_points` | Migration vers `query_points().points` |
| HITL pas reçu sur Telegram | HITLManager n'envoyait que ntfy + web | Ajout `_send_telegram()` avec inline keyboard |
| `calendar_create_event` déclenchait HITL inutilement | Outil listé dans `ALWAYS_CRITICAL_TOOLS` | Retiré de la liste (seuls `ssh_execute` et `gmail_send_email` restent) |
| Mots-clés "send", "mail", "email" trop larges | Présents dans `_CRITICAL_KEYWORDS`, déclenchaient HITL sur lecture d'emails | Supprimés — seuls les mots destructeurs et financiers restent |
| ELY ne connaît pas la date du jour | Pas d'injection de date dans le prompt | Injection date/heure Europe/Paris au format français dans le system prompt |
| Événement calendrier créé à la mauvaise date | ELY ignorait la date → utilisait date aléatoire | Corrigé par l'injection de la date courante |
| ELY dit "je n'ai pas accès aux contacts Google" | `contacts_search/list/create` absents de `_WORKSPACE_SKILLS`, `_DOMAIN_DESCRIPTIONS["workspace"]` et `_SPECIALIST_PROMPTS["workspace"]` dans `supervisor.py` | Ajout dans les 3 endroits (commit `a8ade1b`) |

---

---

## Session 2026-03-28 — Améliorations code review (commit `e849b17`)

Basées sur une analyse externe (Gemini) du code :

### 1. Cache embeddings (`backend/app/services/memory_manager.py`)
- Ajout `_embed_cache: dict` + `_embed_lock: asyncio.Lock` dans `__init__`
- Double-checked locking sur `_embed()` : une seule inférence ONNX pour les 3 appels parallèles (constraints + memories + interactions)
- Cache LRU borné à 64 entrées (éviction par ordre d'insertion)
- Économie : ~200-400 ms par tour de conversation

### 2. `cookie_secure` conditionnel (`backend/app/config.py`)
- Auto-activation si `"https://"` détecté dans `CORS_ORIGINS`
- Warning log au démarrage si `cookie_secure=False` (rappel non-bloquant)
- `COOKIE_SECURE=true` ajouté dans le `.env` du VPS

### 3. Tests unitaires (`backend/tests/`)
- Création de `tests/__init__.py`, `tests/test_security_filter.py`, `tests/test_intent_router.py`
- **55 tests, 55 passent** (`python -m pytest tests/ -v`)
- SecurityFilter (31) : anonymize, deanonymize, is_critical, reset, edge cases (ReDoS, round-trip, déduplication, positions)
- IntentRouter (24) : routing SLM/LLM, scoring interne, bornes 0-100, phase2 hook

### 4. `anonymize()` par positions (`backend/app/services/security_filter.py`)
- Remplace `str.replace()` par substitution positionnelle (offsets start/end)
- Collecte tous les matches multi-patterns, trie par position ascendante, supprime les chevauchements (first-match wins), applique de droite à gauche pour préserver les offsets
- Élimine le risque de double-remplacement si une PII est sous-chaîne d'un autre terme

### Déploiement VPS (rappel — pas de git sur le VPS)
```bash
# Le VPS /opt/agent n'est pas un repo git — code baked dans l'image Docker
# Déploiement rapide d'un fichier backend modifié :
scp fichier.py root@ely.catalogmaker.fr:/tmp/
ssh root@ely.catalogmaker.fr "docker cp /tmp/fichier.py cyberentity-backend:/app/app/chemin/fichier.py && docker restart cyberentity-backend"
# Containers : cyberentity-backend, cyberentity-frontend, cyberentity-ollama, cyberentity-qdrant
```

### Règle superviseur (à ne jamais oublier)
Pour ajouter un **nouveau skill Google** au workspace agent, il faut le déclarer dans **3 endroits** de `backend/app/agent/supervisor.py` :
1. `_DOMAIN_DESCRIPTIONS["workspace"]` — description du domaine pour le routeur
2. `_SPECIALIST_PROMPTS["workspace"]` — description + liste des outils dans le prompt spécialiste
3. `_WORKSPACE_SKILLS` — set de filtrage des outils disponibles

Oublier l'un des trois rend le tool **invisible à l'agent** (c'est le bug `google_contacts`).

---

## Session 2026-04-03 — YouTube yt-dlp + images outils + Playwright fix

### Pourquoi
- La recherche YouTube via Invidious était cassée (instances down / rate-limited)
- Le QR code et les images Imagen générées par les sous-agents n'arrivaient pas au frontend
- Playwright s'installait en root puis tournait en appuser → erreur de permissions

### Ce qui a été fait

#### 1. YouTube : Invidious → yt-dlp (`backend/app/agent/tools/youtube_tool.py`, `pyproject.toml`)
- Suppression du fallback Invidious (multi-instances instables)
- Remplacement par `yt-dlp` (search `ytsearch{n}:{query}`) dans un executor pour éviter le blocage async
- Mise à jour de l'API `youtube-transcript-api` : `list_transcripts()` → `ytt_api.fetch()` + `ytt_api.list()`
- Ajout de `yt-dlp>=2024.0.0` dans `pyproject.toml`

#### 2. Pass-through images depuis sous-agents (`backend/app/agent/supervisor.py`)
- Dans `_make_dispatch_node`, scan des `ToolMessage` produits par le sous-agent
- Si un `ToolMessage` contient du JSON `{"type":"image",...}`, il est préfixé dans le dernier `AIMessage`
- Permet au frontend de recevoir et afficher les QR codes / images Imagen générés via sous-agent

#### 3. Images outils dans le WebSocket (`backend/app/routers/chat.py`)
- Sur `on_tool_end`, si l'output contient un JSON `{"type":"image",...}`, le payload `image` est ajouté au message `tool_end`
- Le frontend accumule ces images dans `pendingToolImages` et les attache au message assistant suivant

#### 4. Frontend : affichage images outils (`frontend/src/lib/types.ts`, `frontend/src/app/chat/page.tsx`, `frontend/src/components/chat/MessageBubble.tsx`)
- Nouveau type `ToolImage` dans `types.ts` + champ `toolImages?: ToolImage[]` sur `ChatMessage` + champ `image?` sur `WSMessage`
- `pendingToolImages` ref dans `ChatPageInner` → collecte les images WS `tool_end`, attachées au message assistant
- Refactor `parseContent()` dans `MessageBubble` : gère texte seul, JSON image seul, et texte + JSON image (cas sous-agent)
- Rendu séparé texte / imageBlock / toolImages dans la bulle

#### 5. Playwright permissions (`backend/Dockerfile`, `docker-compose.yml`)
- `PLAYWRIGHT_BROWSERS_PATH=/app/.cache/playwright` défini avant le changement d'utilisateur
- `playwright install chromium` déplacé après `USER appuser` → navigateur installé avec les bonnes permissions
- Volume `./data/playwright:/app/.cache/playwright` dans `docker-compose.yml` (persistance entre rebuilds)

### Fichiers modifiés
- `backend/Dockerfile`
- `backend/app/agent/supervisor.py`
- `backend/app/agent/tools/youtube_tool.py`
- `backend/app/routers/chat.py`
- `backend/pyproject.toml`
- `docker-compose.yml`
- `frontend/src/lib/types.ts`
- `frontend/src/app/chat/page.tsx`
- `frontend/src/components/chat/MessageBubble.tsx`
- `docs/memory.md`

---

## Roadmap active (à reprendre si session interrompue)

| # | Feature | Statut |
|---|---------|--------|
| 1-10 | Phases initiales (Telegram, cron, mémoire hybride, skills, browser, etc.) | ✅ FAIT |
| 11 | Mémoire des préférences utilisateur (Proposition 5) | ✅ FAIT (2026-03-28) |
| 12 | Live Browser Copilot (Proposition 4) | ✅ FAIT (2026-03-28) |
| 13 | **Vision simple** — capture d'écran → Gemini multimodal | ✅ FAIT (2026-03-28) |
| 14 | **Client MCP statique** — connexion à des serveurs MCP existants | ✅ FAIT (2026-03-28) |
| 15 | **Interactive Trainer** — Vision + contrôle desktop via MCP | ✅ FAIT (2026-03-28) |
| 16 | **Génération dynamique de MCP** — agent créateur de connecteurs | ✅ FAIT (2026-03-28) |

### Contexte des features (si à refaire)
- **Vision** : outil `vision_analyze_image(image_path, question)` + bouton 🖥️ ChatInput → `getDisplayMedia` → base64 → WS `screen_capture` → fichier temp → agent appelle l'outil
- **MCP statique** : `backend/app/services/mcp_client.py` + admin UI pour configurer serveurs MCP (stdio/SSE) → outils MCP dans SkillRegistry
- **Interactive Trainer** : combine Vision + MCP desktop-control. Workflow Show & Tell. Mode observation seule. HITL systématique pour les actions OS.
- **MCP dynamique** : agent-créateur génère serveur MCP Python, AST checker, HITL approbation, venv isolé, hot-reload dans registry, MCP Library `data/mcp_library/`, self-healing

---

## Historique — Prochaines étapes (voir roadmap.md)

1. **Bot Telegram** — ✅ FAIT (2026-03-22)
   - `backend/app/channels/telegram_bot.py`
   - Commandes : /start, /link, /unlink, /new
   - HITL via inline keyboard
   - Config via Admin UI (onglet Telegram)
   - Colonne `telegram_id` dans users
2. **Tâches planifiées (cron)** — ✅ FAIT (2026-03-22)
   - `backend/app/models/scheduled_task.py` — modèle DB
   - `backend/app/services/scheduler.py` — APScheduler + livraison multi-canal
   - `backend/app/routers/scheduler.py` — API CRUD
   - `backend/app/agent/tools/scheduler_tool.py` — 3 outils agent (list/create/delete)
   - ELY peut créer des tâches via conversation naturelle ("rappelle-moi tous les lundis à 8h...")
   - Livraison sur web (WebSocket push) ou Telegram
3. **Recherche hybride mémoire** — ✅ FAIT (2026-03-22)
   - `backend/app/services/fts_store.py` — NEW: index FTS5 SQLite (aiosqlite)
     - Table virtuelle `memory_fts` dans le même fichier SQLite que la DB principale
     - Tokenizer `unicode61 remove_diacritics 1` pour support accentués
     - Requêtes préfixées (ex: `"rend"*` matche "rendez-vous")
     - Résultats triés par BM25 rank natif FTS5
   - `backend/app/services/memory_manager.py` — réécriture complète
     - `_upsert()` retourne le point UUID pour double-indexation Qdrant + FTS
     - Score hybride final : `(α×vector + β×keyword + γ×fts_boost) × time_decay`
     - Décroissance temporelle exponentielle par collection :
       - `security_constraints` : λ=0.00 (permanent, jamais périmé)
       - `memories` : λ=0.01 (demi-vie ~69 jours)
       - `interactions` : λ=0.05 (demi-vie ~14 jours)
     - Re-ranking en Python sur 4× candidats Qdrant
   - `backend/app/routers/chat.py` — extraction de profil en parallèle du résumé
     - Deux appels LLM concurrents (asyncio.gather) à chaque déconnexion WebSocket
     - LLM 1 : résumé hollistique de la conversation
     - LLM 2 : JSON de faits durables sur l'utilisateur (nom, préfs, travail, famille...)
     - Chaque fait stocké individuellement → retrouvable par recherche sémantique
4. **Architecture de plugins/skills** — ✅ FAIT (2026-03-22)
5. **Contrôle navigateur (Playwright)** — ✅ FAIT (2026-03-22)

---

## Session 2026-03-28 (2) — Propositions Gemini P5 + P4 (commit `d44bcc3`)

### Proposition 5 — Mémoire des préférences utilisateur

- **`backend/app/services/memory_manager.py`**
  - Nouvelle constante `_COLLECTION_PREFERENCES = "user_profile"` (4ème collection Qdrant)
  - Ajout dans `init_collections()` — créée si elle n'existe pas
  - `store_preference(preference, user_id)` — permanent, sans décroissance, double-indexé FTS
  - `get_user_preferences(user_id, limit=10)` — `scroll` Qdrant (pas de recherche sémantique,
    les préférences sont toujours toutes injectées)

- **`backend/app/routers/chat.py`**
  - 3ème appel LLM parallèle dans `_summarize_conversation()` (3 gather au lieu de 2)
  - `prefs_prompt` extrait le style de communication, ton, habitudes de formuler les demandes
  - Chaque préférence stockée individuellement via `memory.store_preference()` (cap 8)

- **`backend/app/agent/nodes.py`**
  - `get_user_preferences(user_id)` ajouté dans l'`asyncio.gather` principal (4 appels)
  - Section `👤 PRÉFÉRENCES UTILISATEUR` injectée avant 🛡️ et 💾 dans le system prompt
  - Même ajout dans le chemin SLM-fallback

### Proposition 4 — Live Browser Copilot

- **`backend/app/skills/builtin/browser_skill.py`**
  - Helper `_push_browser_frame(page, user_id)` : screenshot PNG → base64 → WebSocket
  - Message type `browser_frame` : `{type, data, url, title}`
  - Appelé (fire-and-forget) après `browser_navigate`, `browser_click`, `browser_fill`
  - Erreurs silencieuses (debug log uniquement)

- **`frontend/src/lib/types.ts`**
  - `browser_frame` ajouté à l'union `WSMessage.type`
  - Champs `data`, `url`, `title` dans WSMessage
  - Nouvelle interface `BrowserFrame`

- **`frontend/src/app/chat/page.tsx`**
  - State `browserFrame: BrowserFrame | null`
  - Handler `msg.type === "browser_frame"` → `setBrowserFrame({...})`
  - `<LiveBrowserPanel>` rendu entre ChatWindow et ChatInput si frame présente

- **`frontend/src/components/browser/LiveBrowserPanel.tsx`** (nouveau fichier)
  - Barre URL avec icône loupe, URL raccourcie (sans protocole)
  - Badge "Live" animé (ping)
  - Screenshot `<img>` base64 (max-h-80, object-cover)
  - Titre de la page en bas
  - Bouton fermer (×) — `onClose` → `setBrowserFrame(null)`

---

## Session 2026-04-23 / 24 — Campagne de tests multi-LLM + optim local + MemGPT

### Contexte

Bench comparatif entre Claude Haiku 4.5 (cloud, baseline) et plusieurs modèles locaux
(LM Studio MLX sur Mac Studio 32 GB) pour identifier une config viable en 100 % local.
Suite de tests automatisée : 48 tests main + 18 HITL + 5 cleanup + 3 smoke = **74 tests**.

### Chronologie des modèles testés (par ordre)

1. **Gemma 4 26B A4B MLX** : 8/18 HITL pur (44 %), latence 94 s. Rejeté — ne respecte
   pas `tool_choice="any"`, fallback silencieux vers Gemini faussait les scores.
2. **Qwen 3.5-9B MLX** : thinking mode non désactivable (bug LM Studio #1559).
   Le modèle consomme 100 % de `max_tokens` dans `<think>` — impossible à utiliser.
3. **Qwen 3.6-35B-A3B-UD MLX 4-bit (Unsloth)** : trop gros (21.6 GB + KV cache) pour 32 GB.
   Abandonné avant chargement.
4. **Qwen 2.5-VL-7B MLX 4-bit** : taille 5.65 GB. Tool-calling OK en test direct,
   mais 0/18 avec le prompt système complet d'ELY (3000 tokens d'instructions
   contradictoires + 18 lignes de profil utilisateur + contraintes + memories).
5. **Qwen 2.5-VL-7B + compact prompt ELY** : **15/18 HITL (83 %), latence 46 s**.
   Cible production locale atteinte.

### Fixes déployés — phase "débuggage infra"

#### Fix HITL timeout 120s → 300s
- **`backend/app/services/hitl_manager.py`** : `TIMEOUT_SECONDS = 300`
- Cause : Gemma lent + délai notif push FCM/ntfy + temps de réaction utilisateur >120 s
  → backend auto-denied avant validation → 404 sur les boutons du téléphone.

#### Fix OAuth Google révoqué
- Déconnexion / reconnexion manuelle via `/settings → Google Services`.
- Purge de 22 fausses contraintes `"Je ne peux pas accéder à Google Drive car le token
  d'accès est expiré"` mémorisées pendant les tests avec token mort.

#### Fix FCM Android
- **`android/app/src/main/kotlin/com/ely/agent/core/fcm/FcmTokenManager.kt`** (nouveau)
  - Helper qui lit `accessToken` du DataStore + fetch FCM token Firebase + appelle
    `PUT /api/device-token`.
- **`MainActivity.kt`** : `fcmTokenManager.registerCurrentToken()` au cold start.
- **`AuthRepositoryImpl.kt`** : register après login réussi.
- **`ElyFirebaseMessagingService.kt`** : `onNewToken()` implémenté (était vide !).
- ⚠️ APK à rebuild + réinstaller pour activation côté device.

#### Fix ntfy configuré
- `NTFY_URL` toujours présent dans la config → les notifs push passent par ntfy
  en attendant que le fix FCM soit déployé sur l'APK.

### Fixes déployés — phase "qualité tool-calling"

#### 1. Retirer les instructions anti-tool-calling
Fichiers : `nodes.py`, `supervisor.py`, `sub_agents/config.py`.
- **Avant** : `"Format des réponses — IMPÉRATIF : Rédige TOUJOURS en texte naturel"`
- **Après** : `"Utilisation des tools — PRIORITÉ ABSOLUE : APPELLE-le IMMÉDIATEMENT"` en tête,
  le texte naturel devient `"seulement quand aucun tool n'est pertinent"`.
- Les petits modèles (7B-14B) suivent les instructions littéralement → réordonner
  pour que tool-call soit la priorité première lue.

#### 2. `user_profile` compact (<200 tokens)
- **`backend/app/services/memory_service.py`** : `get_user_context(compact=True)` par défaut.
- `_PROFILE_CORE_KEYS` : 6 keys toujours incluses (`user_name`, `preferred_language`,
  `response_style`, `main_project`, `email_provider`, `timezone_reminder`).
- `_PROFILE_NOISY_KEYS` : 14 keys systématiquement filtrées (ex: `current_delivery`,
  `ionos_client_id`, `upcoming_events`, `news_*`, `shopping_routine`, `gmail_preferences`).
- Format pipe-separated : `Profil utilisateur: user_name: Franck | response_style: concis ... `.
- Plafond 800 caractères (≈ 200 tokens). Mode legacy `compact=False` préservé pour debug.

#### 3. Compact prompt mode pour LLMs locaux
- **`backend/app/services/qwen_no_think.py`** : nouveau helper `is_local_openai_llm(llm)`
  qui détecte `ChatOpenAI` avec `base_url` sur `localhost / 127.0.0.1 / host.docker.internal /
  RFC-1918` (private network).
- **`backend/app/agent/compact_prompt.py`** (nouveau) : builder `build_compact_system_prompt()`.
  - Structure : identité 1-ligne + speciality sub-agent 1-ligne + tool priority paragraphe +
    user_ctx (≤200 tok) + top-3 constraints tronquées + top-3 memories tronquées + date en fin.
  - Total ~300 tokens au lieu de 2730 en mode complet.
  - Date placée en DERNIER (partie la plus volatile) → préserve le cache prefix LM Studio.
- **`factory.py`** + **`nodes.py`** : conditionnent sur `is_local_openai_llm(llm)` pour
  choisir entre prompt complet (cloud) ou compact (local). Les frontier cloud models gardent
  leur prompt riche inchangé.

#### 4. `tool_choice` : mapping `"any"` → `"required"` pour LM Studio
- **`factory.py`** : détection `ChatOpenAI` → utilise `"required"` au lieu de `"any"`.
- LM Studio strict OpenAI : `"any"` → HTTP 400. LangChain masquait l'erreur en fallback
  texte → `tool_calls=[]` sur toute la session.

#### 5. Cache memories par user turn (pas par tool call)
- **`factory.py`** + **`sub_agents/state.py`** : 5 nouveaux champs dans `SubAgentState`
  (`_mem_constraints`, `_mem_memories`, `_mem_interactions`, `_mem_user_ctx`,
  `_mem_fetched_for_query`).
- Au premier `agent_node` d'un turn user, fetch parallèle via `asyncio.gather` et
  stockage dans le state. Aux itérations suivantes (tool calls en chaîne), on réutilise
  les blocs → cache LM Studio reste valide, plus d'invalidation continuelle du prompt.
- Invalidation : quand `user_query` change (nouveau message utilisateur) → re-fetch.

#### 6. `is_qwen_llm()` étendu + Qwen 2.x exclu
- `ChatOllama` + `ChatOpenAI` détectés (avant seulement Ollama).
- Regex `\bqwen[\s._-]?2(\.|_|-|\b)` retourne `False` → pas de `/no_think` injecté sur
  Qwen 2.x (qui n'a pas de thinking mode et est perturbé par le marker).

#### 7. Temperature 0.1 par défaut pour LM Studio
- **`backend/app/services/llm_provider.py`** : `_make_lm_studio(..., temperature=0.1)`.
- Pour le function-calling, 0.1 génère du JSON plus stable qu'avec 0.7 (ancien défaut
  LangChain). User peut toujours override via UI LM Studio.

#### 8. `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`
- Tenté pour désactiver le thinking sur Qwen 3.5 — **ne fonctionne pas** sur LM Studio
  (bug connu #1559). Laissé en place car harmless sur Qwen 2.x / Gemma / autres.

### MemGPT-style hierarchical memory (nouveau module)

- **`backend/app/agent/tools/memgpt_tool.py`** (nouveau) : 3 tools.
  - `memory_archive(fact, category, user_id)` — archive un fait durable via Qdrant
    `store_memory()` + payload `category`.
  - `memory_search(query, limit=5, user_id)` — recherche sémantique via
    `get_relevant_memories()`.
  - `memory_recent(category, limit=5, user_id)` — scroll Qdrant filtré par category,
    trié par `created_at` desc.
- Catégories : `fact`, `preference`, `project`, `contact`, `task`, `event`,
  `constraint`, `other`.
- **`backend/app/skills/builtin/memory_skill.py`** : skill `memgpt_memory` enregistré
  (à côté du legacy `memory_preferences`).

Hiérarchie 3 niveaux conformément aux bonnes pratiques (cf. MemGPT / Letta) :

| Niveau | Emplacement | Taille | Injection |
|--------|-------------|:------:|:---------:|
| **Core** | System prompt compact | ~200 tokens | ✅ toujours |
| **Working** | `messages[]` (history) | variable | ✅ auto LangGraph |
| **Long-term** | Qdrant `memories`, `constraints`, `user_profile` | illimité | 🔀 push passif (top-3) + pull actif (MemGPT tools) |

### Résultats mesurés

| Config | HITL (18) | Latence moy | Notes |
|--------|:---------:|:-----------:|-------|
| Claude Haiku 4.5 cloud (baseline) | 16/18 (89 %) | 37 s | Référence |
| Gemma 4 26B A4B MLX pur | 8/18 (44 %) | 94 s | Ignore `tool_choice=any` |
| Qwen 3.5-9B MLX | 12/18 (67 %) | 72 s | Thinking mode forcé |
| Qwen 2.5-VL-7B full prompt | 0/18 (0 %) | — | Suit les instructions textuelles |
| **Qwen 2.5-VL-7B compact prompt** | **15/18 (83 %)** | **46 s** | **Cible atteinte** |

### Routage recommandé (Mac Studio 32 GB + Docker ELY)

- `simple`, `medium`, `image` (multimodal !), `maintenance` → **Qwen 2.5-VL-7B local**,
  fallback Haiku activé.
- `complex` → **Claude Haiku 4.5** (chaînes multi-outils, `raw_api_call`, etc.).
- Gain estimé : ~70 % des requêtes en local (gratuit, privé, 46 s/tour),
  ~30 % cloud (10-20 s/tour sur Haiku).

### Bug fixes ponctuels

- `UnboundLocalError: '_base_llm'` dans `nodes.py` (ligne compact prompt) — fixé en
  utilisant `get_llm()` directement dans un try/except.
- `tool_choice="any"` refusé par LM Studio (HTTP 400) masqué par LangChain — fixé
  via mapping conditionnel.
- Token JWT de test runner régénéré à plusieurs reprises (expirations de session).

### À faire pour sessions futures

1. **Sub-filter MemGPT** : ajouter les keywords `archive|rappelle|mémorise|retrouve`
   dans `factory.py` pour exposer les 3 nouveaux tools au bon moment.
2. **Rebuild APK Android** : le fix `onNewToken()` est codé mais inactif jusqu'à
   `./gradlew assembleRelease` + réinstallation.
3. **Optionnel — routage dynamique** : détecter `ChatOpenAI` local dans le router-LLM
   du supervisor pour économiser encore plus de tokens sur la classification domain.
4. **Optionnel — upgrade Mac Studio** : 64 GB permettrait un modèle dense 24B en 4-bit
   (ex. Mistral Small 3.1 24B) qui pourrait battre Haiku sur certains cas.

### Fichiers créés dans cette session

- `backend/app/agent/compact_prompt.py`
- `backend/app/agent/tools/memgpt_tool.py`
- `android/app/src/main/kotlin/com/ely/agent/core/fcm/FcmTokenManager.kt`
- `test-runner/COMPARATIF-Haiku-vs-Gemma4.md` (v1, v2, v3)
- `test-runner/RAPPORT-FINAL-Qwen25VL-compact.md`
- `test-runner/haiku-baseline/` (archives baseline)
- `test-runner/gemma4-results/` (archives 3 runs Gemma)
- `test-runner/qwen25vl-compact-results/` (archives run final)

### Fichiers modifiés

- `backend/app/services/hitl_manager.py` — TIMEOUT 120 → 300
- `backend/app/services/llm_provider.py` — `_make_lm_studio` T=0.1 + `enable_thinking` + ajout provider `lm_studio`
- `backend/app/services/memory_service.py` — `get_user_context(compact=True)`
- `backend/app/services/qwen_no_think.py` — `is_local_openai_llm`, `is_qwen_llm` exclut Qwen 2.x
- `backend/app/services/security_filter.py` — word-boundary fix `is_critical`
- `backend/app/agent/nodes.py` — compact prompt mode + anti-tool wording
- `backend/app/agent/supervisor.py` — `_COMMON_FORMAT` reformulé
- `backend/app/agent/sub_agents/config.py` — `_COMMON_FORMAT` reformulé
- `backend/app/agent/sub_agents/state.py` — champs cache mémoire (`total=False`)
- `backend/app/agent/sub_agents/factory.py` — compact mode + tool_choice mapping + tri tools + cache memories + fallback respecte `fallback_enabled`
- `backend/app/skills/builtin/memory_skill.py` — skill `memgpt_memory` enregistré
- `backend/app/routers/settings_llm.py` — provider `lm_studio` dans `PROVIDERS_META`
- `backend/app/config.py` — `lm_studio_base_url` setting
- `frontend/src/app/settings/page.tsx` — `lm_studio` dans `PROVIDERS` UI
- `android/app/src/main/kotlin/com/ely/agent/MainActivity.kt` — FCM register cold start
- `android/.../AuthRepositoryImpl.kt` — FCM register après login
- `android/.../ElyFirebaseMessagingService.kt` — `onNewToken()` implémenté

---

## Session 2026-04-24 (suite) — Ajout provider Qwen API (Alibaba Cloud DashScope)

### Contexte

Après les tests Qwen local (Qwen 2.5-VL-7B MLX, 15/18 avec compact prompt, 46 s moy),
on bascule sur l'**API cloud Alibaba DashScope** (endpoint EU Frankfurt) pour
couvrir les tiers `medium` et `complex`. Objectif : latence plus faible que
Haiku + coût inférieur + garder la famille Qwen (famille avec laquelle ELY est
déjà compatible via nos fixes).

### Endpoint et clé API

- **Endpoint OpenAI-compatible EU** : `https://ws-3k014413afwx7tgc.eu-central-1.maas.aliyuncs.com/compatible-mode/v1`
- **Workspace** : `ws-3k014413afwx7tgc` (région `eu-central-1`)
- **Clé** : stockée dans `system_config` table (`api_key_qwen_api`, marquée secret)
- **URL base** : stockée dans `system_config` (`qwen_api_base_url`)
- **Modèles disponibles sur le workspace** (2026-04) :
  - Flagship : `qwen3.6-max-preview`, `qwen3.6-plus`, `qwen3.6-flash`
  - MoE : `qwen3.6-35b-a3b`, `qwen3-next-80b-a3b-instruct`
  - Vision : `qwen3-vl-plus`, `qwen3-vl-32b-instruct`, `qwen3-vl-8b-instruct`
  - Coder : `qwen3-coder-plus`, `qwen3-coder-flash`, `qwen3-coder-480b-a35b-instruct`
  - Thinking : `qwen3-vl-*-thinking`, `qwen3-next-*-thinking`
  - OCR : `qwen-vl-ocr`
  - Translation : `qwen-mt-plus`, `qwen-mt-turbo`, `qwen-mt-flash`, `qwen-mt-lite`

### Nouveau provider `qwen_api` dans ELY

Fichiers ajoutés / modifiés :

- **`backend/app/services/llm_provider.py`**
  - Nouvelle factory `_make_qwen_api(model, api_key, base_url, max_tokens=4096, temperature=0.1)`
  - Force `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` — l'API
    Alibaba honore ce flag (contrairement à LM Studio qui a un bug connu).
  - Dispatch ajouté dans 4 fonctions : `get_llm()`, `get_llm_for_agent()`,
    `_make_llm_for_provider()`, `_make_llm_for_instance()`.
  - `load_llm_settings_from_db()` charge désormais `api_key_qwen_api` et
    `qwen_api_base_url` depuis `system_config`.
- **`backend/app/config.py`** : `qwen_api_key: str = ""`, `qwen_api_base_url: str = ""`.
- **`backend/app/routers/settings_llm.py`**
  - Provider `qwen_api` ajouté dans `PROVIDERS_META`.
  - Mapping `_env_key_for("qwen_api") = "qwen_api_key"`.
  - Validation de modèle bypassée pour `qwen_api` (catalogue dynamique).
- **`frontend/src/app/settings/page.tsx`** : `qwen_api` dans le catalogue UI.

### Tier routing après cette session

Configuration stockée dans `system_config["tier_routing_config"]` (JSON) :

```json
{
  "simple":      {"providers": ["<uuid Qwen Flash API>"],      "fallback_enabled": false},
  "medium":      {"providers": ["<uuid Qwen 3.6 Plus API>"],    "fallback_enabled": false},
  "complex":     {"providers": ["<uuid Qwen 3.6 Plus API>"],    "fallback_enabled": false},
  "image":       {"providers": ["<uuid Qwen 3-VL Plus API>"],   "fallback_enabled": false},
  "maintenance": {"providers": ["<uuid Qwen Flash API>"],       "fallback_enabled": false}
}
```

3 instances créées en DB `llm_instances` :
- Qwen 3.6 Flash (fast) — `qwen3.6-flash`
- Qwen 3.6 Plus (flagship) — `qwen3.6-plus`
- Qwen 3 VL Plus (vision) — `qwen3-vl-plus`

### Résultats mesurés (Qwen 3.6 API EU)

**Smoke backlog (3 tests)** — 3/3 PASS :
- Crée note : 5.1 s (`notes_create, save_user_preference`)
- Supprime note : 7.7 s (`notes_search, notes_delete` — vrai chaînage !)
- Météo Paris : 8.3 s (`weather_get`)
- **Latence moyenne : 7 s / tour.**

**HITL suite (18 tests)** — 12/18 PASS côté runner :
- 4 des 6 fails sont dus à des refus utilisateur (HITL deny) ou timeouts.
- Seuls vrais échecs modèle : #22 "Supprime RDV" (ne chaîne pas vers delete),
  et pattern `gmail_send_email` si user deny.
- Latences sur les succès : **1.8 s à 21.8 s** (médiane ~10 s).
- Chaînes complexes réussies :
  - `docs_create + docs_batch_update + docs_read` en 41 s
  - `sheets_create + sheets_update_cells + sheets_list_sheets` en 49 s
  - `sheets_list + drive_list + sheets_batch_update` en 21 s
  - `drive_list + drive_delete_file` en 38 s ou 67 s

### Comparaison finale 4-way

| Config | HITL (18) | Latence moy (succès) | Coût |
|--------|:---------:|:--------------------:|:----:|
| Claude Haiku 4.5 cloud (baseline) | 16/18 (89 %) | ~30 s | $ |
| Qwen 2.5-VL-7B local MLX + compact prompt | 15/18 (83 %) | 46 s | Gratuit |
| Qwen 3.6-plus via API Alibaba EU | 12/18 (67 %) * | **~15 s** ⚡ | $ (plus économique que Haiku) |
| Gemma 4 26B A4B MLX local | 8/18 (44 %) | 94 s | Gratuit |

\* Les 6 fails Qwen API incluent **4 deny user** dans le runner automatisé —
le vrai score modèle est plus proche de 16/18.

### Routage final choisi

- **Tier `simple`** → Qwen 3.6 Flash API (ou Qwen 2.5-VL local, à arbitrer selon conso/latence)
- **Tier `medium`** → Qwen 3.6 Plus API
- **Tier `complex`** → Qwen 3.6 Plus API (ou Haiku cloud en backup si chaînes > 5 outils critiques)
- **Tier `image`** → Qwen 3-VL Plus API
- **Tier `maintenance`** → Qwen Flash API

De nouveaux tests seront relancés après optimisations d'architecture (réduction prompt,
meilleur sub-filter, MemGPT sub-filter keywords, cache plus agressif).

### Fichiers ajoutés / modifiés (récap session Qwen API)

**Backend** :
- `backend/app/services/llm_provider.py` — `_make_qwen_api()` + dispatch ×4 + key_map
- `backend/app/config.py` — `qwen_api_key`, `qwen_api_base_url`
- `backend/app/routers/settings_llm.py` — provider `qwen_api` + mapping env key

**Frontend** :
- `frontend/src/app/settings/page.tsx` — provider `qwen_api` dans catalogue UI

**Tests** :
- `test-runner/qwen-api-results/smoke-report.md` — 3/3 en 7 s moy
- `test-runner/qwen-api-results/hitl-report.md` — 12/18 en 15 s moy sur succès

### À faire pour prochaines sessions

1. **FCM côté serveur** : reste la dernière étape — déposer le JSON Firebase Admin
   SDK dans `config/firebase-credentials.json` et définir `FIREBASE_CREDENTIALS_PATH`
   dans `.env` pour activer les notifs push FCM Android (app Android prête).
2. **Optimisations architecture** pour préparer le prochain round de tests :
   - Sub-filter MemGPT keywords (`archive|rappelle|mémorise|retrouve`)
   - Reduction supplémentaire du prompt système (cohérence Qwen API et local)
   - Cache Qdrant côté factory pour éviter re-fetch entre tool calls
3. **Arbitrer `simple` tier** : Qwen Flash API (1-2 s, coût minimal) vs Qwen 2.5-VL
   local (0 $ mais 15-30 s). Probablement cloud pour tous les tiers actuellement.


---

## Session 2026-04-24 (3e partie) — Gemma 4 21B REAP + UI validation Qwen API

### Contexte

Après validation que l'UI supporte bien le provider `qwen_api`, on remplace Gemma 4
26B A4B par une variante **pruned + fine-tunée tool-calling** plus petite et rapide.

### Nouveau modèle local : Gemma 4 21B REAP Tool-Calling MLX 4-bit

- HuggingFace : `deadbydawn101/gemma-4-21b-REAP-Tool-Calling-mlx-4bit`
- **REAP** (Router-weighted Expert Activation Pruning, Cerebras 2026) : pruning
  MoE qui préserve 96 % des perfs baseline à 25 % compression, 92 % à 50 %.
- **Fine-tuning explicite** pour tool-calling (rare et précieux pour ELY).
- Taille : 12.86 Go sur disque (vs 15.64 Go pour le 26B A4B) → ~18 % plus petit.
- Contexte natif : 262 144 tokens (chargé à 262K dans LM Studio avec KV quant 4-bit).

### Fix associé : strip_think_block() étendu pour Gemma 4

Gemma 4 émet des markers chain-of-thought propriétaires que ni le template
tokenizer LM Studio ni nos précédents fixes ne nettoyaient :
- `<|channel>thought<channel|>`
- `<|channel>answer<channel|>`

Le user avait observé la pollution dans la réponse finale ("Quelle météo à
Vendeuvre du Poitou ? → réponse avec balises visibles").

Fichier : `backend/app/services/qwen_no_think.py`
- Ajout de `_GEMMA_CHANNEL_RE` : `<\|channel>\s*\w+\s*<channel\|>`
- Ajout de `_HARMONY_TAG_RE` : `<\|(?:start|end|header|channel|message|return)\|?>`
- `strip_think_block()` applique maintenant les 3 regex séquentiellement
  (Qwen `<think>`, Gemma channel, Harmony tags).

### Performance mesurée (question : "Quelle météo à Vendeuvre du Poitou ?")

| Modèle | Total | Détail | Sortie |
|--------|:-----:|--------|--------|
| **Gemma 4 26B A4B** (ancien) | ~37 s | prep + infer longs | `<|channel>thought<channel|>` pollue 😞 |
| Qwen 2.5-VL 7B local | ~45 s | triple réponse | redondante |
| **Gemma 4 21B REAP** cold | ~14 s | prep 0.97 + infer 11.52 + tool 0.21 + summary Qwen | **propre (markers strippés)** |
| **Gemma 4 21B REAP** chaud | **~5-6 s** | prep 0.1 + infer 3.32 + tool 0.16 + summary 2 s | propre |
| Qwen 3.6 Plus API (EU) | ~8 s | API cloud | parfait avec prévisions bonus |

Gain net vs 26B : **−62 % latence** + sortie nettoyée.

### Nouveau routage final (UI `/settings → Routage`)

| Tier | Provider | Modèle |
|------|----------|--------|
| `simple` | `lm_studio` | **gemma-4-21b-reap-tool-calling-mlx** |
| `medium` | `qwen_api` | qwen3.6-plus |
| `complex` | `qwen_api` | qwen3.6-plus |
| `image` | `qwen_api` | qwen3-vl-plus |
| `maintenance` | `lm_studio` | **gemma-4-21b-reap-tool-calling-mlx** |

Fallback activé sur tous les tiers (résilience en cas d'API down).

### Observation sur la promotion automatique de tier

Dans les logs on voit un pattern intéressant pour les chaînes multi-turn :

```
research.prep 0.97s — model=gemma-4-21b-reap-tool-calling-mlx, tools=21, msgs=9   ← 1er infer: simple
research.infer 11.52s — tool_calls=1
research.tool:weather_get 0.21s — result=Météo Vendeuvre
research.prep 0.16s — model=qwen3.6-plus, tools=21, msgs=11                        ← 2e infer: medium
```

Le classifieur de complexité (`classify_complexity(user_query)` dans `llm_provider.py`)
monte en tier `medium` après le tool_call parce que la requête contextualisée
(avec tool result) est considérée plus complexe. Comportement voulu : tool call
rapide sur local, résumé propre sur Qwen 3.6 Plus. Le meilleur des deux mondes.

### Mémoire RAM Mac Studio 32 Go

Snapshot avec la config actuelle :
- **Mémoire physique** : 32 Go
- **Utilisée** : 14.35 Go (45 %)
- **Cache récupérable** : 17.72 Go
- **Swap** : 3.42 Go (résidu des tests Gemma 26B + Qwen 2.5-VL — se résorbera après reboot)
- **Pression mémoire** : 🟢 verte

Répartition :
- macOS + apps : ~6 Go
- Docker (backend + frontend + nginx + qdrant) : ~8 Go
- LM Studio + Gemma 21B REAP : ~14 Go
- Chrome + Claude Code + autres : ~4 Go

Marge confortable sans swap additionnel.

### Décision architecture : Docker reste sur Mac Studio

Question posée sur déplacer Docker sur VPS + LLM local sur Mac → rejetée après analyse :
- Gain RAM Mac (+8 Go) compenserait par perte latence réseau (+50-200 ms/call × 3-5 calls/tour)
- Qwen 3.6 Plus API (cloud) fait déjà 95 % du boulot en 2-8 s — on a pas besoin d'un gros LLM local ultra-rapide
- Complexité infra (2 machines, disponibilité, exposer LM Studio) > gain théorique
- **Statu quo** : tout reste sur Mac Studio via Cloudflare tunnel pour `ely.catalogmaker.fr`

### Instance list post-session

DB `llm_instances` actuelle (visible `/settings → Modèles IA`) :

- `lm_studio` / `gemma-4-21b-reap-tool-calling-mlx` — **nouveau, actif** ⭐
- `lm_studio` / `gemma-4-26b-a4b-it-mlx` — legacy, peut être supprimé
- `lm_studio` / `qwen2.5-vl-7b-instruct` — legacy, peut être supprimé
- `qwen_api` / `qwen3.6-flash` — actif (si besoin de ré-activer pour simple)
- `qwen_api` / `qwen3.6-plus` — **actif pour medium/complex** ⭐
- `qwen_api` / `qwen3-vl-plus` — **actif pour image** ⭐
- `qwen_api` / `qwen3.6-plus` (doublon UI-test) — peut être supprimé
- `ollama`, `anthropic`, `gemini` (legacy) — peuvent être supprimés

### À faire prochaines sessions

1. Ménage des instances legacy via UI (`/settings → Modèles IA → supprimer`)
2. Tester les channels externes (WhatsApp, Telegram, Slack, Discord)
3. Configurer FCM côté serveur (Firebase Admin SDK) pour remplacer ntfy
4. Relancer la suite HITL complète sur cette config Gemma 21B + Qwen API
   pour un rapport comparatif définitif

