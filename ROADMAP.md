# ELY Roadmap

> **TL;DR** — ELY converge sur ce que personne d'autre n'offre dans le monde des agents IA personnels : un agent **self-hosted** qui combine la **surface produit grand public** (UI riche sur tous les canaux) avec un **moat technique unique** (modèle qui apprend et qui appartient au user). Ce document liste les chantiers, leur ordre, et leur valeur différenciatrice.
>
> Last updated: **May 2, 2026** — public launch.
> Maintainer: [Franck OLLIVIER](mailto:contact@agent-ely.fr).

---

## Vision

Trois principes immuables guident ce qu'on construit et ce qu'on refuse :

1. **Le user possède son agent.** Pas de SaaS, pas de cloud forcé, pas de modèle qu'on peut nous éteindre. Hardware du user → données du user → modèle du user.
2. **L'UI doit être un game-changer.** Si grand-mère ne peut pas l'utiliser, c'est pas fini. Web + mobile natif + voix + multi-canal, polish absolu sur chaque surface.
3. **L'agent doit être agentique pour de vrai.** HITL avant l'irréversible, missions goal-driven, sub-agents quand utile, auto-amélioration mesurable.

Tout chantier qui contredit l'un de ces principes est rejeté, peu importe l'effet de mode.

---

## Comment lire cette roadmap

| Légende | Sens |
|---|---|
| 🟢 **Standard** | Catch-up sur ce qui existe ailleurs, table-stakes |
| 🟡 **Hermes-parity** | Pattern technique éprouvé chez Hermes Agent ou similaire qu'on adopte |
| 🔴 **Unique to ELY** | Différenciateur que personne d'autre n'offre — *le moat* |
| 🔬 **Research** | Exploratoire, ne sera shippé que si ça bat la baseline en éval |

| Effort | Sens |
|---|---|
| **S** | < 1 semaine |
| **M** | 1-3 semaines |
| **L** | 1-2 mois |
| **XL** | 2-4 mois |
| **XXL** | trimestre+ |

---

## Sprint 0 — Public launch ✅ *Mai 2026*

L'objectif a été : ouvrir le repo sans honte ni faille. Catalogue final livré ce jour :

- ✅ Refonte UI complète (Claude.ai handoff, oklch, Inter, dark+light)
- ✅ Multi-domain routing fix (queries croisant 2+ specialists → general)
- ✅ Mode mono-agent (toggle admin pour bypasser le router)
- ✅ Provider Moonshot Kimi K2.x (avec fix température=1 sur reasoning models)
- ✅ Self-improving keyword router (Phase 1 : DB + cache + endpoints, Phase 2 : auto-detection des reformulations via job MAINTENANCE)
- ✅ API key validator côté backend (URL/whitespace/length checks)
- ✅ Anti-hallucination guards (workspace + general prompts)
- ✅ Specialists honor tier config partout
- ✅ README final avec emphase UI graphique différenciante
- ✅ 92/92 pytest, smoke tests OK, no committed secrets

---

## Sprint 1 — Memory recall ⏳ *Mai-Juin 2026*

| # | Item | Type | Effort | Source d'inspiration |
|---|---|---|---|---|
| 1 | **Session search FTS5 + résumé LLM auxiliaire** — Éli retrouve « tu te souviens du projet X il y a 3 mois ? ». Table FTS5 sur SQLite, tool LLM-callable `search_past_conversations(query, limit=3)` qui groupe par session, charge ±100k chars centrés sur les matches, résume via LLM cheap, retourne 3 résumés focalisés. | 🟡 Hermes-parity | M | `hermes_state.py:36-180` + `tools/session_search_tool.py` |

**Pourquoi en premier** : c'est le plus gros gain perçu utilisateur pour l'effort le plus modeste. Aucun agent personnel grand public n'a ça de façon cross-conversation. Ouvre la voie à *"v1.1 — Memory recall"* qui fait du buzz.

**Livrables** :
- Migration SQLite : `messages_fts` (unicode61) + `messages_fts_trigram` pour CJK
- `app/services/session_search.py` avec `search_past_conversations()`
- Tool LLM-callable enregistré dans le registry
- Test de bout-en-bout : ingestion 100 conversations → recherche fuzzy → résumés

---

## Sprint 2 — Developer experience ⏳ *Juin 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 2 | **Tool registry auto-discovery par AST** — un tool s'auto-déclare avec `@register(domain="workspace", schema=...)`. Le supervisor lit la liste depuis le registry. Élimine la triple-registration `_DOMAIN_DESCRIPTIONS`/`_SPECIALIST_PROMPTS`/`_WORKSPACE_SKILLS` documentée comme un piège dans CLAUDE.md. | 🟡 Hermes-parity | S-M | `hermes-agent-main/tools/registry.py:30-72` |

**Pourquoi maintenant** : confort dev quotidien pour Franck + futur·e·s contributeur·rices. Réduit les bugs « tool invisible ». 1 jour à 1 semaine selon la profondeur du refactor.

---

## Sprint 3 — User State Vector ⏳ *Juin-Juillet 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 3 | **User State Vector** — état JSON structuré (`mood`, `current_focus`, `recent_topics`, `open_loops`, `energy_budget`) mis à jour toutes les N messages par le LLM MAINTENANCE. Injecté en début de prompt système. Interrogeable depuis l'UI (« Que penses-tu de moi ? »). C'est l'équivalent fonctionnel d'un *World Model* sans Mamba. | 🔴 Unique to ELY | M | Inspiration LeCun + analyse interne ELY |

**Pourquoi unique** : aucun agent personnel n'expose un état utilisateur structuré et inspectable. Combiné avec l'UI ELY, ça donne un *« profil dynamique »* visible dans Settings → Mon profil ELY. Game-changer pour la perception de personnalisation.

---

## Sprint 4 — MCP integration ⏳ *Juillet-Août 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 4 | **MCP client + server** — ELY consomme tout MCP server (Claude Desktop, Cursor, Zed exposent leurs intégrations) ET s'expose elle-même comme MCP server (apparaît dans Claude Desktop, Cursor, etc.). Pattern `_build_safe_env()` + OSV malware check pour npx/uvx. OAuth manager. | 🟡 Hermes-parity | M-L | `hermes-agent-main/tools/mcp_tool.py` + `mcp_serve.py` |

**Pourquoi** : effet réseau gratuit. Ouvre ELY à l'écosystème dev sans coût marketing. Aujourd'hui MCP est le standard de fait pour étendre Claude Desktop / Cursor / Zed.

---

## Sprint 5 — Personal Knowledge Graph ⏳ *Août-Septembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 5 | **Personal Knowledge Graph** — graphe de connaissances per-user construit au fil des interactions (entités, préférences, patterns, relations). Extraction par LLM MAINTENANCE. Stockage SQLite + relations JSON. Retrieval ciblé en complément du RAG vectoriel actuel. Visualisable dans l'UI (« graphe de ton univers selon Éli »). | 🔴 Unique to ELY | L | LightRAG (Microsoft Research) + custom |

**Pourquoi unique** : combine l'esprit du World Model de LeCun (modèle interne du monde du user) avec une représentation **interprétable** que le user peut inspecter, corriger, exporter. Aucun agent commercial ne fait ça avec ce niveau de transparence.

**Stack envisagée** : LightRAG ou GraphRAG + BGE-M3 embeddings + SQLite (pas de Neo4j externe).

---

## Sprint 6 — Smart approval ⏳ *Septembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 6 | **Smart approval auxiliaire** — un LLM rapide auxiliaire classifie une action critique comme « low-risk » ou « high-risk » et auto-approuve les low-risk sans déranger le user. Plus de hooks plugins `pre_approval_request`/`post_approval_response`. Allowlist persistante per-user. ContextVar thread-safe pour multi-session. | 🟡 Hermes-parity | M | `hermes-agent-main/tools/approval.py:30-90` |

**Pourquoi** : actuellement chaque action critique demande validation, ce qui devient pénible à l'usage. Le smart-approval réduit le bruit HITL de ~70% sans réduire la sécurité (le LLM auxiliaire ne valide que ce qui est trivialement bénin).

---

## Sprint 7 — Predictive tool gate ⏳ *Octobre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 7 | **Predictive tool gate** — avant d'appeler un tool coûteux/critique (LLM appel, Drive search lourd, web scrape), un LLM cheap prédit l'utilité du résultat probable. Si jugé inutile, on skip et on répond depuis la prédiction. Économies tokens massives + UX améliorée. | 🔴 Unique to ELY | M | LeCun WM appliqué à l'agentic |

**Pourquoi unique** : c'est la VRAIE essence du World Model de LeCun (« simuler avant d'agir ») appliquée à un agent texte. Aucun agent open-source ne le fait aujourd'hui. Combiné aux missions ELY, ça réduit les itérations inutiles.

---

## Sprint 8 — Skills marketplace standard ⏳ *Novembre 2026*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 8 | **Format SKILL.md standard + bridge agentskills.io** — adopte le format frontmatter YAML d'Hermes (`name`, `description`, `version`, `metadata.tags`, scripts/références). Permet d'importer les skills d'agentskills.io. ELY hérite d'un écosystème naissant sans tout produire elle-même. | 🟡 Hermes-parity | L | `hermes-agent-main/tools/skills_tool.py` + format `agentskills.io` |

---

## Sprint 9 — LoRA personnel par user ⏳ *Q1 2027*

| # | Item | Type | Effort | Source |
|---|---|---|---|---|
| 9 | **LoRA adapter personnel par user** — chaque user a son adapter LoRA (~200-500 MB) entraîné mensuellement sur Mac Studio en MLX/Unsloth. Base : Qwen2.5-3B ou Phi-3.5-mini. Le user peut **télécharger son `.safetensors`**, le sauvegarder, le restaurer, le partager. Inférence locale, A/B test contre baseline avant deploy. | 🔴 Unique to ELY | XL | Approche Personal AI / Adept, jamais shippée open-source |

**Pourquoi le moat ultime** : aucun agent commercial ne donne au user la *propriété physique* de son modèle d'IA. Le pitch devient : *"Va dans Paramètres → Mon Modèle → Télécharger. C'est à toi. Personne ne peut te l'éteindre."*

**Stack** : MLX-LM (Apple Silicon natif), Unsloth (cross-platform), Qwen2.5-3B-Instruct comme base, eval automatique avant chaque deploy.

---

## Recherche Q1-Q2 2027 — World Model expérimental 🔬

| # | Item | Type | Effort | Hypothèse à valider |
|---|---|---|---|---|
| 10 | **Predictive embedding model** (esprit JEPA texte) — petit modèle (~50-200M params) entraîné à prédire les états futurs probables : « si l'utilisateur vient d'envoyer ce message, quels sont les 3 tools les plus probablement appelés ensuite ? ». Pas génératif. Oracle complémentaire au LLM principal. | 🔬 Research | XXL | « Un modèle prédictif latent peut anticiper les besoins user et pre-fetcher les tools, réduisant la latence perçue de 40% » |

**Mode opératoire** : branch isolée `experimental/jepa-text`, A/B contre baseline (User State Vector), métriques objectives, rollback automatique si dégradation. **Ne sera shippé que si ça bat la baseline en éval.**

---

## Backlog non-prioritaire (à reconsidérer si demande user)

- **Sub-agents avec parallélisation** (`hermes-agent-main/tools/delegate_tool.py`) — utile pour missions très complexes, mais ELY a déjà les missions LangGraph qui couvrent 90% des cas
- **Plugins shell hooks** (`hermes-agent-main/agent/shell_hooks.py`) — ouvre l'extensibilité aux non-Pythonistes, mais peu de demande pour l'instant
- **Multi-canal massif** (au-delà de 5 canaux : Signal, Matrix, Mattermost, Email, etc.) — Hermes en a 18, ELY garde Telegram + Discord + Slack + WhatsApp + iOS + Android. Ajout uniquement sur demande user concrète.
- **6 backends terminal** (Modal, Daytona, Singularity) — pas le use-case ELY (agent personnel, pas dev infra)
- **TUI Ink (terminal client)** — régression vs UI Next.js, n'arrivera jamais

---

## Principes de priorisation appliqués

1. **Ce qui rend ELY unique en premier** (sprints 3, 5, 7, 9 — tous 🔴)
2. **Ce qui réduit la dette technique de Franck** (sprint 2 — fini la triple-registration)
3. **Ce qui prépare le terrain de l'écosystème** (sprints 4, 8 — MCP + SKILL.md)
4. **Ce qui améliore la perception utilisateur immédiate** (sprint 1 — memory recall)
5. **Recherche en parallèle, jamais bloquant** (sprint 10 — JEPA)

---

## Comment contribuer à un sprint

Chaque sprint sera tracké comme une **GitHub Milestone** avec ses issues. Les PRs externes sont les bienvenues, en particulier sur :
- Skills (`backend/app/skills/`) — easy win
- Traductions (`frontend/messages/`) — actuellement FR/EN, on attend ES, DE, IT
- Tests (`backend/tests/`) — il y en a 92 aujourd'hui, on vise 200+ d'ici fin 2026
- Docs (`README.md`, `docs/`) — les retours d'install sont précieux

Voir [CONTRIBUTING.md](./CONTRIBUTING.md) pour les détails.

---

## Versions cibles

| Version | Sprint(s) inclus | ETA |
|---|---|---|
| **v1.1.x** | Sprint 0 (launch) | ✅ Mai 2026 |
| **v1.2** | Sprint 1 (memory recall) | Juin 2026 |
| **v1.3** | Sprint 2 (registry) + Sprint 3 (user state) | Juillet 2026 |
| **v1.4** | Sprint 4 (MCP) | Août 2026 |
| **v1.5** | Sprint 5 (Personal KG) | Septembre 2026 |
| **v1.6** | Sprint 6 (smart approval) + Sprint 7 (predictive gate) | Octobre-Novembre 2026 |
| **v1.7** | Sprint 8 (SKILL.md) | Novembre-Décembre 2026 |
| **v2.0** | Sprint 9 (LoRA personnel) — release majeure « Your Model, Your Control » | Q1 2027 |
| **v2.x** | Sprint 10 (JEPA recherche) — opt-in expérimental | Q2 2027+ |

Toutes les ETAs sont des **objectifs cibles**, pas des promesses. Un agent personnel one-developer-and-an-AI ne suit pas un Gantt d'ESN.

---

## Ce que la roadmap PROMET de ne pas faire

- ❌ Devenir un SaaS multi-tenant avec données chez nous
- ❌ Ajouter du tracking, des cookies tiers, ou de la télémétrie sans opt-in
- ❌ Verrouiller un user dans un provider LLM particulier
- ❌ Cacher les coûts (analytics tokens reste transparent dans le dashboard)
- ❌ Sacrifier l'UI au profit du terminal-first
- ❌ Promettre un World Model avant qu'on ait validé qu'il bat la baseline

---

*« On ne va pas confondre vitesse et précipitation. »* — Franck, 2 mai 2026
