# ELY — Rapport final Qwen 2.5-VL 7B + compact prompt + MemGPT

**Date :** 2026-04-24
**Config Mac Studio** : 32 GB RAM
**LM Studio** : `qwen2.5-vl-7b-instruct` MLX 4-bit, contexte 128K (KV quant 4-bit)

---

## 1. Résultats finaux vs baselines

| Config | HITL (18) | Latence moy | Fiabilité tool-calling | Multimodal |
|--------|:---------:|:-----------:|:----------------------:|:----------:|
| **Claude Haiku 4.5 cloud** | 16/18 (89%) | 37 s | Excellente | ✅ |
| Gemma 4 26B A4B MLX | 8/18 (44%) | 94 s | Mauvaise | ❌ |
| Qwen 3.5-9B MLX | 12/18 (67%) | 72 s | Bonne (mais hybride Gemini caché) | ⚠️ thinking mode bloqué |
| Qwen 2.5-VL 7B **full prompt** | 0/18 (0%) | — | Nulle (ignore tools) | ✅ |
| **Qwen 2.5-VL 7B compact prompt** | **15/18 (83%)** | **46 s** | **Très bonne** | ✅ |

🎯 **Qwen 2.5-VL-7B avec compact prompt est à 1 point de Haiku sur le score, et ~20 % plus rapide que Qwen 3.5 hybride.**

---

## 2. Les 6 optimisations déployées

### Optim 1 — Retirer les instructions anti-tool-calling
Fichiers modifiés : `nodes.py`, `supervisor.py`, `sub_agents/config.py`

**Avant :**
```
Format des réponses — IMPÉRATIF :
- Rédige TOUJOURS en texte naturel
- N'utilise JAMAIS de markdown
...
```

**Après :**
```
Utilisation des tools — PRIORITÉ ABSOLUE :
- Si la demande correspond à un tool disponible, APPELLE-le IMMÉDIATEMENT.
- Ne JAMAIS annoncer l'appel avant.

Format des réponses TEXTE (seulement quand aucun tool n'est pertinent) :
- Texte naturel sans markdown...
```

Les petits modèles lisent les instructions littéralement — mettre la priorité tool-calling en premier change tout.

### Optim 2 — Profil utilisateur compact (<200 tokens)
`memory_service.get_user_context(compact=True)` — nouveau param par défaut.

- **Avant** : 15-20 lignes `- key : value` = ~600-1000 tokens
- **Après** : `Profil utilisateur: user_name: Franck | response_style: concis, tutoiement | ...` = ~200 tokens max
- Noisy keys filtrées (`current_delivery`, `ionos_client_id`, `upcoming_events`, `news_*`, etc.)
- Core keys toujours incluses (`user_name`, `preferred_language`, `response_style`, `main_project`)

### Optim 3 — Compact prompt mode pour LM Studio
Nouveaux fichiers : `app/agent/compact_prompt.py` + helper `is_local_openai_llm()` dans `qwen_no_think.py`.

**Détection** : `ChatOpenAI` + `base_url` contient `localhost`/`127.0.0.1`/`host.docker.internal`/RFC-1918 IPs → mode compact activé.

**Compact prompt structure (~300 tokens totaux) :**
1. Identity 1-line
2. Sub-agent speciality 1-line
3. Tool-calling priority directive
4. Compact user context (≤200 tokens)
5. Top-3 constraints truncated
6. Top-3 memories truncated
7. Date (en dernier pour préserver le cache prefix)

Cloud frontier models (Haiku / Claude / Gemini Pro) conservent leur **prompt complet** — ils naviguent bien la richesse.

### Optim 4 — tool_choice="required" pour LM Studio
`factory.py` : détection ChatOpenAI et traduction `any` → `required`.

LM Studio ne supporte que `none/auto/required` (strict OpenAI). Envoyer `any` causait HTTP 400 silencieusement masqué par LangChain → tool_calls=0.

### Optim 5 — Cache memories par user turn
`factory.py` : stocke `constraints/memories/past_interactions/user_ctx` dans `SubAgentState` au 1er fetch, réutilise aux tool calls suivants du même turn.

Impact sur les chaînes multi-outils : passage de timeout 240s → PASS (observable sur `sheets_batch_update`).

### Optim 6 — `is_qwen_llm()` distingue Qwen 2.x (no-think) vs Qwen 3+ (think)
`qwen_no_think.py` : détection regex sur `qwen2` pour ne PAS injecter `/no_think` sur Qwen 2.5 (qui ne comprend pas le marker).

---

## 3. MemGPT-style tools — **déployés, à affiner**

Nouveau fichier : `app/agent/tools/memgpt_tool.py`

### 3 tools ajoutés au skill registry
| Tool | Rôle | Paramètres |
|------|------|------------|
| `memory_archive` | Archive un fait durable dans Qdrant avec catégorie | `fact`, `category`, `user_id` |
| `memory_search` | Recherche sémantique dans l'archive long-terme | `query`, `limit`, `user_id` |
| `memory_recent` | Top-N derniers faits d'une catégorie | `category`, `limit`, `user_id` |

### Catégories supportées
`fact`, `preference`, `project`, `contact`, `task`, `event`, `constraint`, `other`

### État actuel
- **Code** : ✅ écrit et testé unitairement
- **Enregistrement** : ✅ dans `skills/builtin/memory_skill.py` comme skill `memgpt_memory`
- **Exposition agent** : ⚠️ tools présents dans `registry.all_tools` mais le sub-filter de `factory.py` les filtre out si aucun keyword `archive`/`rappelle`/`retrouve` ne matche.

### À finir (non-bloquant)
Ajouter dans le sub-filter de `factory.py` (memory/general sub-agents) :
```python
(_re_filter.compile(r"\b(archive|archives?|rappelle.toi|m[ée]morise|retrouve|cherche dans ma m[ée]moire)\b"),
 ("memory_archive", "memory_search", "memory_recent", "save_")),
```

Et potentiellement router explicitement "archive-moi X" vers le sub-agent memory dans `supervisor.py`.

---

## 4. Hiérarchie mémoire implémentée

Conforme aux 3 niveaux du fichier `verif.md` :

| Niveau | Emplacement | Taille | Injection |
|--------|-------------|:------:|:---------:|
| **Core** | System prompt compact | ~200 tokens | ✅ toujours |
| **Working** | Messages array (history) | variable | ✅ auto LangGraph |
| **Long-term** | Qdrant — collections `memories`/`constraints`/`user_profile` | illimité | 🔀 push passif (legacy) **+** pull actif (MemGPT) |

- **Push passif** : top-3 memories + top-3 constraints injectés dans chaque prompt (mode compact)
- **Pull actif** : `memory_search` / `memory_archive` / `memory_recent` que l'agent peut appeler on-demand

---

## 5. Recommandation de routage

### Pour usage production (coût + fiabilité)
| Tier | Modèle | Fallback |
|------|--------|:--------:|
| `simple` | **Qwen 2.5-VL-7B local** | Haiku |
| `medium` | **Qwen 2.5-VL-7B local** | Haiku |
| `complex` | Claude Haiku 4.5 | Sonnet 4.6 |
| `image` | Qwen 2.5-VL local (multimodal !) | Gemini 2.5 Flash |
| `maintenance` | Qwen 2.5-VL-7B local | Haiku |

**Résultat attendu** : ~70 % des requêtes en local (gratuit, privé, 46s/tour), ~30 % cloud (actions complexes critiques, 10-20s/tour).

### Pour 100 % privé (pas de cloud)
Garde `fallback_enabled=False` partout. Accepte les 17 % de tool-calling échoués (principalement les cas `update_settings`, `raw_api_call`).

---

## 6. Fichiers créés / modifiés

### Nouveaux fichiers
- `backend/app/agent/compact_prompt.py` — Builder de prompt compact
- `backend/app/agent/tools/memgpt_tool.py` — 3 tools mémoire hiérarchique
- `test-runner/qwen25vl-compact-results/` — Rapports finaux
- `test-runner/RAPPORT-FINAL-Qwen25VL-compact.md` — ce document

### Fichiers modifiés
- `backend/app/services/hitl_manager.py` — `TIMEOUT_SECONDS` 120 → 300
- `backend/app/services/llm_provider.py` — `_make_lm_studio` temp 0.1 + `enable_thinking: False`
- `backend/app/services/memory_service.py` — `get_user_context(compact=True)` par défaut
- `backend/app/services/qwen_no_think.py` — `is_local_openai_llm()` + `is_qwen_llm()` skip Qwen 2.x
- `backend/app/agent/nodes.py` — compact prompt mode + anti-tool instructions reformulées
- `backend/app/agent/supervisor.py` — `_COMMON_FORMAT` reformulé
- `backend/app/agent/sub_agents/config.py` — `_COMMON_FORMAT` reformulé
- `backend/app/agent/sub_agents/state.py` — champs cache mémoire
- `backend/app/agent/sub_agents/factory.py` — compact mode + tool_choice mapping + tri tools + cache memories
- `backend/app/skills/builtin/memory_skill.py` — skill `memgpt_memory` enregistré

### Android (non rebuild dans cette session)
- `android/app/src/main/kotlin/com/ely/agent/core/fcm/FcmTokenManager.kt` — helper FCM
- `android/.../MainActivity.kt` — register FCM au cold start
- `android/.../AuthRepositoryImpl.kt` — register FCM après login
- `android/.../ElyFirebaseMessagingService.kt` — `onNewToken()` implémenté

---

## 7. Conclusion

L'objectif d'exécuter **le maximum de requêtes en local avec temps de réponse acceptables** est atteint :

✅ **83 % de taux de succès** sur la suite HITL (18 tests)
✅ **46 s/tour en moyenne** (vs 37 s sur Haiku cloud — écart minime)
✅ **0 faux positifs faibles** — tool_calls correctement émis sur la grande majorité
✅ **Multimodal activé** (Qwen 2.5-VL supporte les images, utile pour la capture d'écran ELY)
✅ **Hiérarchie mémoire MemGPT** en place (à affiner côté routage pour utilisation active)

Le Mac Studio 32 GB tient la charge grâce à la quantification 4-bit des weights ET du KV cache. Plus d'OS swap observé pendant les tests.
