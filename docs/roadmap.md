# ELY Agent — Roadmap

## Statut actuel — 2026-03-23
✅ Phase 1 : Bot Telegram
✅ Phase 2 : Tâches planifiées (cron)
✅ Phase 3 : Mémoire hybride (FTS5 + Qdrant)
✅ Phase 4 : Architecture plugins/skills
✅ Phase 5 : Contrôle navigateur (Playwright)

**Revue de code complète effectuée le 2026-03-23 :**
- Corrigé : `all_tools` évalué trop tôt au démarrage
- Corrigé : `HITLManager.pop()` maintenant dans `finally`
- Corrigé : appels Qdrant synchrones wrappés dans `asyncio.to_thread()`
- Corrigé : gestion `json.JSONDecodeError` dans WebSocket handler
- Corrigé : avertissement utilisateur si suppression message `/link` Telegram échoue
- Corrigé : isolation d'erreur DB dans le handler d'erreur du scheduler
- Corrigé : captures d'écran browser avec timestamp (plus d'écrasement)

---

## Analyse comparative : ELY vs OpenClaw (330K stars, MIT)

### Ce qu'OpenClaw fait exceptionnellement bien

| Fonctionnalité | OpenClaw | ELY | Priorité |
|---|---|---|---|
| Multi-canal (Telegram, WhatsApp, Signal, Slack, Discord, iMessage...) | 20+ canaux | Web uniquement | **P1** |
| Tâches planifiées (cron) | 76 fichiers, sub-agents | Aucun | **P2** |
| Mémoire hybride (vecteur + FTS + décroissance temporelle) | SQLite-vec + multi-provider embeddings | Qdrant (vecteur seul) | **P3** |
| Architecture de plugins/skills | 52 skills découplés | Outils en dur | **P4** |
| Contrôle navigateur (Playwright/CDP) | 133 fichiers | Aucun | **P5** |
| Apps natives (macOS, iOS, Android) | Swift + Kotlin | Tailscale web | Futur |
| Multi-session / sub-agents | Oui | Non | Futur |

### Ce qu'ELY fait et qu'OpenClaw ne fait PAS (ou mal)

| Fonctionnalité | ELY | OpenClaw |
|---|---|---|
| **Sécurité** (HITL, anonymisation, contraintes apprises) | Architecture sécurisée par design | 288 alertes de sécurité GitHub |
| **Google Workspace natif** (Gmail, Calendar, Docs, Sheets, Tasks, Drive) | Intégration complète | Skills séparés, partiel |
| **Mémoire évolutive** (résumés auto + profil utilisateur) | Oui, Qdrant + summarisation | Fichier-centrique |
| **TTS natif** | Oui (edge-tts) | Plugin séparé |
| **HITL avec apprentissage** | Contraintes de sécurité persistantes | Approval simple |

---

## Plan d'implémentation

### Phase 1 — Bot Telegram (canal alternatif)
**Statut : ✅ FAIT**

- [x] Bot Telegram via `python-telegram-bot` (async)
- [x] Whitelist de Telegram user IDs liés aux comptes ELY
- [x] Routage vers le même agent graph (mêmes outils, mêmes filtres)
- [x] HITL via boutons inline Telegram (Approve / Deny / Ban)
- [x] Configuration du bot token via Admin UI (pas .env)
- [ ] Support voix (messages vocaux → transcription → agent)

### Phase 2 — Tâches planifiées (cron)
**Statut : ✅ FAIT**

- [x] Modèle DB `scheduled_tasks` (user_id, cron_expression, prompt, channel, enabled)
- [x] Service cron en background (APScheduler ou custom)
- [x] Exécution de prompt planifié via l'agent
- [x] Livraison des résultats sur le canal d'origine (web, Telegram)
- [x] UI de gestion des tâches (créer, modifier, activer/désactiver)
- [x] Commandes naturelles : "rappelle-moi tous les lundis de..."

### Phase 3 — Recherche hybride mémoire
**Statut : ✅ FAIT (2026-03-22)**

- [x] SQLite FTS5 en complément de Qdrant (`app/services/fts_store.py`)
- [x] Recherche hybride : score sémantique + keyword score + FTS boost
- [x] Décroissance temporelle (les souvenirs récents pèsent plus)
- [x] Extraction automatique de faits structurés (profil utilisateur en fin de session)
- [ ] Multi-provider embeddings avec fallback (dimension mismatch — à résoudre en v2 avec migration Qdrant)

### Phase 4 — Architecture de plugins/skills
**Statut : ✅ FAIT (2026-03-23)**

- [x] `Skill` dataclass standard (nom, display_name, description, icon, scopes, tools, version, author)
- [x] `SkillRegistry` singleton avec `register()`, `all_tools`, `get_user_active_tools()`, `skills_summary()`
- [x] Chargement dynamique : `register_all()` dans `app/skills/builtin/__init__.py`
- [x] 8 skills existants wrappés : system, gmail, calendar, drive, docs, sheets, tasks, scheduler
- [x] 3 nouveaux skills packagés :
  - 🌤️ Météo — wttr.in JSON API, prévisions J+1 à J+3, sans clé API
  - 📰 Actualités — Google News RSS, recherche par sujet, multilingue, sans clé API
  - 🌐 Traduction — MyMemory API, 50+ langues, noms de langue en français acceptés, sans clé API
- [x] `SkillPreference` DB model : enable/disable par utilisateur
- [x] `GET /skills/` et `PUT /skills/{name}` — REST API avec auth
- [x] `nodes.py` utilise `get_skill_registry().all_tools` (plus de liste hardcodée)
- [x] System prompt dynamique : liste les skills disponibles via `registry.skills_summary()`
- [x] SDK clair : créer un fichier dans `app/skills/builtin/`, appeler `register()`, importer dans `__init__.py`

### Phase 5 — Contrôle navigateur
**Statut : ✅ FAIT (2026-03-23)**

- [x] `BrowserManager` — Playwright Chromium headless, un contexte isolé par utilisateur
- [x] Sandboxing : pas de cookies partagés, pas de profil utilisateur, storage_state=None
- [x] 7 outils intégrés dans le skill 🌍 Navigateur web :
  - `browser_navigate`    — charger une URL, extraire le contenu principal (5 000 car. max)
  - `browser_search_web`  — recherche DuckDuckGo, retourne titres + snippets + URLs
  - `browser_get_text`    — extraire le texte d'un sélecteur CSS précis
  - `browser_screenshot`  — capture d'écran → fichier `/tmp/ely_browser_{user_id}.png`
  - `browser_click`       — cliquer un élément (HITL obligatoire)
  - `browser_fill`        — remplir un champ (HITL obligatoire)
  - `browser_close`       — libérer la session navigateur
- [x] Extraction intelligente : priorité article > main > .content > body, scripts/nav supprimés
- [x] `browser_click` + `browser_fill` dans `ALWAYS_CRITICAL_TOOLS` (validation humaine)
- [x] user_id injecté automatiquement via `InjectedToolArg` pour isolation par utilisateur

---

## Objectifs long terme

- **WhatsApp** via WhatsApp Business API
- **App Android native** (Kotlin) avec push notifications
- **Multi-agent** : ELY peut déléguer des sous-tâches à des agents spécialisés
- **Marketplace de skills** communautaire
- **Dashboard analytics** : usage, coûts LLM, interactions par jour

---

## Idées post-launch — feuille de route

### Onboarding conversationnel (proposé 2026-04-30 par Franck)

**Idée** : au premier login, Éli initie une conversation guidée pour apprendre
le vocabulaire et les habitudes de l'utilisateur. Évite les approximations
quand le user dit "mes mailings" ou "mes achats" et que ces termes ne sont
pas dans le dictionnaire générique.

**Architecture proposée** :

```
backend/
├── models/user.py               # + onboarding_completed_at
├── models/user_vocabulary.py    # NEW table (user_term ↔ canonical_term)
├── services/onboarding.py       # NEW — séquence de questions structurée
└── routers/onboarding.py        # NEW — REST API + WebSocket trigger

frontend/
└── components/OnboardingChat.tsx  # NEW — surcouche du chat normal
```

**Questions clés à poser** :
1. "Comment veux-tu que je t'appelle ?"
2. "Concise ou détaillée ?"
3. "Quelles catégories utilises-tu dans ta boîte mail ? (texte ou capture d'écran)"
4. "As-tu plusieurs calendriers (perso/pro/famille) ? Comment les nommes-tu ?"
5. "Y a-t-il des mots que j'ai besoin d'apprendre ? (ex: 'mes mailings' = newsletters)"
6. "Une routine quotidienne à mettre en place ? (briefing matin, etc.)"
7. "Des règles strictes à respecter ? (toujours HITL pour X, jamais Y, etc.)"

**Bonus** : support capture d'écran via tier IMG (Gemma 4 21B REAP / Qwen 3 VL Plus).
Éli analyse la sidebar Gmail/Drive et liste les libellés détectés pour confirmation.

**Injection à l'inférence** :
À chaque tour, le system prompt est enrichi avec :
```
## Vocabulaire personnel de cet utilisateur :
- "mes mailings" = newsletters
- "boulot" = calendrier "Travail Pro"
- "ELY-Test" = libellé Gmail personnalisé
```

**Estimation** :
- MVP (texte seulement, stockage memory_manager existant) : ~3h
- Full (table dédiée, capture d'écran, UI séparée, possibilité de réviser) : ~1-2 jours

**Status** : à démarrer post-launch, sans doute MVP en premier puis Full V2.

### Refacto session (déjà mentionné précédemment)

- `settings/page.tsx` ~2200 lignes → split par tab
- `supervisor.py` ~1200 → routing.py / dispatch.py / graph_builder.py
- `main.py` lifespan → `app/bootstrap/`
- Prompts agents en Jinja2 templates externes (`app/agent/prompts/*.j2`)

### i18n vague 4

- `admin/CreateUserForm.tsx` — laissé en FR (out of scope vague 3)

### System prompts en EN (post-launch)

- Tous les prompts (`_PLANNER_SYSTEM`, `_ACT_SYSTEM`, `_EVAL_SYSTEM`, sub-agents)
  réécrits en EN avec instruction finale `Reply in {user_language}`
- Économie tokens + meilleure précision tool-calling
- Risque de régression — à faire avec tests parallèles avant switch
