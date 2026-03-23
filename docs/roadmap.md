# ELY Agent — Roadmap

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
**Statut : EN COURS**

- [ ] Bot Telegram via `python-telegram-bot` (async)
- [ ] Whitelist de Telegram user IDs liés aux comptes ELY
- [ ] Routage vers le même agent graph (mêmes outils, mêmes filtres)
- [ ] HITL via boutons inline Telegram (Approve / Deny / Ban)
- [ ] Configuration du bot token via Admin UI (pas .env)
- [ ] Support voix (messages vocaux → transcription → agent)

### Phase 2 — Tâches planifiées (cron)
**Statut : À FAIRE**

- [ ] Modèle DB `scheduled_tasks` (user_id, cron_expression, prompt, channel, enabled)
- [ ] Service cron en background (APScheduler ou custom)
- [ ] Exécution de prompt planifié via l'agent
- [ ] Livraison des résultats sur le canal d'origine (web, Telegram)
- [ ] UI de gestion des tâches (créer, modifier, activer/désactiver)
- [ ] Commandes naturelles : "rappelle-moi tous les lundis de..."

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
**Statut : À FAIRE**

- [ ] Intégration Playwright headless
- [ ] Outil `browser_navigate`, `browser_screenshot`, `browser_fill`, `browser_click`
- [ ] Sandboxing (profil Chrome isolé, pas d'accès aux cookies utilisateur)
- [ ] Extraction de contenu web structuré
- [ ] Cas d'usage : remplir un formulaire, scraper une page, comparer des prix

---

## Objectifs long terme

- **WhatsApp** via WhatsApp Business API
- **App Android native** (Kotlin) avec push notifications
- **Multi-agent** : ELY peut déléguer des sous-tâches à des agents spécialisés
- **Marketplace de skills** communautaire
- **Dashboard analytics** : usage, coûts LLM, interactions par jour
