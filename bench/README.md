# Bench — ELY

Deux bancs d'essai cohabitent dans ce dossier :

1. **Harness de régression canonique** (`run_canonical.py`) — 50 scénarios
   déterministes qui verrouillent le contrat de chaque sous-système
   (failure_capture, mémoire cognitive, HITL, learned skills, MCP, …).
   C'est **le filet de régression** qui rend la V2 « Auto-Developing Agent »
   (génération de `@tool` Python) safe à shipper. → §1, ci-dessous.
2. **Bench tokens `orchestrate`** (`../scripts/bench_orchestrate.py`) — mesure
   l'économie de tokens du tool `orchestrate` (Sprint 2.7) sur des workflows
   multi-tool. → §2, plus bas.

---

## 1. Harness de régression canonique

### Pourquoi

La V2 génère des outils Python à la volée. Avant de promouvoir un `@tool`
généré, 4 garde-fous : (1) AST whitelist, (2) ruff + mypy, (3) sandbox eval,
(4) **ce harness de régression**. Avec 50 scénarios couvrant les sprints
majeurs, un tool généré qui casse silencieusement un sous-système (capture
d'échec, mémoire, learning report, …) est attrapé — chaque nuit (§ CI).

### Lancer

Depuis la **racine du repo** (le package `bench` y vit ; le runner ajoute
`backend/` au `sys.path` tout seul) :

```bash
# Tout le tier shallow (défaut du CI nocturne)
PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag shallow

# Plusieurs tags
PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag shallow,medium

# Tout (y compris deep = vrais appels LLM, coûte de l'argent)
PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag all

# Lister sans exécuter
PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --list
```

> ⚠️ Une **DB SQLite fichier** est requise (le défaut `cyberentity.db` suffit).
> `:memory:` casse les scénarios : il est par-connexion, donc un scénario qui
> écrit dans une session et relit dans une autre verrait une base vide.

Exit code `0` si tous les scénarios sélectionnés passent, `1` sinon (CI-ready).
Résultats écrits dans `bench/results/<timestamp>/` (`results.json` + `summary.md`).

### Tags (taxonomie)

| Tag | Sens | Coût |
|---|---|---|
| `shallow` | service-level, **aucun appel LLM**, sub-seconde | CI-cheap |
| `medium`  | chemin orchestrateur avec LLM mocké, quelques secondes | CI-ok |
| `deep`    | vrai appel LLM (budget capé), dizaines de secondes | **exclu du nocturne** — à lancer à la main avant une release |

Un scénario sans `TAGS` est `shallow` par défaut.

### Les 50 scénarios

Tous sous `bench/scenarios/canonical/`, tous `shallow` à ce jour.

| Lot | Fichiers | Couvre |
|---|---|---|
| **Signaux** (5) | `scenario_{d,e,f,g,h}_*` | hitl_refusal / hallucination_block / memory recall / provider_switch / prompt_version chain (Sprint 3.7 V1) |
| **Critique-replay** (30) | `scenario_critique_01..30_*` | verdicts du LLM-as-judge → `capture_from_mission_critique` (filtre actionnabilité + `pattern_hash`) + round-trip learning-report. Auto-générés (voir ci-dessous). |
| **Catalogués** (10) | `scenario_{i..r}_*` | HITL préférences/deny/timeout, completion_guard (détection + pipeline), chaînes multi-signaux, learning-report, memory cross-conv, MCP registration, skill_view |
| **Structurels** (5) | `scenario_{s..w}_*` | Phase 5.b list/pin/forget, MCP admin CRUD, user_state idempotence, mémoire 5-types, FTS5 recall |

### Scénarios critique-replay générés

`mission_critiques` est vide sur une instance perso (usage conversationnel,
pas mission-driven) → les 30 scénarios critique sont **synthétiques**, produits
par un catalogue :

```bash
# Dry-run : affiche le plan, n'écrit rien
PYTHONPATH=. backend/.venv/bin/python -m bench.gen_critique_scenarios

# Émet les 30 scenario_critique_*.py
PYTHONPATH=. backend/.venv/bin/python -m bench.gen_critique_scenarios --write

# Supprime les fichiers générés
PYTHONPATH=. backend/.venv/bin/python -m bench.gen_critique_scenarios --clean
```

Les fichiers générés sont **committés** (le runner + la CI les découvrent sur
disque). Pour les modifier : éditer le `CATALOGUE` du générateur, pas les
fichiers de sortie.

### CI nocturne

`.github/workflows/bench-nightly.yml` — cron `0 3 * * *` (03:00 UTC) +
`workflow_dispatch`. Lance `--tag shallow,medium`, publie le tableau par
scénario dans le résumé du run, upload `bench/results/` en artefact (14j). Un
échec rend le job rouge → notification GitHub. Le tag `deep` est exclu.

### Écrire un nouveau scénario

Un scénario = un module `scenario_<id>.py` exposant :

```python
NAME = "<titre court>"
DESCRIPTION = "<une ligne>"
TAGS = ["shallow"]          # optionnel, défaut shallow

async def run() -> dict:    # retourne {"pass": bool, "checks": {...}, "failed_checks": [...]}
    ...
```

Helpers partagés dans `bench/scenarios/_base.py` :
- `throwaway_user(prefix)` — user jetable + **cleanup idempotent** de toutes
  les tables user-scoped à la sortie (missions/critiques incluses, FK-aware).
  **Utilise-le** : un scénario qui crée un `User` inline sans cleanup fuit une
  ligne par run.
- `seed_mission_with_critique(uid, ...)` — seed Mission + MissionCritique.
- `anonymise_text(s)` — scrub PII regex.
- `from_checks({"name": bool})` — convertit en la shape de résultat attendue.

Règle : un scénario doit être **hermétique et idempotent** (re-runnable sur la
DB partagée sans fuite). Pour Qdrant, monkeypatcher le store (cf. `scenario_f`).

### Smoke manuel avant release

```bash
# 1. Suite unit + bench shallow verts
cd backend && uv run pytest -q
cd .. && PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag shallow

# 2. (optionnel) le tier deep, à la main, si des scénarios deep existent
PYTHONPATH=. backend/.venv/bin/python -m bench.run_canonical --tag deep

# 3. Vérifier 0 fuite (users bench nettoyés)
#    (le runner est idempotent ; un reliquat = un scénario à corriger)
```

---

## 2. Bench tokens `orchestrate` (Sprint 2.7)

> **Objectif** : mesurer l'économie tokens et la latence du tool `orchestrate`
> sur des workflows multi-tool. Target : **≥ 60% d'économie tokens médiane**.

Distinct du harness canonique : ce bench-ci mesure un **coût** (tokens/latence),
pas une régression pass/fail. Scénarios sous `bench/scenarios/scenario_{a,b,c}_*`.

### Lancer un scénario (technique, automatisé)

```bash
cd backend
uv run python ../scripts/bench_orchestrate.py ../bench/scenarios/scenario_a_dev_weekly_summary.py
# JSON parseable :
uv run python ../scripts/bench_orchestrate.py ../bench/scenarios/scenario_a_dev_weekly_summary.py --json \
    > ../bench/results/scenario_a-$(date +%Y%m%d).json
```

Mesure : durée wall-clock du sandbox, taille du stdout renvoyé au LLM, liste
ordonnée des tools dispatchés, détection de truncation. Ne mesure **pas** les
tokens du LLM principal ni la qualité (→ protocole manuel).

| Fichier | Tools | Workflow |
|---|---|---|
| `scenario_a_dev_weekly_summary.py` | 5 | Résumé hebdo dev (repo / mémoire / docs / conversations). |
| `scenario_b_memory_audit.py` | 8 | Boucle sur les 7 catégories de mémoire. |
| `scenario_c_no_op_baseline.py` | 0 | Plancher du surcoût sandbox. |

### Bench end-to-end via Ely (manuel)

Poser **la même demande** à Ely deux fois — **sans** puis **avec** `orchestrate`
forcé — et comparer tokens in/out, tool_calls, durée, qualité. Template :

```markdown
| Scenario | Mode | Tool_calls | Tokens in | Tokens out | Durée (s) | Qualité |
|---|---|---|---|---|---|---|
| A | Sans orchestrate | … | … | … | … | … |
| A | Avec orchestrate | … | … | … | … | … |
| **Économie** | | … % | … % | … % | … % | |
```

Tokens : grep `tokens.input` / `tokens.output` dans les logs Docker, ou
dashboard Ely (Settings → Analytics), ou dashboard provider. Sauver une session
par fichier `bench/results/YYYYMMDD.md` pour suivre la médiane.
