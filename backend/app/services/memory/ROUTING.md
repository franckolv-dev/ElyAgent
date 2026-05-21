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
