# Sprint 2.5 — Mémoire cognitive multi-typée (V1)

> **Statut** : V1 livrée le 2026-05-21 sur la branche
> `feature/sprint-2.5-memory-cognitive`. Suite de tests : **652 verts**
> (574 baseline + 78 ajoutés par les 8 jalons).
>
> Cette note acte ce qui a été livré, l'architecture finale, et fixe la
> baseline post-V1 pour les comparaisons futures (Sprint 2.5 V2 + Sprint 3.7).

## TL;DR

Le pivot décidé pendant le sprint :

- **Mémoire typée** plutôt qu'un blob unique. 5 types : `EPISODIC`,
  `SEMANTIC_USER`, `PROCEDURAL`, `ERROR`, `CONSTRAINT`.
- **API unifiée** `memory_recall(memory_type, query, user_id, limit)`
  → `list[MemoryHit]`. AUTO fan-out parallèle disponible.
- **Routing explicite à l'écriture** — chaque tool d'écriture dit où
  il écrit, dans le code, au-dessus de l'appel `store_*`.
- **Clean slate** plutôt que migration heuristique des 799 entrées
  prod (cf. §5).
- **Maintenance agent event-driven** sur fin de conversation
  (Ministral 3B local), en parallèle du cron nightly existant.
- **Pin du bug "BASE VIDE"** : test E2E qui rejouera la scène du
  2026-05-20 à chaque CI run.

## Jalons livrés

| # | Sujet | Commit | Tests cumulés |
|---|---|---|---|
| 1 | Schémas SQL (`procedures`, `error_log`, `recall_count`) | `736ccdf` | 574 |
| 2 | Split `MemoryManager` → 5 stores typés | `d18071d` | 574 |
| 3 | `MemoryRecallService` + tool `memory_recall` | `adb7124` | 594 |
| 4 | Routing explicite à l'écriture | `bd58c0c` | 602 |
| 5 | Script clean-slate (snapshot + wipe Qdrant) | `fe29381` | 606 |
| 7 | Legacy tools wrappés en alias deprecated | `2525ea8` | 613 |
| 6 | Maintenance agent rapide (Ministral 3B) | `7af40de` | 646 |
| 8 | Tests E2E + cette note | _en cours_ | **652** |

Le `_time_decay` fix qui clôt le bug "BASE VIDE" du 2026-05-20 avait
été poussé séparément sur `main` la veille (`4ad6e19`, 13 tests dédiés
dans `test_memory_time_decay.py`).

## Architecture finale

### Couche stores (`backend/app/services/memory/`)

```
memory/
├── _infra.py          MemoryInfra (Qdrant client + fastembed encoder + LRU cache)
├── _base.py           BaseStore (search_hybrid, rerank, time_decay, keyword_score)
├── _constants.py      Noms Qdrant collections + dim vecteur + stop-words
├── _deprecated.py     log_deprecation() one-shot per process
├── constraint_store.py    security_constraints (no decay)
├── episodic_store.py      interactions (Q&A pairs, λ=0.05)
├── semantic_user_store.py memories + user_profile (facts + preferences)
├── procedural_store.py    NEW V1 stub — populated in V2
├── error_store.py         NEW V1 write-only — read path en Sprint 3.7
├── recall_service.py      MemoryRecallService — fan-out + dispatch
├── types.py               MemoryType enum + MemoryHit dataclass
├── maintenance_rapid.py   MaintenanceAgentRapid event-driven
└── ROUTING.md             Mapping tool → store + Jalons 4/6/7 doc
```

### Surface publique pour le code applicatif

- **Lecture** (toujours) :
  ```python
  from app.services.memory import get_memory_recall_service, MemoryType
  hits = await get_memory_recall_service().recall(
      memory_type=MemoryType.SEMANTIC_USER,
      query="...",
      user_id="...",
      limit=5,
  )
  ```

- **Écriture typée** (Jalon 4) :
  ```python
  from app.services.memory import (
      get_constraint_store,
      get_episodic_store,
      get_semantic_user_store,
      get_procedural_store,
      get_error_store,
  )
  await get_semantic_user_store().store_fact(content, user_id, ...)
  await get_semantic_user_store().store_preference(text, user_id)
  await get_constraint_store().store(rule, user_id)
  # error/procedural stores arrivent en Sprint 3.7 / Sprint 2.5 V2
  ```

- **LangChain tool exposé au LLM** : `memory_recall(query, memory_type, limit)`.

### Compatibilité ascendante

- Le legacy `MemoryManager` (`app/services/memory_manager.py`) est
  maintenu comme **facade délégant** vers les nouveaux stores. Les
  49 call sites historiques continuent de fonctionner.
- Trois tools legacy (`memory_search`, `memory_recent`,
  `search_past_conversations_tool`) émettent un log `DEPRECATION`
  une fois par process et restent fonctionnels.
- `memory_search` délègue à `MemoryRecallService.recall(SEMANTIC_USER)`
  pour qu'il n'y ait **qu'un seul** code path de recall (pas de drift).
- Suppression définitive de la facade + des wrappers prévue en V2 ou V3.

## Décision clé : clean slate

Le 2026-05-21 (avec Franck), pivot de la migration heuristique des
799 entries Qdrant vers un wipe complet. Raisons :

1. Bugs structurels accumulés (725/799 sans `category`, mix float/ISO
   sur `created_at`, pas de dedup avant 2026-05-09, hallucinated
   self-limitations stockées comme constraints, sessions de bench
   interleaved).
2. Heuristique de classification ~70% de précision → ~250 entries
   `migrated_uncertain` polluant le cron de maintenance.
3. Franck est encore seul user — fenêtre rare pour wiper proprement.

**Action utilisateur** : exécuter
`backend/scripts/wipe_memory_for_sprint_2_5.py --confirm` (dry-run par
défaut). Snapshot Qdrant côté serveur avant chaque suppression, hard
fail si le snapshot rate.

## Pin du bug "BASE VIDE" (2026-05-20)

`tests/test_memory_e2e_sprint_2_5.py` contient deux tests qui
rejoueront le scénario chaque CI run :

- `test_time_decay_accepts_iso_string_from_production_payload` :
  pin direct de `_time_decay` sur les deux formats ISO observés en prod.
- `test_memory_recall_does_not_return_empty_on_iso_string_payloads` :
  pin end-to-end — un payload Qdrant avec `created_at` en ISO string
  doit surfacer comme `MemoryHit` à travers `memory_recall`, pas être
  silencieusement avalé par un `unsupported operand`.

## Métriques observées en V1

| Métrique | Valeur |
|---|---|
| Lignes ajoutées (8 jalons) | ~3 400 |
| Lignes supprimées (refactor) | ~560 |
| Nouveaux fichiers Python | 14 |
| Nouvelles suites de tests | 5 |
| Tests ajoutés | 78 |
| Tests totaux post-V1 | 652 |
| Temps suite pytest complète | ~8 s |
| Tests intégration Qdrant réels | 0 (tous mockés à la limite du store) |

## Failles connues et plan V2

**Iteration 1 du prompt d'extraction (2026-05-21, post-validation live)** :
le premier prompt (modélisé sur l'existant `extract_and_store_facts`)
faisait sur-extraire Ministral 3B — sur une conv tisane hibiscus, 8 des
10 « préférences » stockées étaient en réalité du contexte ponctuel
de la conv (« demande des nuances sur les saveurs », « veut des étapes
structurées »). Prompt durci avec 3 ajouts : règle explicite *« une
préférence doit s'appliquer à TOUTES les conversations futures »*, fallback
*« en cas de doute → context »*, et 6 exemples positifs/négatifs littéraux
issus de la conv hibiscus observée. À ré-évaluer en usage réel sur ~10
conversations avant Sprint 2.5 V2.

Pas dans V1 :

- `ProceduralStore.get_relevant` retourne `[]` (le store est wiré, pas
  alimenté). Jalon V2 : harvester les missions réussies après HITL OK.
- `ErrorStore.store` écrit mais aucune lecture exposée. Sprint 3.7
  consommera la table pour l'auto-réflexion.
- `memory_recall(ERROR)` retourne `[]` (write-only en V1).
- Le `filter` argument de `memory_recall` est accepté mais ignoré.
  Implémentation V2 : filter par date, par `kind=preference|fact`, etc.
- Les notes (`notes_*` tools, table SQL distincte) restent gérées en
  parallèle des stores typés. Intégration V2 : `notes_*` →
  `SemanticUserStore` sous-section "notes".
- Pas de scoring `recall_count` exploité par le cron — les colonnes
  ont été ajoutées (Jalon 1) mais le cron `consolidate_user_memory`
  n'en tire pas encore parti. V2 : reprendre l'inspiration `dreaming`
  d'OpenClaw (§11 de la design note).

## Pour reprendre la branche

```bash
git checkout feature/sprint-2.5-memory-cognitive
cd backend && uv run pytest -q  # 652 verts attendus

# Avant de toucher la prod :
cd backend && uv run python scripts/wipe_memory_for_sprint_2_5.py           # dry-run
cd backend && uv run python scripts/wipe_memory_for_sprint_2_5.py --confirm # live
```

Design note interne : `docs/external-references/sprint-2.5-memory-cognitive-multi-typed.md`
(gitignored, local sur le poste de Franck).
Audit d'origine : `docs/audits/memory-audit-2026-05-20.md`
(gitignored aussi — local).
Routing tool → store : voir [ROUTING.md](ROUTING.md) dans ce dossier.
