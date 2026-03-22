# ELY Agent — Journal d'implémentation

> Ce fichier sert de mémoire persistante entre sessions de développement.
> Mis à jour le : 2026-03-22

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
- [x] Scopes : gmail, calendar, drive, documents, spreadsheets, tasks

#### Configuration système
- [x] Table `system_config` pour configuration runtime (clé/valeur, secrets masqués)
- [x] Priorité DB > env vars (via `get_config(key, fallback=env)`)
- [x] CRUD admin : `GET/PUT/DELETE /admin/config`

#### Notifications push (ntfy)
- [x] Notifications HITL via ntfy (Android)
- [x] Configurable : `NTFY_URL` + `NTFY_TOPIC`

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

---

## Prochaines étapes (voir roadmap.md)

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
   - `backend/app/services/memory_manager.py` — réécriture complète
   - Score hybride : `(α × vector_score + β × keyword_score) × time_decay`
   - Timestamps automatiques sur tous les upserts Qdrant (`created_at`)
   - Décroissance temporelle exponentielle par collection :
     - `security_constraints` : λ=0.00 (permanent, jamais périmé)
     - `memories` : λ=0.01 (demi-vie ~69 jours)
     - `interactions` : λ=0.05 (demi-vie ~14 jours)
   - Keyword boost : mots significatifs de la requête cherchés dans le texte stocké
   - Re-ranking en Python sur 4× plus de candidats Qdrant
4. Architecture de plugins/skills — À FAIRE
5. Contrôle navigateur (Playwright) — À FAIRE
