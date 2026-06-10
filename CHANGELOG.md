# Changelog

All notable changes to ELY are documented here, in reverse chronological order.

This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention. Each entry references the commit short-SHA so you can dig into the exact diff with `git show <sha>`.

Categories used:
- **Added** — new user-visible capabilities.
- **Changed** — non-breaking changes to existing behaviour or wording.
- **Fixed** — bug fixes.
- **Security** — anything touching auth, anonymization, HITL, sandboxing, or vault.
- **Docs** — documentation-only changes that nonetheless affect what users see.

> Maintainer: [Franck OLLIVIER](mailto:contact@agent-ely.fr) — `franckolv-dev`

---

## [Unreleased]

_(empty — next batch starts here)_

---

## [1.14.8] — 2026-06-10 — Phase 2 (lot 3b) revue multi-utilisateurs : caches LRU+TTL & rétention — **Phase 2 complète**

### Security
- **Vault PII unifié entre les canaux chat et voix.** `voice.py` maintenait son **propre** dict de `SecurityFilter` alors que `tool_node` dé-anonymise les arguments d'outils via le registre partagé `conversation_filters` : sur le canal vocal, les deux vaults divergeaient → un tool_call vocal contenant un placeholder partait avec le **littéral `[EMAIL_0]`** (la résurgence côté voix du bug Gmail du 2026-05-07). Une seule source de vérité désormais, épinglée par test (`voice._get_filter is conversation_filters.get_filter`). *(2026-06-10)*

### Fixed
- **Caches par-conversation : LRU + TTL d'inactivité au lieu du FIFO (B-7).** Quatre modules (`conversation_filters`, `frozen_memory`, `system_prompt_cache`, `fallback_manager`) dupliquaient le même `_BoundedDict` plafonné à 1000 entrées avec éviction **FIFO à l'insertion** : sous charge (~1000 conversations actives cumulées), l'entrée évincée était la plus *anciennement créée* — potentiellement une conversation **encore en cours** (vault PII détruit en pleine conversation = placeholders du contexte LLM irrésolubles ; état fallback perdu = retour silencieux au primary en panne). Nouveau `services/bounded_cache.BoundedLRUDict` partagé : chaque lecture rafraîchit l'entrée (l'éviction ne cible que la plus longtemps inactive) + TTL d'inactivité 24 h (expiration paresseuse). *(2026-06-10)*

### Added
- **Rétention des tables de signaux (§4).** Aucune politique n'existait : audit, usage et signaux learning croissent à chaque tour — N fois plus vite en multi-utilisateurs, et sur SQLite un gros fichier = checkpoints WAL plus longs = fenêtres de lock plus larges. Job quotidien 04:30 : `audit_logs`/`hitl_refusals`/`hallucination_blocks`/`provider_switches`/`error_logs` → `ELY_SIGNALS_RETENTION_DAYS` (90 j, 0 = off) ; `usage_logs` → `ELY_USAGE_RETENTION_DAYS` (365 j). Volontairement épargnés : messages/conversations, `mission_critiques` (bench mining), `failure_cases` (UI tool-gaps). *(2026-06-10)*

---

## [1.14.7] — 2026-06-10 — Phase 2 (lot 3a) revue multi-utilisateurs : budget LLM par utilisateur

### Added
- **Budget LLM quotidien par utilisateur, opt-in (A-6b).** Rien ne bornait la dépense cloud d'un user (ou d'un script avec un token volé) — c'est l'opérateur de l'instance qui paie. Nouveau `services/budget_guard.py` (inspiré du `budget_guard.py` Phase 5A de la branche salvage, dont le volet tracking est déjà couvert par `UsageLog.cost_usd`) : somme des coûts du jour (minuit UTC), refus au-delà de `ELY_USER_DAILY_BUDGET_USD`. **Désactivé par défaut (0)** — une install solo ne doit jamais s'auto-bloquer sur une table de prix heuristique ; les instances multi-utilisateurs l'activent via env. Application : chat et voice (refus doux avec message explicite), tâches planifiées (exécution du jour sautée, tâche préservée), missions (tick **reporté d'une heure** — un user temporairement à sec ne perd pas sa mission). Best-effort : une erreur DB ne bloque jamais un run. *(2026-06-10)*

### Fixed
- **Les coûts LLM background sont enfin comptés dans `UsageLog`.** Les résumés de fin de conversation (3 appels LLM à chaque déconnexion), l'extraction + consolidation mémoire et le critic de missions (cron 5 min sur tier cloud) n'appelaient pas `log_usage` : la facture réelle par user était sous-estimée précisément sur les chemins qui scalent avec le nombre d'utilisateurs — et le budget A-6b aurait été contournable par ces chemins. Nouveau helper `analytics_service.log_response_usage()` (extraction `usage_metadata` best-effort, no-op silencieux si le provider ne l'expose pas), branché sur les 4 sites. *(2026-06-10)*

---

## [1.14.6] — 2026-06-10 — Phase 2 (lot 2) revue multi-utilisateurs : équité entre utilisateurs

### Fixed
- **Le rate limit global est enfin branché (A-6a).** `RATE_LIMIT=60/minute` existait dans le compose et `settings.rate_limit` dans la config **depuis le début, sans jamais être relié au limiter** : seuls 3 endpoints d'auth étaient limités, tout le reste était illimité. `default_limits` + `SlowAPIMiddleware` appliquent désormais la limite à toutes les routes HTTP (multi-bornes acceptées : `120/minute,2000/hour`). `/health` est exempté (sondé par le healthcheck Docker — un 429 ferait flapper le conteneur). Les WebSockets ne sont pas concernés : leur débit est borné par B-15. *(2026-06-10)*
- **Cap de runs agent concurrents par utilisateur (B-15).** 1 user × 10 onglets = 10 runs LLM simultanés (coût cloud, RAM, contention) payés en latence par les autres. Nouveau `services/run_gate.py` : sémaphore par user (défaut 2, `ELY_MAX_AGENT_RUNS_PER_USER`), acquis par chat et voice — les runs excédentaires du même user font la queue sans impacter les autres. *(2026-06-10)*
- **Heartbeat missions : équitable et non bloquant (B-3).** Les missions étaient tickées séquentiellement sous un lock global : la mission lente d'un user (tick de 3 min) bloquait les missions de **tous** les autres, et le beat suivant était sauté tant que le précédent tournait (débit max théorique ~5 ticks/30 s, bien moins en pratique). Désormais : dispatch **round-robin par user** (un user avec 5 missions dues n'affame plus les autres), ticks en tâches de fond bornées par `MISSION_TICK_CONCURRENCY` (défaut 3), garde-fou `_in_flight` par mission (jamais deux ticks simultanés de la même mission), et le beat rend la main immédiatement. *(2026-06-10)*

---

## [1.14.5] — 2026-06-10 — Phase 2 (lot 1) revue multi-utilisateurs : hygiène disque & données

### Fixed
- **Connexions FTS hors-engine alignées sur les pragmas de l'engine (B-2).** Les deux stores FTS5 ouvraient des `aiosqlite.connect()` nus sur le même fichier que l'engine SQLAlchemy : 5 s de lock timeout (vs 30 s engine) et `synchronous=FULL`. Sous écrivains concurrents, une écriture d'index qui attendait > 5 s recevait `database is locked` — avalé par le « best-effort » — et **la ligne d'index FTS était perdue définitivement** : rappel mémoire et recherche de messages dégradés silencieusement, par user, de façon non reproductible. Nouveau helper `services/sqlite_aio.connect()` (timeout 30 s + `busy_timeout` + `NORMAL`), 11 sites migrés, test source-level anti-régression. *(2026-06-10)*
- **Voix Vivienne réellement active en Docker.** Le compose forçait `TTS_VOICE=${TTS_VOICE:-fr-FR-DeniseNeural}` — le défaut applicatif de la v1.14.2 était **écrasé silencieusement** quand `TTS_VOICE` n'était pas dans le `.env` hôte. Défaut compose aligné. *(2026-06-10)*

### Added
- **Backup SQLite nocturne (§4).** Qdrant était sauvegardé chaque nuit ; `cyberentity.db` — users, conversations, missions, signaux learning, la **vraie** source de vérité — jamais. Nouveau job 02:30 via `VACUUM INTO` (snapshot cohérent à chaud, les writers continuent) couvrant aussi `missions_checkpoints.sqlite`, rotation 7 j (`ELY_SQLITE_BACKUP_RETENTION_DAYS`), à destination du volume hôte déjà monté. *(2026-06-10)*
- **Uploads : volume persistant, quota par user, purge (B-9).** `/app/uploads` n'était pas monté — chaque rebuild perdait les fichiers et captures référencés dans l'historique des conversations (liens morts). Volume `./data/uploads` ajouté ; quota disque par user (500 Mo, `ELY_UPLOAD_QUOTA_MB`, 0 = off) vérifié à l'upload (413 au-delà, scan en thread) ; purge quotidienne 03:30 des fichiers > 90 j (`ELY_UPLOADS_RETENTION_DAYS`, 0 = off). *(2026-06-10)*
- **`mem_limit: 4g` sur le backend (B-16).** Seul service sans cap mémoire alors que c'est lui qui grossit avec N users (Whisper, fastembed, Chromium, clients WhatsApp par user) — risque de swap hôte qui dégrade LM Studio. *(2026-06-10)*

---

## [1.14.4] — 2026-06-10 — Phase 1 (lot 2) revue multi-utilisateurs : event loop & LLM local

### Fixed
- **`get_llm_for_tier` ne bloque plus l'event loop au cold start (B-1).** La branche de chargement paresseux des settings LLM faisait `fut.result(timeout=10)` depuis du code sync exécuté **sur** la loop : cache froid + premier appel = toute l'application gelée (tous les WebSockets, tous les users) jusqu'à 10 s — précisément au moment du rush post-redémarrage. Désormais : si une loop tourne, le chargement part en tâche de fond (référence forte via `spawn`) et le tour courant utilise les défauts ; hors loop (script `docker compose exec`, cron isolé), chargement synchrone comme avant. *(2026-06-10)*
- **Porte de concurrence devant le LLM local (A-5).** LM Studio/MLX ne sert qu'**une** requête à la fois : N requêtes simultanées (N users, ou chat + cron MAINTENANCE) s'empilaient côté serveur sans signal, chacune payant le prompt processing complet des précédentes jusqu'au timeout 900 s. Borne au niveau **transport** : `httpx.AsyncClient` partagé par base_url avec `max_connections=1` (env `LOCAL_LLM_MAX_CONCURRENCY`) — la file d'attente vit côté client, couvre `ainvoke`/`astream`/`bind_tools` sans wrapper. Même borne (`async_client_kwargs`) sur les chemins Ollama legacy. *(2026-06-10)*

---

## [1.14.3] — 2026-06-10 — Phase 1 (lot 1) revue multi-utilisateurs : fiabilité temps réel

### Fixed
- **`ws_registry` multi-sockets + bug des deux onglets (B-6).** Un user avec deux connexions (deux onglets, PWA + desktop, chat + voix) perdait des pushes : la 2ᵉ connexion *remplaçait* la 1ʳᵉ, et — pire — fermer l'ancien onglet désinscrivait la socket du nouveau (`pop(user_id)` aveugle), laissant l'utilisateur connecté mais injoignable (cartes HITL, résultats de tâches planifiées, alertes watchdog, frames navigateur). Registre `dict[str, set[WebSocket]]`, `unregister(user_id, ws)` ciblé, et fan-out `send_text_all()` avec purge des sockets mortes — adopté par hitl_manager, scheduler, watchdog et browser_skill. *(2026-06-10)*
- **Webhook Telegram : réponse immédiate + dédup par `update_id` (B-8).** Le traitement tournait inline — la réponse HTTP ne partait qu'après le run agent complet (souvent > 60 s) ; Telegram considérait le webhook en échec et **rejouait le même update** → agent exécuté 2-3× pour un message (actions et coûts dupliqués). Désormais : dédup bornée (1000 ids) puis traitement en tâche de fond, la route répond 200 instantanément. *(2026-06-10)*
- **Sandbox : concurrence bornée (B-10).** Aucune limite sur `/run` alors que chaque subprocess a droit à 256 Mio dans un conteneur plafonné à 512 Mio : deux runs gourmands simultanés (deux users) suffisaient à OOM-kill **le conteneur entier**, faisant échouer tous les runs de tous les users d'un coup. Sémaphore (défaut 2, env `ELY_SANDBOX_MAX_CONCURRENCY`) + file d'attente bornée 10 s puis 503 propre. *(2026-06-10)*
- **Backpressure sur le stream de tokens (B-14).** Un client lent ou zombie bloquait `websocket.send_text` par token, ce qui gelait la consommation du stream LLM (connexion provider maintenue ouverte, tokens facturés pour rien). Timeout d'envoi 10 s → socket traitée comme morte, sur les deux canaux chat et voix. *(2026-06-10)*
- **Fire-and-forget fiabilisé : `background_tasks.spawn()` (§4 mineurs).** 9 sites `asyncio.create_task(...)` sans référence forte (signaux learning, extraction mémoire, log usage, résumés de fin de conversation) pouvaient être garbage-collectés en vol sous pression mémoire — perte silencieuse. Module central avec registre de références fortes + log des exceptions (pattern repris de `sub_agents/factory.py`). *(2026-06-10)*

---

## [1.14.2] — 2026-06-10 — Phase 0 revue multi-utilisateurs : durcissement + voix Vivienne

### Security
- **PII : l'historique assistant du canal vocal est ré-anonymisé avant le LLM (B-13, revue 2026-06-10).** Le fix #55 (`4af483b`) couvrait le chat mais pas `/ws/voice` : les réponses passées de l'agent (stockées dé-anonymisées pour l'affichage) repartaient **en clair** vers les LLM cloud à chaque tour vocal — emails, téléphones inclus. Le canal vocal applique désormais le même `sf.anonymize(...)` que le chat (helper `_anonymized_history`, testé). *(2026-06-10)*
- **Headers de sécurité HTTP sur toutes les réponses backend (B-18/D1).** Nouveau middleware `app/middleware/security_headers.py` : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, et `Strict-Transport-Security` quand le déploiement est HTTPS (`cookie_secure`). Pas de CSP (casserait Swagger UI pour zéro gain — les pages utilisateur sont servies par Next.js). *(2026-06-10)*
- **TTL des access tokens : 60 → 15 minutes par défaut (B-18/D2).** Les access tokens n'ont pas de `jti` et ne sont pas révocables — seule l'expiration borne un token volé (le logout ne blackliste que le refresh). Le refresh étant transparent côté frontend, on aligne sur la durée que `docs/architecture.md` documentait déjà. Override possible : `ACCESS_TOKEN_EXPIRE_MINUTES`. *(2026-06-10)*
- **Warning de démarrage si HTTPS sans `CORS_ORIGINS` explicite (B-18/M3).** Le runtime retombe sur `[frontend_url]` (pas un wildcard, donc pas bloquant — et les déploiements nginx même-origine ne déclenchent jamais le CORS), mais une allowlist explicite est la posture attendue en multi-utilisateurs. *(2026-06-10)*

### Fixed
- **Chemin SQLite par défaut ancré sur `backend/` (revue §4, mineur).** Le défaut relatif `./cyberentity.db` dépendait du cwd : lancé depuis la racine vs depuis `backend/`, le backend lisait/écrivait **deux bases divergentes** (constaté en réel le 9 juin : 798 Ko à la racine, 978 Ko dans backend/). Le défaut est désormais absolu ; toute `DATABASE_URL` explicite (Docker) passe inchangée. *(2026-06-10)*
- **`recursion_limit` du canal vocal aligné sur `CHAT_RECURSION_LIMIT`** au lieu d'un `100` codé en dur (divergence chat/voice, revue B-13). *(2026-06-10)*

### Changed
- **Voix TTS par défaut : `fr-FR-DeniseNeural` → `fr-FR-VivienneMultilingualNeural`.** Le réglage `settings.tts_voice` existait mais n'était **lu nulle part** — la voix restait épinglée sur Denise dans deux constantes séparées (`routers/tts.py`, `services/voice_service.py`). Les deux sont désormais câblées sur le setting (override : `TTS_VOICE`), et le défaut passe sur la voix multilingue HD, nettement plus naturelle. Retour utilisateur : « voix trop artificielle » → à re-tester. *(2026-06-10)*

---

## [1.14.1] — 2026-06-10 — Sécurité multi-utilisateurs Phase 0 : IDOR + Whisper

### Security
- **Conversation ownership enforced on the chat WebSocket (IDOR A-1, revue 2026-06-10).** The `/ws/chat` handler accepted any client-supplied `conversation_id` without checking it belongs to the authenticated user — any logged-in user could write into (and have the agent read from) another user's conversation by replaying its UUID, including the per-conversation PII vault and frozen-memory snapshot keyed by that id. A foreign or unknown id now closes the socket with code 4003, indistinguishable from "not found" (no existence oracle), mirroring `conversations._get_owned_conversation`. Regression-pinned by `tests/test_idor_conversation_ownership.py` (real WS round-trip). *(2026-06-10)*
- **Ownership check on `POST /api/me/state/recompute` (IDOR A-2, revue 2026-06-10).** The `conversation_id` query param was passed straight to `compute_user_state`, whose `_load_recent_messages` has no user filter — the MAINTENANCE LLM could read a foreign conversation. Foreign/unknown ids now 404 before any read. *(2026-06-10)*

### Fixed
- **faster-whisper moved off the event loop (A-4, revue 2026-06-10).** `model.transcribe(...)` was called synchronously inside async handlers (`/ws/voice` + `POST /api/transcribe`), freezing the whole backend (all websockets, mission heartbeats, webhooks) for the duration of each decode. Transcription now runs in `asyncio.to_thread` with the lazy segments generator consumed inside the worker thread, bounded by a shared `Semaphore(2)`. *(2026-06-10)*
- **`POST /api/transcribe` always returned 500.** The endpoint read `info.detected_language`, which does not exist on faster-whisper's `TranscriptionInfo` (real field: `language`) — every successful transcription crashed at response-build time. Latent since the endpoint was written; surfaced by the A-4 test pins. *(2026-06-10)*

### Changed
- `.gitignore` now excludes SQLite WAL/SHM sidecars (`*.db-wal`, `*.db-shm`) that appear when the backend runs outside Docker with the relative DB path. *(2026-06-10)*

---

## [1.1.2] — 2026-05-17 — Sprint 1: cross-conversation memory recall + agent hallucination hardening

Tagged release closing **Sprint 1 (Memory recall)** on the `feature/memory-recall` branch, plus everything else merged after `v1.1.0`. Two themes dominate this version:

1. **Memory recall**: ELY can now retrieve and summarise past conversations across the user's entire history, in pure prose, via a local Ministral 3B summariser (cost-marginal-zero). The agent calls it autonomously when the user says *« tu te souviens de… »*, *« on en était où… »*, *« mon médecin traitant… »*, etc.
2. **Anti-hallucination hardening**: a stricter RULE 0 covers all data-bearing tools (not just browser), plus six rules around calendar/timestamps/list-size/refusal-on-suspicion. Triggered by a live audit where DeepSeek fabricated four fictional corporate calendar events instead of calling `calendar_list_events`.

### Added (Sprint 1 — Memory recall, full pipeline)
- **`2fbef2b` — Phase 1: FTS5 messages index + auto-indexer + backfill.** New `MessagesFTSStore` sister to the existing `FTSStore` (which indexes extracted facts). Indexes the literal messages of every conversation behind a SQLAlchemy `after_insert` hook (fire-and-forget). Idempotent backfill script (`scripts/backfill_messages_fts.py`) ran on Franck's history: 1862/2468 messages indexed. 16 unit tests cover tokenizer, stop-words, prefix-match, accents, user isolation. *(2026-05-15)*
- **`2fbef2b` — Phase 2: `session_search.py` + Ministral 3B summariser.** FTS hits grouped by conversation, BM25-ranked, top-K loaded with their full transcript (truncated to 80k chars), summarised in parallel via `ComplexityTier.SIMPLE` (Ministral 3B local in the default routing). Cost: zero euros per call. Latency: ~5-10s for 3 conversations in parallel. 11 unit tests cover JSON extraction, prompt formatting, group-ranking, content normaliser. *(2026-05-15)*
- **`7577c3d` — Phase 3: `search_past_conversations_tool` registered as agent tool.** Exposed via `tool_sets.USER_ID_TOOLS` + `toolset_profiles._DEFAULT_TOOLS` + `memory_skill` registration. Default profile is now 65 tools (was 64). Tool docstring primes the LLM on WHEN to call (memory references) and WHEN NOT TO (current-turn-only queries → use `knowledge_search` or `memory_search` instead). *(2026-05-15)*
- **`eb08dd9` — Skill registry registration fix.** Tools in ELY are discovered through the global SkillRegistry at startup, not by import. The new tool was listed in `tool_sets.py` and `toolset_profiles.py` but never plugged into a skill — so the registry silently dropped it from the bind layer (64 tools instead of 65). Added a `memory_recall` skill registration next to `memgpt_memory` in `memory_skill.py`. Lesson written into the commit message for future contributors: define → register in a skill → list in toolset_profiles. *(2026-05-15)*

### Added (related infrastructure)
- **`5fe0410` indirectly** — Docker backend image now copies `backend/scripts/` so operational scripts (backfill, admin, migrations) can be invoked via `docker compose exec backend uv run --no-sync python scripts/<name>.py`. *(2026-05-15)*

### Fixed
- **`818c6ce` — Memory bridge: `search_past_conversations_tool` triggered by implicit personal-data references too.** Previously the prompt mentioned the tool only for explicit memory patterns (« tu te souviens », « on a parlé »). It didn't cover implicit references to personal data the user had previously shared (« mon médecin », « ma banque », « le projet sur lequel je travaille »). The agent broke the implicit contract « I told you once, you remember » and asked the user to repeat. Now the prompt explicitly lists these patterns and adds: *AVANT de dire « je n'ai pas cette information » ou de demander à l'utilisateur de te répéter quelque chose qu'il a déjà mentionné, FAIS UN search_past_conversations_tool.* *(2026-05-16)*
- **`45b01b5` — RULE 0: universal anti-hallucination data rule.** Live audit on 16 May: DeepSeek-v4-pro fabricated four corporate calendar events ("Point hebdo équipe", "Déjeuner avec Sarah", "Revue de code", "Session brainstorming") instead of calling `calendar_list_events`. The actual events were "Tennis de table", "Pictavino", "Festival Food Truck". The previous "Intégrité des actions" block only covered email/document CONTENT; structured LISTS like calendar events, contacts, scheduled tasks fell through. New RULE 0 added at the top of both `_SYSTEM_PROMPT_BASE` and `_SYSTEM_PROMPT_SLM`, applies to ALL tool families. Includes concrete forbidden examples copied from the audit. *(2026-05-16)*
- **`44ee987` — Tool output reshaped from Markdown structure to conversational prose.** Root cause of a multi-model JSON-leak bug: all tested cloud LLMs (DeepSeek, Haiku, Qwen, Mistral large, Kimi K2.6) re-encode structured tool outputs as JSON cards in their reply to the user. Only the local Ministral 3B respected the original Markdown. Instead of adding per-model regex filters in the response pipeline (technical debt + risk of side effects), the tool's output was redesigned: a single conversational paragraph with connectors ("D'abord", "Ensuite", "Et enfin"), no `### [N]` headings, no metadata italics, no fences. The structure that SCREAMED data is gone, so the calling LLM has no structural signal to re-encode. *(2026-05-16)*
- **`8fd5327` — Flatten nested structured summaries from Ministral 3B.** Ministral occasionally ignored the "summary must be a plain string" instruction and returned a JSON object like `{"rendez-vous_principaux": [...], "actions_pendantes": [...]}`. Excellent content, wrong shape. New `_flatten_to_summary(value)` helper recursively renders any value (str / number / list / dict / nested combinations) as a Markdown-bullet-list string instead of dropping the LLM's work. *(2026-05-15)*
- **`a8a4f5f` — Guard against non-string title/summary in parsed JSON.** Ministral 3B sometimes returns the title/summary fields as nested objects rather than plain strings. Coerce both through `_content_to_text` before calling `.strip()` instead of crashing. *(2026-05-15)*
- **`166d97d` — Tool-pair-aware context trimming.** The context manager used to drop messages from the head of the conversation when the token budget was exceeded, without checking that it didn't break a `tool_call ↔ tool_response` pair. DeepSeek (and every OpenAI-protocol provider) rejects orphan tool messages with `400 Bad Request`, which triggered the fallback chain down to weaker models. After the fix, trimming respects pairs: orphan `ToolMessage` in the head is skipped, dangling `AIMessage` with unanswered `tool_calls` in the tail is trimmed. *(2026-05-15)*
- **`a7bf15d` — Anti-hallucination prompt rules 5 & 6.** Mandatory temporal sanity-check before proposing any date (refuses to propose `Wednesday 13 May` when today is the 14th); explicit refusal threshold on lists with > 15-20 values at a regular interval (classic hallucination signature). *(2026-05-14)*
- **`596c329` — Pattern C: collapsed-UI handling.** Doctolib and similar SPAs render days as collapsible cards with the slots out of the DOM until you click the chevron. The agent now has a concrete recipe (read_html → identify chevron selector → click → wait_for_selector → read scoped) and a hard refusal rule when the same precise values appear for two distinct items (e.g. identical slots for two different days). *(2026-05-14)*
- **`e797e1a` — Anti-hallucination rules 1-4 + Pattern C bootstrap.** First version of the rules forbidding fabrication of precise values, vision-for-numerics misuse, and context-coherence violations. *(2026-05-14)*
- **`403c48d` — Revert needless LOCKED_HITL on `scheduler_delete_task`.** User-initiated deletion of their own scheduled tasks shouldn't require HITL confirmation — pure friction. The previous commit had added it "for safety" but `scheduler_delete_task` wasn't in `ALWAYS_CRITICAL_TOOLS` anyway, so the lock was a no-op with a misleading docstring. *(2026-05-14)*
- **`6423c29` — Expose scheduler list + delete to the default agent profile.** The tools existed but only `scheduler_create_task` was bound to the agent. Symptom: ELY would create scheduled tasks but answer "I have no tool to delete them" and resort to scheduling a cleanup task for tomorrow at 9am. Regression-guard test included. *(2026-05-14)*
- **`5a6b52a` — Chat bubble overflow + soft handling of structured tool outputs.** `MessageBubble.tsx` `<pre>` renderer used `overflow-x-auto` only, so a 500-char-line JSON dump forced a horizontal scrollbar across the chat. Added `whitespace-pre-wrap break-all` so long single-line dumps wrap inside the bubble. Inline tokens (URLs, hashes) also wrap. *(2026-05-15)*
- **`e5b1a2e` — Contrast fix on `/settings/extension`.** The amber "new token created" banner used `bg-amber-50` with default text colour, which rendered as light-grey-on-cream in dark mode — barely legible. Switched to theme-agnostic semi-transparent overlays. *(2026-05-14)*

### Changed
- Default `_DEFAULT_TOOLS` profile size: 64 → 65 tools (added `search_past_conversations_tool`).
- `LOCKED_HITL_TOOLS` no longer contains `scheduler_delete_task` (cf. `403c48d`).

### Docs
- **`cfc57d6` — CHANGELOG.md created** and bug-report template extended with HUD-model + tier dropdowns to make user reports actionable. *(2026-05-15)*
- **`e9e3553` — LinuxFr feedback addressed across docs.** ROADMAP.md reformulated to drop ambiguous "open-source" claims (we are source-available); `docs/security.md` gains a "Limites assumées de l'anonymisation déterministe" section (corpus-wide frequency attack, out-of-pattern PII, indirect inference, hash reversibility); `docs/installation.md` gains a chapter "8. Exposer ELY à l'extérieur" with three options (Tailscale → Caddy+Let's Encrypt → Cloudflare Tunnel) ranked by sovereignty; FAQ FR + EN clarified for non-profits (strict non-commercial = free, no paperwork). *(2026-05-15)*
- **`094f257` — Roadmap aligned with reality + MCP expanded.** Sprint 0.5 (Chrome extension) inserted between launch and memory-recall; Sprint 3.5 (Web Automation) reframed as complementary to the extension (batch use cases); Sprint 4 (MCP) expanded from a single line into four sub-items: 4.1 consume external MCP servers, 4.2 expose ELY as MCP server, 4.3 Settings UI, 4.4 OAuth manager. New `v1.1.2` row in the target versions table. *(2026-05-15)*

### Known limitations carried over
- **Cosmetic JSON leak after memory recall**: cloud LLMs re-encode the prose tool output as JSON cards in the user-facing reply. The content is correct, the form is noisy. Three rounds of fixes attempted (prompt rule, tool docstring, server-side regex filter), none held reliably. Accepted as cosmetic in this release; will be addressed properly in a future version via either a UI-side renderer for tool results, or a runtime bypass that delivers `search_past_conversations_tool` output directly without LLM reformat.
- **Gemini returns "internal error"** when used as the agent's primary tier. Untested but likely a message-format compatibility issue (Gemini is stricter than OpenAI-protocol providers about sequence ordering). Backlogged for a "Gemini compat" sprint.
- **GitHub Traffic stats not accessible to the agent**: when asked "how many clones on the ELY repo?", ELY answers with whatever it can find via web search (typically incorrect or zero). A dedicated `github_traffic_stats` tool is backlogged.
- **599 messages from the FTS backfill are orphan** (pre-existing conversations that were deleted but whose messages remained without a CASCADE). Acceptable for the current backfill since the missing data isn't catastrophic; `audit messages orphelins` is in the backlog.

---

## Pre-1.1.2 (entries previously listed under [Unreleased])

The bug fixes below predate Sprint 1 work and were rolled into this same v1.1.2 release for simplicity.

### Fixed
- **`166d97d` — Tool-pair-aware context trimming.** The context manager used to drop messages from the head of the conversation when the token budget was exceeded, without checking that it didn't break a `tool_call ↔ tool_response` pair. DeepSeek (and every OpenAI-protocol provider) rejects orphan tool messages with `400 Bad Request`, which triggered the fallback chain down to weaker models. After the fix, trimming respects pairs: orphan `ToolMessage` in the head is skipped, dangling `AIMessage` with unanswered `tool_calls` in the tail is trimmed. *(2026-05-15)*
- **`a7bf15d` — Anti-hallucination prompt rules 5 & 6.** Mandatory temporal sanity-check before proposing any date (refuses to propose `Wednesday 13 May` when today is the 14th); explicit refusal threshold on lists with > 15-20 values at a regular interval (classic hallucination signature). *(2026-05-14)*
- **`596c329` — Pattern C: collapsed-UI handling.** Doctolib and similar SPAs render days as collapsible cards with the slots out of the DOM until you click the chevron. The agent now has a concrete recipe (read_html → identify chevron selector → click → wait_for_selector → read scoped) and a hard refusal rule when the same precise values appear for two distinct items (e.g. identical slots for two different days). *(2026-05-14)*
- **`e797e1a` — Anti-hallucination rules 1-4 + Pattern C bootstrap.** First version of the rules forbidding fabrication of precise values, vision-for-numerics misuse, and context-coherence violations. *(2026-05-14)*
- **`403c48d` — Revert needless LOCKED_HITL on `scheduler_delete_task`.** User-initiated deletion of their own scheduled tasks shouldn't require HITL confirmation — pure friction. The previous commit had added it "for safety" but `scheduler_delete_task` wasn't in `ALWAYS_CRITICAL_TOOLS` anyway, so the lock was a no-op with a misleading docstring. *(2026-05-14)*
- **`6423c29` — Expose scheduler list + delete to the default agent profile.** The tools existed but only `scheduler_create_task` was bound to the agent. Symptom: ELY would create scheduled tasks but answer "I have no tool to delete them" and resort to scheduling a cleanup task for tomorrow at 9am. Regression-guard test included. *(2026-05-14)*
- **`e5b1a2e` — Contrast fix on `/settings/extension`.** The amber "new token created" banner used `bg-amber-50` with default text colour, which rendered as light-grey-on-cream in dark mode — barely legible. Switched to theme-agnostic semi-transparent overlays. *(2026-05-14)*

### Added
- **`6726b27` — Sprint 1: browser interactivity tools.** `browser_tab_click(selector)`, `browser_tab_fill(selector, value)`, `browser_tab_navigate(url)`. React-aware implementations (native value setter + dispatchEvent for controlled inputs; MouseEvent + native click for buttons). Trust model: agent only emits these on explicit user request, user sees the tab live in their own Chrome. Unlocks multi-step SPA workflows (Doctolib, SNCF, Booking, .gouv.fr forms). *(2026-05-14)*
- **`56acb6e` — Sprint 0.5: long-lived extension tokens.** New `ExtensionToken` model + REST CRUD `/api/extension/tokens` + dedicated Settings page. Format `ely_ext_<48 hex>` (192 bits of entropy). SHA-256 + last_4 stored; plaintext shown exactly once at creation, then never. Replaces the previous DevTools → Application → Local Storage → copy-JWT bidouille, and ends the every-60-min disconnection. Backwards compatible: the WS handshake still accepts legacy access JWTs. *(2026-05-14)*

### Docs
- **`166d97d` indirectly** — `docs/security.md` will be updated to call out the trim-boundary class of bugs in the next sweep.
- **`e9e3553` — LinuxFr feedback addressed across docs.** ROADMAP.md reformulated to drop ambiguous "open-source" claims (we are source-available); `docs/security.md` gains a "Limites assumées de l'anonymisation déterministe" section (corpus-wide frequency attack, out-of-pattern PII, indirect inference, hash reversibility); `docs/installation.md` gains a chapter "8. Exposer ELY à l'extérieur" with three options (Tailscale → Caddy+Let's Encrypt → Cloudflare Tunnel) ranked by sovereignty; FAQ FR + EN clarified for non-profits (strict non-commercial = free, no paperwork). *(2026-05-15)*
- **`094f257` — Roadmap aligned with reality + MCP expanded.** Sprint 0.5 (Chrome extension) inserted between launch and memory-recall; Sprint 3.5 (Web Automation) reframed as complementary to the extension (batch use cases); Sprint 4 (MCP) expanded from a single line into four sub-items: 4.1 consume external MCP servers, 4.2 expose ELY as MCP server, 4.3 Settings UI, 4.4 OAuth manager. New `v1.1.2` row in the target versions table. *(2026-05-15)*

---

## [1.1.0] — 2026-05-11 — Public launch

Initial public release on GitHub. The repository was opened from private to public on Wednesday 12 May 2026; the actual development had been ongoing since early March 2026 (200+ commits, see `git log` for the pre-launch history).

### Added (launch capabilities)
- **Multi-LLM routing** with tier A/B/C/IMG and per-conversation fallback chain. Default routing: Tier A = Ministral 3B local; Tier B = DeepSeek v4-flash → v4-pro → Qwen 3.6 Flash → Ministral; Tier C = DeepSeek v4-pro primary; Tier IMG = DeepSeek v4-flash. Configurable per-user in Settings → Routing.
- **Native PII anonymization** before any cloud LLM call — credit cards, emails, tokens, IBANs, French phone numbers, named entities via NER. Deterministic mapping within a session so the LLM can reason on relationships.
- **HITL gating** on every irreversible action (gmail_send_email, calendar_delete_event, drive_delete_file, ssh_execute, vault_unlock, plus 20+ others in `LOCKED_HITL_TOOLS`). Per-user preferences, force-locked for the most destructive operations.
- **Multi-channel access**: Web UI (Next.js, FR + EN), Telegram bot, Slack app, Discord bot, WhatsApp (via webhook), iOS PWA, Android FCM push.
- **374/374 pytest** tests passing at launch.
- **Sovereignty modes documented**: 100 % local (Ministral on user's Mac), 100 % EU (Mistral only), or mixed performant (DeepSeek + Mistral + anonymization).
- **`feat(extension): browser companion`** *(`71bcbc6`)* — Chrome extension Sprint 0: WebSocket handshake, tab listing, DOM read, screenshot. Foundation for Sprint 0.5 and Sprint 1 that landed three days later.
- **`feat(install): bullet-proof first-time install`** *(`5fe0410`)* — install audit on a fresh `/tmp/ely-fresh-test/` sandbox surfaced 10 bugs (Python 3 detection on Mac Sequoia, hardcoded ports, password policy not documented…); all fixed in this release.
- **`feat(ui): mobile hamburger drawer`** *(`a67aedd`)* — sidebar properly collapses on screens under 768 px instead of being truncated at 64 px wide.
- **`feat(dashboard): per-user stats opened to all users`** *(`236c1af`)* — every user can see their own LLM cost/usage breakdown, no longer admin-only.
- **`feat(prompt): RÈGLE INVIOLABLE anti-confabulation`** *(`ef9c047`)* — early version of the anti-hallucination guard for factual queries.
- **`feat(desktop): 9 filesystem tools`** *(`725ce7b`)* — ELY Desktop daemon exposes read + write filesystem tools, with HITL forced on destructive operations.

### Security
- **`chore(security): harden .gitignore before public launch`** *(`da3908d`)* — extra patterns to prevent accidental commit of `.env`, `credentials.json`, `*.p8`, `*.safetensors`, vault DB.

### Fixed (right before launch)
- **`fix(auth): clear stale tokens on login + fix SameSite mismatch`** *(`470700e`)* — fresh-install testing surfaced session-expired errors on new devices; root cause in cookie SameSite policy.
- **`fix(deepseek): auto-swap to deepseek-chat for multi-turn`** *(`dbdcd90`)* — `v4-flash` and `v4-pro` reject multi-turn tool_calls with HTTP 400 unless `thinking={"type": "disabled"}` is passed.
- **`fix(name): Ely canonical spelling`** *(`cc1f103`, `966a72a`)* — agreed in May 2026 to standardise on "Ely" (no accent), pronounced "Éli". All onboarding messages and HITL notifications now use the canonical form.

---

## Pre-1.1.0 — Private development (March-May 2026)

The 200+ commits from `2026-03-09` (repo created) to `2026-05-11` (public launch) are not individually listed here. Highlights:

- **Phase 1** *(March)* — Bot Telegram integration, HITL via inline buttons, session linking via `/link` command.
- **Phase 2** *(March)* — Scheduled tasks with APScheduler, natural-language cron creation ("rappelle-moi tous les lundis à 9h").
- **Phase 3** *(March)* — Hybrid memory: SQLite FTS5 for keyword + Qdrant for semantic, time-decay weighting, automatic fact extraction.
- **Phase 4** *(March)* — Skill registry (`@register` decorator), 11 builtin skills (system, gmail, calendar, drive, docs, sheets, tasks, scheduler, météo, actualités, traduction).
- **Phase 5** *(March-April)* — Server-side Playwright browser control with per-user isolation, 7 tools, HITL on click/fill.
- **Phase 1bis** *(April)* — Slack, Discord, WhatsApp channels; agentic RAG; CI/CD.
- **Phase 2bis** *(April)* — Security marketplace, audit logging, skills marketplace foundations.
- **Phase 3bis** *(April)* — Voice wake "Éli", WebSocket `/ws/voice`, iOS SwiftUI app.
- **Phase 4bis** *(April)* — Mode Arena (ELO), agentic RAG v2, PWA.
- **Hermes Chantier 1** *(2026-05-07)* — sticky toolset profile per conversation + 13 fixes — 198 tests.
- **Hermes Chantiers 2, 4, 9, 10 partial** *(2026-05-08)* — prompt cache + frozen memory, transparent fallback chain, iteration budget + force_summary, toast UI on provider.switched — 340 tests.
- **Sovereignty stack 100 % Mistral pivot** *(2026-05-09)* — abandoned xLAM-2 8B (tool-call confabulation), validated Ministral 3B local + Mistral Small 4 + Mistral Large 3.

For the full pre-launch history, see `git log --pretty=format:"%h %ai %s" --until="2026-05-11"`.

---

## Reporting a bug

ELY ships without telemetry — this is deliberate. We will not silently collect usage data, error reports, or any signal from your installation. The flip side: we can't see your bugs from here.

If you spot a regression or hallucination, please open an [issue](https://github.com/franckolv-dev/ElyAgent/issues/new?template=bug_report.yml) with the new bug-report template (it asks for the model shown in the HUD at the time of the bug — critical for fallback-chain diagnostics).

For security-sensitive issues, do **not** open a public issue. See [`SECURITY.md`](./SECURITY.md) and e-mail `contact@agent-ely.fr`.

---

## Versioning policy

ELY follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html), adapted to a self-hosted personal AI agent:

- **Major (`x`.0.0)** — breaking change to the user's data, configuration, or API surface. Example: v2.0 will ship the LoRA-personnel-par-user feature, which changes how the LLM is stored on disk.
- **Minor (1.`x`.0)** — new capabilities or sprints from the [roadmap](./ROADMAP.md), backwards-compatible.
- **Patch (1.1.`x`)** — bug fixes, documentation, security hardening; no behaviour change beyond fixing what was broken.

The roadmap target-versions table tracks which sprint lands in which version.
