# Bench `orchestrate` — protocole et scénarios

> **Objectif** : mesurer l'économie tokens et la latence apportées par
> le tool `orchestrate` (Sprint 2.7) sur des workflows multi-tool
> représentatifs. Target initial : **≥ 60% d'économie tokens médiane**.

Le bench se déroule en deux temps :

1. **Bench technique côté serveur** (automatisable, ce qui suit) —
   mesure ce que le sandbox produit pour un scénario donné : durée
   d'exécution, taille du stdout, tools effectivement dispatchés.
2. **Bench end-to-end via Ely** (manuel) — pose le même workflow à
   l'agent **avec et sans** `orchestrate` et compare ce que le LLM
   consomme en tokens.

Les deux se complètent : le premier valide le coût brut du sandbox,
le second mesure la valeur réelle vue de l'utilisateur.

---

## 1. Bench technique (automatisé)

### Lancer un scénario

Depuis la racine du repo, après avoir activé le backend :

```bash
cd backend
uv run python ../scripts/bench_orchestrate.py ../bench/scenarios/scenario_a_dev_weekly_summary.py
```

Sortie attendue : un tableau ASCII avec `duration_seconds`,
`tools_dispatched`, `stdout_tokens`, etc.

Pour récupérer du JSON parseable (utile si tu veux pousser ça dans un
fichier ou un dashboard) :

```bash
uv run python ../scripts/bench_orchestrate.py \
    ../bench/scenarios/scenario_a_dev_weekly_summary.py --json \
    > ../bench/results/scenario_a-$(date +%Y%m%d).json
```

### Scénarios disponibles

| Fichier | Tools utilisés | Workflow |
|---|---|---|
| `scenario_a_dev_weekly_summary.py` | 5 (github×2, memory_recent, search_past_conversations_tool, knowledge_search) | Résumé hebdomadaire dev croisant repo / mémoire / docs / conversations. |
| `scenario_b_memory_audit.py` | 8 (memory_recent ×7, search_past_conversations_tool) | Boucle for sur les 7 catégories de mémoire — pattern impossible pour le LLM en mode séquentiel. |
| `scenario_c_no_op_baseline.py` | 0 | Plancher du surcoût sandbox (démarrage subprocess + stubs + RPC). |

### Ce que ça mesure — et ce que ça ne mesure PAS

✅ **Mesuré** :
- Durée wall-clock d'un run sandbox
- Taille du stdout renvoyé au LLM principal (= ce qui pollue son contexte)
- Liste ordonnée des tools effectivement dispatchés
- Détection de truncation (timeout ou cap stdout)

❌ **Pas mesuré** :
- Les **tokens consommés par le LLM principal** (input/output) — il
  faudrait que ce bench appelle le LLM, ce qu'on délègue au protocole
  manuel ci-dessous.
- La **qualité** de la réponse (pertinence, hallucinations).
- Le coût $ de l'appel — dépend du tier (Mistral Large 3 ≠ DeepSeek
  v4-pro ≠ Anthropic).

---

## 2. Bench end-to-end via Ely (manuel)

L'idée : poser **la même demande** à Ely deux fois, et mesurer ce que
ça consomme.

### Préparer une question équivalente

Pour chaque scenario du bench technique, une question utilisateur qui
**naturellement** devrait déclencher le même workflow :

| Scenario | Question user typique |
|---|---|
| A | « Fais-moi le résumé hebdomadaire dev : où en est le repo GitHub, les stats de trafic 14j, mes derniers projets en mémoire, et les sujets qu'on a discutés sur Sprint 2.7. » |
| B | « Audite ma mémoire : pour chaque catégorie (faits, préférences, projets, contacts, tâches, events, contraintes), liste-moi les 3 derniers faits archivés et fais-moi une synthèse. » |
| C | (n/a — c'est le baseline) |

### Protocole de mesure

**Run 1 — Sans orchestrate** :
1. Ouvre Ely en mode tier C (Mistral Large 3 ou DeepSeek v4-pro).
2. Pose la question exactement.
3. Note dans le tableau de résultats :
   - Nombre de tool_calls effectués
   - Tokens **input** cumulés (somme des `input_tokens` des
     `usage_metadata` côté backend, visible dans les logs `info`
     « tokens.input » ou dans le dashboard d'Ely si activé)
   - Tokens **output** cumulés
   - Durée totale (de la submission jusqu'au dernier token reçu)
   - Qualité subjective (réponse correcte / approximative / fausse)

**Run 2 — Avec orchestrate forcé** :
1. Même Ely, même tier C.
2. Reformule la question pour pousser le tool :
   > « Utilise le tool `orchestrate` pour [même demande]. Écris un seul
   > script Python qui chaîne les tool_calls nécessaires. »
3. Note les mêmes métriques.

### Template du tableau de résultats

```markdown
| Scenario | Mode | Tool_calls | Tokens in | Tokens out | Durée (s) | Qualité |
|---|---|---|---|---|---|---|
| A | Sans orchestrate | … | … | … | … | … |
| A | Avec orchestrate | … | … | … | … | … |
| **Économie** | | … % | … % | … % | … % | |
```

Si tu lances le bench plusieurs fois (pour avoir un médian / une
moyenne), un fichier `bench/results/YYYYMMDD.md` par session est
parfait pour suivre l'évolution.

### Comment trouver les tokens consommés

Trois options selon ton setup :

1. **Logs backend** : grep `tokens.input` / `tokens.output` dans la
   sortie du container Docker.
2. **Dashboard Ely** (si activé dans Settings → Analytics) : section
   « consommation par conversation ».
3. **Provider direct** : tableau de bord Mistral / DeepSeek / Anthropic,
   filtré sur la conversation en cours (plus précis mais nécessite
   d'isoler la conversation des autres).

---

## Pour aller plus loin

Quand le bench technique + end-to-end aura été tourné sur 2-3 séries
de scénarios, on pourra extraire :

- Le **point d'équilibre** : à partir de combien de tool_calls
  prévus, `orchestrate` devient rentable (overhead sandbox vs. économie
  contexte). Mon estimation initiale : autour de 3-4 tool_calls.
- Le **bon nudge système** : si le LLM n'utilise pas orchestrate
  spontanément, quelle phrase ajouter à `_SYSTEM_PROMPT_BASE` pour
  déclencher le bon réflexe.
- La **stratégie d'extension** de la V1 (15 tools) : quels tools
  destructifs débloquer en priorité via l'option C HITL (cf. design
  note Hermes §4.1).
