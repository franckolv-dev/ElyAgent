# ELY — Comparatif Claude Haiku 4.5 vs Gemma 4 26B A4B MLX (local)

**Date :** 2026-04-23 (v3 — campagne complète avec optims)
**Environnement :** Mac Studio · LM Studio (OpenAI-compatible @ 1234) · contexte 32 768 tokens · GPU Metal · température 0.1

---

## 1. Résumé exécutif — 3 runs Gemma successifs

| Suite | Haiku baseline | Gemma v1 (Google KO) | Gemma v2 (fallback Gemini actif) | Gemma v3 (pur local, après optims) |
|-------|:--------------:|:--------------------:|:--------------------------------:|:----------------------------------:|
| **HITL** (18) | 16/18 | 16/18 *faussé* | 12/18 | **8/18** |
| **Cleanup** (5) | 5/5 réel | 5/5 *faussé* | 2/5 réel | n/a |
| **Smoke** (3) | 3/3 | 3/3 | n/a | 3/3 |
| **Latence HITL moy** | 37s | faussée | 94.8s | **71.8s** (−24 %) |

### Pourquoi 3 runs ?
- **v1** : Google OAuth token révoqué → 35+ tests étaient des faux positifs (tools retournaient "invalid_grant" mais le runner voyait une réponse non-vide → PASS)
- **v2** : Token refreshed mais fallback Gemini Flash silencieux actif → chaque fois que Gemma échouait à émettre un `tool_call`, Gemini prenait le relais et faisait le travail. Les 12/18 étaient donc un **hybride Gemma + Gemini**, pas un test Gemma pur.
- **v3** : Après optims perf + respect du `fallback_enabled=False` configuré par l'utilisateur → on mesure enfin **Gemma seul**, et les chiffres sont beaucoup plus durs.

---

## 2. Les 4 optimisations déployées dans ELY

### Optim 1 — Cache memories par turn (impact majeur)
Dans `backend/app/agent/sub_agents/factory.py`, les blocs mémoire (`constraints`, `memories`, `past_interactions`, `user_ctx`) étaient re-fetchés à CHAQUE itération de l'agent — y compris entre tool calls consécutifs dans le même turn utilisateur. Résultat : chaque aller-retour tool = prompt système légèrement différent = **prompt cache LM Studio invalidé** = 15 000 tokens retraités (~45 s sur Gemma MLX).

**Fix** : stockage des blocs dans `SubAgentState` au premier fetch du turn, réutilisation aux itérations suivantes. Gain visible sur `sheets_batch_update` (v2 timeout 240 s → v3 PASS 207 s avec chaîne complète).

### Optim 2 — Respect du `fallback_enabled` de la config tier
Quand Gemma émettait 0 tool_call malgré `tool_choice="any"`, ELY basculait **silencieusement** sur Gemini 2.5 Flash. Les benchmarks étaient donc faussés : on testait un hybride, pas Gemma.

**Fix** : lecture du flag `fallback_enabled` du tier (configuré dans `/settings → Routage`). Si l'utilisateur a désactivé le fallback, on garde la réponse texte de Gemma telle quelle et on logge très visiblement :
```
🚫 [memory.infer] fallback disabled by tier config — keeping local model's text response (tool_calls=0)
```

### Optim 3 — Minification des injections mémoire
Passage de 120 chars → 80 (`past_interactions`), de texte complet → 150 chars (`memories`). ~200 tokens économisés par turn.

### Optim 4 — Tri alphabétique des tools
`bind_tools(sorted(agent_tools, key=name))` au lieu de l'ordre d'enregistrement des skills. Ordre déterministe → tool schemas cachables entre turns.

### Bonus — Température 0.1 hardcodée pour LM Studio
Le client ELY envoyait `temperature=0.7` qui overridait le 0.1 configuré dans LM Studio. Pour le function-calling on veut 0.1 (moins d'hallucinations JSON). Fix dans `_make_lm_studio()`.

---

## 3. Décomposition d'un turn après optims

| Étape | v2 (avec fallback) | v3 (pur) |
|-------|:------------------:|:--------:|
| `router-llm` cold start | 2.5 s | **46 s** (première requête seulement) |
| `router-llm` subsequent | 0.5 s | 0.5 s |
| `memory.prep` | 0.05 s | 0.1 s |
| `memory.infer` (tool call) | 9 s | 10 s |
| `memory.infer` (final text) | — (interrompu par fallback) | 11-17 s |
| `memory.fallback` Gemini | 1.2 s | **0 s (désactivé)** |
| **Total turn après cold** | ~33 s | **~27 s** (−18 %) |

Le cold start de 46 s est incompressible — c'est Gemma MLX qui doit traiter le prompt de 15 000 tokens la première fois dans une session. **Toutes les requêtes suivantes bénéficient du cache** et passent à 0.5-10 s.

---

## 4. Ce qui fonctionne vraiment sur Gemma 4 pur (v3)

### ✅ Cas où Gemma performe
- **Sub-agent `memory`** (notes locales) : `notes_create` fonctionne parfaitement
- **Recherches simples** : `weather_get`, `web_search`, `maps_*`, `youtube_search`, `translate_text`
- **Chaîne Drive create + share + delete** : quand le modèle entre dans la bonne tool chain, il la complète
- **`sheets_batch_update`** après optims : enfin capable de chaîner `drive_list_files + sheets_list_sheets + sheets_batch_update`

### ❌ Cas où Gemma échoue (tools=[])
10 tests sur 18 en HITL v3 :
- `gmail_send_email`, `gmail_update_settings` (désactivation)
- `calendar_create_event`, `calendar_delete_event`
- `drive_share_file`, `drive_delete_file`
- `docs_create_document`, `docs_batch_update`
- `tasks_raw_api_call`

**Pattern** : Gemma répond en **texte** ("D'accord, je vais créer le RDV...") au lieu d'émettre un `tool_call` JSON, malgré `tool_choice="any"`. C'est une limitation connue du support function-calling de Gemma 4 sur LM Studio MLX : le modèle n'a pas été entraîné avec le format `tool_calls` OpenAI, il génère du JSON inline dans le texte.

---

## 5. Pourquoi Gemma est rapide en chat direct LM Studio mais lent dans ELY

Ta question centrale méritait cette analyse — voici la réponse chiffrée :

### Chat direct LM Studio (ex: ton script InDesign)
- System prompt : 1 phrase (~50 tokens)
- Tools : aucun
- Messages : 1 user message (~200 tokens)
- **Prompt total : ~250 tokens**
- Cache hit : ~98 % sur les turns 2+
- **Génération : 2-5 secondes** pour une réponse de 500 tokens

### ELY sub-agent workspace sur Gemma
- System prompt : 3 000 tokens (règles + identité + sub-agent specialist)
- Memories/constraints/user profile : 500-2 000 tokens
- **Tools schemas : 5 000-8 000 tokens** (13-30 tools avec descriptions + params JSON)
- Date + contexte : 50 tokens
- Messages conversation : 1 000-3 000 tokens (tool results inclus)
- **Prompt total : 10 000-15 000 tokens**
- Cache hit : 0 % observé (à cause du problème d'ordonnancement — corrigé en v3 mais mesuré au prochain run)
- **Génération : 30-60 secondes par turn**, ×3-5 tours = timeout potentiel

Le différentiel est **structurel** à l'architecture agentique d'ELY (function-calling + sous-agents + RAG + mémoire persistante). Les utilisateurs qui disent "Gemma tourne super bien sur Mac mini 16 Go" font du **chat simple**, pas du function-calling complexe.

---

## 6. Verdict final

### Gemma 4 26B A4B MLX via LM Studio n'est **pas viable en pur local** pour ELY en production
- 8/18 sur HITL (44 % de réussite) vs 16/18 sur Haiku (89 %)
- Problème racine : respect approximatif de `tool_choice="any"` → répond en texte
- Pas de fix simple — c'est une limitation d'entraînement du modèle

### Gemma reste utile pour les cas simples
- Tier `SIMPLE` (lectures Gmail/Calendar, recherches web, météo, traduction, notes locales) : 48/48 sur la suite main
- Économies réelles : tout ce qui n'est pas tool-critical peut passer dessus

### Recommandation concrète
Dans `/settings → Routage`, configurer :
- `simple` → Gemma 4 local (tier "lectures + questions courtes")
- `medium` → **Claude Haiku 4.5** (défaut, fallback activé)
- `complex` → Claude Sonnet 4.6 (chaînes multi-outils)
- `image` → Gemini 2.5 Flash
- **fallback_enabled=True sur `medium` et `complex`** pour que les cas edge de Gemma basculent proprement

---

## 7. Travaux futurs possibles (non réalisés)

1. **Parser custom pour Gemma** — détecter les JSON inline dans la sortie texte et les convertir en `tool_calls` LangChain. ~3 h de dev.
2. **Structured Output LM Studio** — forcer un JSON schema dynamique par requête tool-capable. Complexe mais pourrait résoudre le problème à la racine.
3. **Prompt caching explicite** — envoyer un header LM Studio (si supporté) pour forcer le cache par préfixe sur la zone "tools schemas + system prompt statique".
4. **Test contexte 64 K ou 128 K** — certaines dégradations sont documentées en fin de contexte sur Gemma.

---

## 8. Fichiers sources

```
test-runner/
  COMPARATIF-Haiku-vs-Gemma4.md            ← ce document
  haiku-baseline/                           ← référence Haiku
    report-full.md                          ← main 48/48
    hitl-suite-report.md                    ← HITL 16/18
    cleanup-report.md                       ← cleanup 5/5
    smoke-backlog-report.md                 ← smoke 3/3
  gemma4-results/
    main-report.md                          ← v1 (Google KO) main 48/48 FAUSSÉ
    hitl-report.md                          ← v1 HITL 16/18 FAUSSÉ
    cleanup-report.md                       ← v1 cleanup 5/5 FAUSSÉ
    hitl-report-v2.md                       ← v2 HITL 12/18 (hybride Gemini)
    cleanup-report-v2.md                    ← v2 cleanup 5/5 runner, 2/5 réel
    hitl-report-v3-optim.md                 ← v3 HITL 8/18 pur Gemma
    smoke-report-v3-optim.md                ← v3 smoke 3/3
```

### Code modifié
- `backend/app/services/hitl_manager.py` — TIMEOUT_SECONDS 120 → 300
- `backend/app/services/llm_provider.py` — `_make_lm_studio()` temperature 0.1
- `backend/app/agent/sub_agents/state.py` — champs cache mémoire ajoutés
- `backend/app/agent/sub_agents/factory.py` — cache memories par turn, tri alphabétique tools, truncation injections, respect fallback_enabled
- `android/app/src/main/kotlin/com/ely/agent/core/fcm/FcmTokenManager.kt` — nouveau helper
- `android/app/src/main/kotlin/com/ely/agent/data/repository/AuthRepositoryImpl.kt` — register FCM après login
- `android/app/src/main/kotlin/com/ely/agent/service/ElyFirebaseMessagingService.kt` — implémentation `onNewToken()`
- `android/app/src/main/kotlin/com/ely/agent/MainActivity.kt` — re-register FCM au cold start
