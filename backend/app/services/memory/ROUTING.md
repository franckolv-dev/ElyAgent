# Sprint 2.5 — Routing à l'écriture (mémoire cognitive multi-typée)

> **Principe** (design note §5) : chaque tool qui écrit en mémoire **dit
> explicitement** où il écrit, dans le code, avec un commentaire bloc
> immédiatement au-dessus de l'opération. Pas de routage inféré
> silencieux. Si un nouveau tool d'écriture est ajouté sans cible
> explicite, le test `test_explicit_write_routing.py` doit échouer.

## Mapping tool → store

| Tool (LangChain)           | MemoryType       | Store                          | Stockage physique                                | Décay |
|----------------------------|------------------|--------------------------------|--------------------------------------------------|-------|
| `memory_archive`           | `SEMANTIC_USER`  | `SemanticUserStore.store_fact` | Qdrant `memories`                                | λ=0.01 |
| `save_user_preference`     | `SEMANTIC_USER`  | `SemanticUserStore.store_preference` | Qdrant `user_profile` (dedup ≥ 0.88)       | aucun |
| `save_constraint`          | `CONSTRAINT`     | `ConstraintStore.store`        | Qdrant `security_constraints`                    | aucun |
| `notes_create`             | `SEMANTIC_USER`  | (V2 — `SemanticUserStore.store_note`) | SQLite `notes` table                       | aucun |
| `notes_update` / `delete`  | `SEMANTIC_USER`  | (V2) SQLite `notes` table — édition directe | —                                       | — |
| (interne) `store_interaction` | `EPISODIC`    | `EpisodicStore.store`          | Qdrant `interactions`                            | λ=0.05 |
| (Sprint 3.7) `error_log`   | `ERROR`          | `ErrorStore.store`             | SQL `error_log` (rétention 90j)                  | n/a |
| (Sprint 2.5 Jalon 6) procédural | `PROCEDURAL`| `ProceduralStore.store` (V2)   | SQL `procedures` + Qdrant `procedures`           | aucun |

## Patterns interdits

### ❌ Routage inféré (avant Sprint 2.5)

```python
# Mauvais — le tool ne dit pas quel type il vise
memory = get_memory_manager()
await memory.store_memory(content=fact, user_id=user_id)
```

Le caller n'a aucune idée que ce `store_memory` finit dans la collection
`memories`. Pour comprendre il faut suivre `MemoryManager.store_memory`
→ `SemanticUserStore.store_fact` → `_COLLECTION_MEMORIES`.

### ✅ Routage explicite (Sprint 2.5+)

```python
# Sprint 2.5 Jalon 4 — routing explicite:
#     MemoryType  = SEMANTIC_USER (kind=fact)
#     Store       = SemanticUserStore.store_fact
#     Collection  = Qdrant `memories` (λ=0.01)
#     Rationale   = stable user knowledge, retrievable on demand
await get_semantic_user_store().store_fact(content=fact, user_id=user_id)
```

Un seul `grep "Jalon 4 — routing"` retrouve toutes les écritures mémoire
et leur cible.

## Tools deprecated (Sprint 2.5 Jalon 7)

Ces tools restent fonctionnels pour la rétrocompat mais émettent un
`DeprecationWarning` côté logger Python à la première invocation par
process. Ils seront supprimés en Sprint 2.5 V2 ou V3.

| Tool legacy                       | Remplacé par                                 | Délégation interne ?                     |
|-----------------------------------|----------------------------------------------|------------------------------------------|
| `memory_search`                   | `memory_recall(memory_type="semantic_user")` | Oui — délégué à `MemoryRecallService`    |
| `memory_recent`                   | `memory_recall` (V2 ajoutera le filtre)      | Non — logique scroll Qdrant conservée    |
| `search_past_conversations_tool`  | `memory_recall(memory_type="episodic")` (V2) | Non — implémentation Sprint 1 conservée  |

Le helper `log_deprecation(tool_name, successor=...)` dans
`app/services/memory/_deprecated.py` log une fois par process et par
tool, pour éviter le spam.

## Maintenance agent rapide (Jalon 6)

Fire-and-forget sur fin de conversation (WS disconnect → `chat.py`) :
`MaintenanceAgentRapid.consolidate(conversation_id, user_id)` (dans
`app/services/memory/maintenance_rapid.py`).

- Charge les ~20 derniers messages SQL de la conv
- Tier MAINTENANCE (Ministral 3B local par défaut) → JSON 3–5 facts max
- Dispatch typed sur le bon store :
  - `type=preference` → `SemanticUserStore.store_preference` (no decay, dedup)
  - autres types (`context|event|skill|personal`) →
    `SemanticUserStore.store_fact` avec `extra_payload={"category": ftype,
    "source": "maintenance_rapid"}`

Skip via env `MAINTENANCE_RAPID_DISABLED=true` sur hardware faible.
Le cron nightly `consolidate_user_memory` (niveau 2) reste branché en
parallèle pour la mémoire SQL legacy — les deux paths coexistent
pendant la transition V1, le legacy disparaîtra en V2 ou V3.

## Comment ajouter un nouveau tool d'écriture

1. Choisir le **MemoryType** (cf. design note §2 : 5 types disponibles).
2. Récupérer le store typé via le bon accessor :
   - `get_semantic_user_store()`
   - `get_constraint_store()`
   - `get_episodic_store()`
   - `get_procedural_store()`
   - `get_error_store()`
3. Coller le bloc de commentaire ci-dessus, au-dessus de l'appel `store_*`.
4. Ajouter une ligne dans la table en haut de ce fichier.
5. Le test `test_explicit_write_routing.py` doit rester vert.

## Pourquoi pas un dispatcher central ?

On a délibérément **pas** introduit un service `MemoryWriteService.write(type, payload)`
parce que :

- Chaque type a une signature de payload différente (un fait ≠ une contrainte ≠ une
  procédure). Un dispatcher générique aurait un `**kwargs` qui casse le type-safety.
- L'objectif Sprint 2.5 est de rendre le routage *visible*, pas de l'abstraire à
  nouveau. Un dispatcher central re-cache l'information.
- LangChain tools n'ont pas besoin d'un facade : un tool a déjà sémantique claire
  (`memory_archive`, `save_user_preference`), il sait toujours quel type il vise.
